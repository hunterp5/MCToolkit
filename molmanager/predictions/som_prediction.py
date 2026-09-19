# This file is part of MolManager.
# Copyright (C) 2026 Hunter Picard
#
# MolManager is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# MolManager is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with MolManager.  If not, see <https://www.gnu.org/licenses/>.

"""FAME3R site-of-metabolism (SOM) prediction via the NERDD REST API.

Models and service: Jacob et al., *J. Cheminform.* 2026,
https://doi.org/10.1186/s13321-026-01161-1 — https://nerdd.univie.ac.at/fame3r
"""

from __future__ import annotations

import json
import logging
import math
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from rdkit import Chem
from rdkit.Chem.Draw import rdMolDraw2D

from ..chem.structure_2d_depiction import configure_mol_drawer, structure_cairo_dimensions

logger = logging.getLogger(__name__)

NERDD_API_BASE = "https://nerdd.univie.ac.at/api"
DEFAULT_THRESHOLD = 0.3
DEFAULT_BATCH_SIZE = 10
DEFAULT_POLL_INTERVAL_S = 2.0
DEFAULT_JOB_TIMEOUT_S = 600.0
_USER_AGENT = "MolManager/1.0 (FAME3R SOM; local desktop app)"
SOM_CANCELLED_ERROR = "Cancelled."

MetabolismSubset = Literal["all", "phase1", "phase2", "cyp"]
COMBINED_PHASES_SUBSET: MetabolismSubset = "all"

NERDD_METABOLISM_SUBSETS: tuple[tuple[str, str], ...] = (
    ("all", "Phase 1 and 2"),
    ("phase1", "Phase 1"),
    ("phase2", "Phase 2"),
    ("cyp", "CYP-mediated"),
)
METABOLISM_SUBSET_OPTIONS: tuple[tuple[str, str], ...] = NERDD_METABOLISM_SUBSETS

SOM_MAP_COLUMN = "SOM Map"
SOM_SITES_COLUMN = "SOM Sites"
SOM_P1_SITES_COLUMN = "SOM Sites Phase 1"
SOM_P2_SITES_COLUMN = "SOM Sites Phase 2"
SOM_PHASE_COLUMN = "SOM Phase"
SOM_PROB_COLUMN = "SOM Probabilities"
SOM_FAME_COLUMN = "SOM FAME Score"
SOM_ENTROPY_COLUMN = "SOM Entropy"


def is_som_map_header(header: str) -> bool:
    """True for the Predict SOM map column (including numbered duplicates)."""
    h = (header or "").strip().lower()
    return h == "som map" or h.startswith("som map ")


def uses_split_phase_jobs(metabolism_subset: str) -> bool:
    """True when Phase 1 and 2 runs two NERDD jobs and merges site columns."""
    return str(metabolism_subset) == COMBINED_PHASES_SUBSET


CancelCallback = Callable[[], bool]


@dataclass(frozen=True)
class SomAtomHit:
    """One atom-level FAME3R prediction."""

    atom_id: int
    probability: float
    is_som: bool
    fame_score: float | None = None
    shannon_entropy: float | None = None
    is_phase1_som: bool | None = None
    is_phase2_som: bool | None = None
    phase1_probability: float | None = None
    phase2_probability: float | None = None


@dataclass(frozen=True)
class SomMoleculePrediction:
    """SOM predictions for one input molecule."""

    smiles: str
    preprocessed_smiles: str
    atoms: tuple[SomAtomHit, ...]
    error: str | None = None


def fame3r_api_base() -> str:
    """NERDD API root; override with ``MOLMANAGER_FAME3R_API_BASE``."""
    raw = (os.environ.get("MOLMANAGER_FAME3R_API_BASE") or "").strip()
    return raw.rstrip("/") if raw else NERDD_API_BASE


def shannon_binary_entropy(probability: float) -> float:
    """Shannon entropy of a Bernoulli SOM probability (base 2, range 0–1)."""
    p = min(max(float(probability), 1e-12), 1.0 - 1e-12)
    return float(-(p * math.log2(p) + (1.0 - p) * math.log2(1.0 - p)))


def _app_is_shutting_down() -> bool:
    try:
        from ..workers.process_pool_utils import application_is_shutting_down

        return bool(application_is_shutting_down())
    except Exception:
        return False


def _json_request(
    url: str,
    *,
    method: str = "GET",
    form: list[tuple[str, str]] | None = None,
    timeout: float = 60.0,
) -> Any:
    if _app_is_shutting_down():
        raise RuntimeError("Cancelled.")
    data = None if form is None else urllib.parse.urlencode(form).encode("utf-8")
    headers = {"Accept": "application/json", "User-Agent": _USER_AGENT}
    if data is not None:
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", errors="replace")[:2000]
        except Exception:
            pass
        raise RuntimeError(f"FAME3R HTTP {e.code}: {body or e.reason}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"FAME3R network error: {e}") from e
    if not raw.strip():
        return {}
    return json.loads(raw)


def _bool_form(value: bool) -> str:
    return "true" if value else "false"


def _as_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_atom_row(row: dict[str, Any], *, threshold: float) -> SomAtomHit | None:
    atom_id = _as_int(row.get("atom_id"))
    prob = _as_float(row.get("prediction"))
    if atom_id is None or prob is None:
        return None
    binary = row.get("prediction_binary")
    if isinstance(binary, bool):
        is_som = binary if abs(threshold - DEFAULT_THRESHOLD) < 1e-12 else prob > threshold
    else:
        is_som = prob > threshold
    fame = _as_float(row.get("fame_score"))
    entropy = _as_float(row.get("shannon_entropy"))
    if entropy is None:
        entropy = shannon_binary_entropy(prob)
    return SomAtomHit(
        atom_id=atom_id,
        probability=prob,
        is_som=is_som,
        fame_score=fame,
        shannon_entropy=entropy,
    )


def _group_atom_rows(
    rows: list[dict[str, Any]],
    smiles_in: list[str],
    *,
    threshold: float,
) -> list[SomMoleculePrediction]:
    by_mol: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        mol_id = _as_int(row.get("mol_id"))
        if mol_id is None:
            continue
        by_mol[mol_id].append(row)
    out: list[SomMoleculePrediction] = []
    for i, smi in enumerate(smiles_in):
        atom_rows = by_mol.get(i, [])
        if not atom_rows:
            out.append(
                SomMoleculePrediction(
                    smiles=smi,
                    preprocessed_smiles="",
                    atoms=(),
                    error="No FAME3R atoms were returned for this molecule.",
                )
            )
            continue
        problems = atom_rows[0].get("problems") or []
        if problems:
            out.append(
                SomMoleculePrediction(
                    smiles=smi,
                    preprocessed_smiles="",
                    atoms=(),
                    error=str(problems),
                )
            )
            continue
        pre_smi = str(atom_rows[0].get("preprocessed_smiles") or smi)
        hits = tuple(
            hit
            for hit in (_parse_atom_row(r, threshold=threshold) for r in atom_rows)
            if hit is not None
        )
        out.append(
            SomMoleculePrediction(
                smiles=smi,
                preprocessed_smiles=pre_smi,
                atoms=hits,
            )
        )
    return out


def _submit_fame3r_job(
    smiles: list[str],
    *,
    metabolism_subset: MetabolismSubset,
    fame_score: bool,
    shannon_entropy: bool,
    base: str,
) -> str:
    form: list[tuple[str, str]] = [("inputs", smi) for smi in smiles]
    form.append(("metabolism_subset", metabolism_subset))
    form.append(("fame_score", _bool_form(fame_score)))
    form.append(("shannon_entropy", _bool_form(shannon_entropy)))
    payload = _json_request(f"{base}/fame3r/jobs", method="POST", form=form, timeout=120.0)
    job_id = str((payload or {}).get("id") or "").strip()
    if not job_id:
        raise RuntimeError("FAME3R did not return a job id.")
    return job_id


def _compressed_set_count(raw: Any) -> int | None:
    """Count entries from a NERDD ``CompressedSet`` JSON payload (ranges or ints)."""
    if raw is None:
        return None
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return max(0, raw)
    if isinstance(raw, dict):
        counted = _as_int(raw.get("count"))
        if counted is not None:
            return max(0, counted)
        raw = raw.get("ranges") or raw.get("intervals") or raw.get("entries")
    if not isinstance(raw, list):
        return None
    total = 0
    for item in raw:
        if isinstance(item, bool):
            continue
        if isinstance(item, int):
            total += 1
            continue
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            try:
                start, end = int(item[0]), int(item[1])
            except (TypeError, ValueError):
                continue
            total += abs(end - start)
    return total


def _job_entry_progress(job: dict[str, Any], fallback_total: int) -> tuple[int, int]:
    """Map a NERDD job payload to ``(processed, total)`` for UI progress.

    ``num_entries_total`` is often null while the job is queued (``created``), which
    previously skipped progress updates and left Predict SOM at 0%.
    """
    fallback = max(1, int(fallback_total))
    total = _as_int(job.get("num_entries_total"))
    processed = _as_int(job.get("num_entries_processed"))
    if processed is None:
        processed = _compressed_set_count(job.get("entries_processed"))
    if processed is None:
        processed = 0
    pages_done = _as_int(job.get("num_pages_processed")) or 0
    pages_tot = _as_int(job.get("num_pages_total"))
    if (total is None or total <= 0) and pages_tot:
        total = pages_tot
        if processed <= 0 and pages_done:
            processed = pages_done
    if total is None or total <= 0:
        total = fallback
    status = str(job.get("status") or "")
    if status == "completed":
        processed = max(int(processed), int(total))
    return max(0, int(processed)), max(1, int(total))


def _poll_job(
    job_id: str,
    *,
    base: str,
    poll_interval_s: float,
    timeout_s: float,
    cancel: CancelCallback | None,
    progress: Callable[[int, int], None] | None,
    fallback_total: int = 1,
) -> dict[str, Any]:
    deadline = time.monotonic() + max(5.0, float(timeout_s))
    last: dict[str, Any] = {}
    fallback = max(1, int(fallback_total))
    while time.monotonic() < deadline:
        if _app_is_shutting_down() or (cancel is not None and cancel()):
            raise RuntimeError("Cancelled.")
        last = _json_request(f"{base}/jobs/{job_id}", timeout=15.0) or {}
        status = str(last.get("status") or "")
        processed, total = _job_entry_progress(last if isinstance(last, dict) else {}, fallback)
        if progress is not None:
            progress(processed, total)
        if status == "completed":
            return last
        if status == "failed":
            raise RuntimeError("FAME3R job failed on NERDD.")
        interval = max(0.5, float(poll_interval_s))
        slept = 0.0
        while slept < interval:
            if _app_is_shutting_down() or (cancel is not None and cancel()):
                raise RuntimeError("Cancelled.")
            step = min(0.1, interval - slept)
            time.sleep(step)
            slept += step
    raise RuntimeError("FAME3R job timed out waiting for NERDD.")


def _fetch_job_results(job_id: str, *, base: str, n_pages: int) -> list[dict[str, Any]]:
    pages = max(1, int(n_pages))
    rows: list[dict[str, Any]] = []
    for page in range(1, pages + 1):
        payload = _json_request(f"{base}/jobs/{job_id}/results?page={page}", timeout=120.0) or {}
        chunk = payload.get("data") or []
        if isinstance(chunk, list):
            rows.extend(r for r in chunk if isinstance(r, dict))
        pagination = payload.get("pagination") or {}
        total = pagination.get("num_pages_total") or payload.get("job", {}).get("num_pages_total")
        if total is not None:
            try:
                pages = max(pages, int(total))
            except (TypeError, ValueError):
                pass
    return rows


def _delete_job(job_id: str, *, base: str) -> None:
    try:
        _json_request(f"{base}/jobs/{job_id}", method="DELETE", timeout=30.0)
    except Exception:
        logger.debug("Could not delete FAME3R job %s", job_id, exc_info=True)


def predict_soms_batch(
    smiles: list[str],
    *,
    metabolism_subset: MetabolismSubset = "all",
    fame_score: bool = False,
    shannon_entropy: bool = False,
    threshold: float = DEFAULT_THRESHOLD,
    batch_size: int = DEFAULT_BATCH_SIZE,
    poll_interval_s: float = DEFAULT_POLL_INTERVAL_S,
    timeout_s: float = DEFAULT_JOB_TIMEOUT_S,
    cancel: CancelCallback | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> list[SomMoleculePrediction]:
    """Predict SOMs for SMILES strings (empty entries become error results)."""
    if metabolism_subset not in {k for k, _ in NERDD_METABOLISM_SUBSETS}:
        raise ValueError(f"Unknown metabolism subset: {metabolism_subset}")
    base = fame3r_api_base()
    results: list[SomMoleculePrediction | None] = [None] * len(smiles)
    pending: list[tuple[int, str]] = []
    for i, raw in enumerate(smiles):
        smi = (raw or "").strip()
        if not smi:
            results[i] = SomMoleculePrediction(
                smiles="",
                preprocessed_smiles="",
                atoms=(),
                error="Empty SMILES.",
            )
        else:
            pending.append((i, smi))
    n_pending = len(pending)
    done_mols = 0
    chunk_n = max(1, int(batch_size))
    for start in range(0, len(pending), chunk_n):
        if cancel is not None and cancel():
            break
        chunk = pending[start : start + chunk_n]
        chunk_smiles = [s for _, s in chunk]
        job_id = ""
        cancelled = False
        chunk_rows: list[dict[str, Any]] | None = None
        if progress is not None:
            progress(done_mols, n_pending)
        try:
            job_id = _submit_fame3r_job(
                chunk_smiles,
                metabolism_subset=metabolism_subset,
                fame_score=fame_score,
                shannon_entropy=shannon_entropy,
                base=base,
            )

            def _chunk_progress(processed: int, total: int, *, _done=done_mols) -> None:
                if progress is None:
                    return
                # NERDD counts atoms once totals exist; before that, processed stays 0.
                frac = processed / max(total, 1)
                mols = int(round(frac * len(chunk)))
                if processed > 0 and mols < 1:
                    mols = 1
                if processed >= total > 0:
                    mols = len(chunk)
                progress(_done + mols, n_pending)

            job = _poll_job(
                job_id,
                base=base,
                poll_interval_s=poll_interval_s,
                timeout_s=timeout_s,
                cancel=cancel,
                progress=_chunk_progress,
                fallback_total=len(chunk),
            )
            n_pages = int(job.get("num_pages_total") or 1)
            chunk_rows = _fetch_job_results(job_id, base=base, n_pages=n_pages)
        except RuntimeError as e:
            cancelled = str(e) == "Cancelled."
            if not cancelled:
                raise
        finally:
            if job_id and not cancelled and not _app_is_shutting_down():
                _delete_job(job_id, base=base)
        if chunk_rows is None:
            break
        parsed = _group_atom_rows(chunk_rows, chunk_smiles, threshold=threshold)
        for (orig_i, _), pred in zip(chunk, parsed):
            results[orig_i] = pred
        done_mols += len(chunk)
        if progress is not None:
            progress(done_mols, n_pending)
    return [
        r
        if r is not None
        else SomMoleculePrediction(
            smiles[i] if i < len(smiles) else "",
            "",
            (),
            error=SOM_CANCELLED_ERROR,
        )
        for i, r in enumerate(results)
    ]


def _merged_entropy(
    h1: SomAtomHit | None, h2: SomAtomHit | None, probability: float
) -> float | None:
    ranked: list[tuple[float, float]] = []
    for hit in (h1, h2):
        if hit is not None and hit.shannon_entropy is not None:
            ranked.append((abs(float(hit.probability) - probability), float(hit.shannon_entropy)))
    if ranked:
        ranked.sort()
        return ranked[0][1]
    return shannon_binary_entropy(probability)


def som_phase_label(hit: SomAtomHit) -> str:
    """Short P1 / P2 / P1+P2 label for split Phase 1 and 2 atoms."""
    p1 = bool(hit.is_phase1_som)
    p2 = bool(hit.is_phase2_som)
    if p1 and p2:
        return "P1+P2"
    if p1:
        return "P1"
    if p2:
        return "P2"
    return ""


def _pick_merged_error(p1: SomMoleculePrediction, p2: SomMoleculePrediction) -> str | None:
    errs = [e for e in (p1.error, p2.error) if e]
    if not errs:
        return None
    if all(e == SOM_CANCELLED_ERROR for e in errs) and not p1.atoms and not p2.atoms:
        return SOM_CANCELLED_ERROR
    if not p1.atoms and not p2.atoms:
        return p1.error or p2.error
    return None


def merge_phase_predictions(
    phase1: SomMoleculePrediction,
    phase2: SomMoleculePrediction,
) -> SomMoleculePrediction:
    """Combine Phase 1 and Phase 2 FAME3R results for one molecule."""
    err = _pick_merged_error(phase1, phase2)
    smiles = phase1.smiles or phase2.smiles
    if err:
        return SomMoleculePrediction(
            smiles=smiles,
            preprocessed_smiles="",
            atoms=(),
            error=err,
        )
    by_id: dict[int, tuple[SomAtomHit | None, SomAtomHit | None]] = {}
    for hit in phase1.atoms:
        by_id[int(hit.atom_id)] = (hit, None)
    for hit in phase2.atoms:
        prev = by_id.get(int(hit.atom_id), (None, None))
        by_id[int(hit.atom_id)] = (prev[0], hit)
    merged: list[SomAtomHit] = []
    for atom_id, (h1, h2) in sorted(by_id.items()):
        p1_prob = None if h1 is None else float(h1.probability)
        p2_prob = None if h2 is None else float(h2.probability)
        is_p1 = bool(h1 is not None and h1.is_som)
        is_p2 = bool(h2 is not None and h2.is_som)
        probs = [p for p in (p1_prob, p2_prob) if p is not None]
        probability = max(probs) if probs else 0.0
        fame_candidates = [
            h.fame_score
            for h, is_som in ((h1, is_p1), (h2, is_p2))
            if h is not None and h.fame_score is not None and is_som
        ]
        if not fame_candidates:
            fame_candidates = [
                h.fame_score for h in (h1, h2) if h is not None and h.fame_score is not None
            ]
        entropy = _merged_entropy(h1, h2, probability)
        merged.append(
            SomAtomHit(
                atom_id=atom_id,
                probability=probability,
                is_som=is_p1 or is_p2,
                fame_score=max(fame_candidates) if fame_candidates else None,
                shannon_entropy=entropy,
                is_phase1_som=is_p1,
                is_phase2_som=is_p2,
                phase1_probability=p1_prob,
                phase2_probability=p2_prob,
            )
        )
    pre = phase1.preprocessed_smiles or phase2.preprocessed_smiles or smiles
    return SomMoleculePrediction(
        smiles=smiles,
        preprocessed_smiles=pre,
        atoms=tuple(merged),
    )


def format_som_columns(
    pred: SomMoleculePrediction | None,
    *,
    include_fame: bool = False,
    include_phases: bool = False,
) -> dict[str, str]:
    """Table text columns for one molecule (map column holds SMILES / error)."""
    if pred is None or pred.error:
        row = {
            SOM_MAP_COLUMN: (pred.error if pred and pred.error else "N/A"),
            SOM_SITES_COLUMN: "N/A",
            SOM_PROB_COLUMN: "N/A",
            SOM_ENTROPY_COLUMN: "N/A",
        }
        if include_fame:
            row[SOM_FAME_COLUMN] = "N/A"
        if include_phases:
            row[SOM_P1_SITES_COLUMN] = "N/A"
            row[SOM_P2_SITES_COLUMN] = "N/A"
            row[SOM_PHASE_COLUMN] = "N/A"
        return row
    soms = sorted(
        [a for a in pred.atoms if a.is_som],
        key=lambda a: (-a.probability, a.atom_id),
    )
    ranked = sorted(pred.atoms, key=lambda a: (-a.probability, a.atom_id))
    sites = ", ".join(str(a.atom_id) for a in soms) if soms else "—"
    top = ranked[:12]
    probs = "; ".join(f"{a.atom_id}:{a.probability:.2f}" for a in top)
    if len(ranked) > 12:
        probs += " …"
    entropies = [a.shannon_entropy for a in soms if a.shannon_entropy is not None]
    if not entropies and ranked:
        entropies = [ranked[0].shannon_entropy] if ranked[0].shannon_entropy is not None else []
    entropy_txt = f"{sum(entropies) / len(entropies):.2f}" if entropies else "N/A"
    row = {
        SOM_MAP_COLUMN: pred.preprocessed_smiles or pred.smiles,
        SOM_SITES_COLUMN: sites,
        SOM_PROB_COLUMN: probs or "N/A",
        SOM_ENTROPY_COLUMN: entropy_txt,
    }
    if include_fame:
        fames = [a.fame_score for a in soms if a.fame_score is not None]
        if not fames:
            fames = [a.fame_score for a in ranked[:3] if a.fame_score is not None]
        row[SOM_FAME_COLUMN] = f"{sum(fames) / len(fames):.2f}" if fames else "N/A"
    if include_phases:
        p1 = sorted(
            [a for a in pred.atoms if a.is_phase1_som],
            key=lambda a: (-(a.phase1_probability or a.probability), a.atom_id),
        )
        p2 = sorted(
            [a for a in pred.atoms if a.is_phase2_som],
            key=lambda a: (-(a.phase2_probability or a.probability), a.atom_id),
        )
        row[SOM_P1_SITES_COLUMN] = ", ".join(str(a.atom_id) for a in p1) if p1 else "—"
        row[SOM_P2_SITES_COLUMN] = ", ".join(str(a.atom_id) for a in p2) if p2 else "—"
        phase_bits = []
        for a in soms:
            label = som_phase_label(a)
            if label:
                phase_bits.append(f"{a.atom_id}:{label}")
        row[SOM_PHASE_COLUMN] = "; ".join(phase_bits) if phase_bits else "—"
    return row


def som_output_columns(*, include_fame: bool, include_phases: bool = False) -> list[str]:
    cols = [SOM_MAP_COLUMN, SOM_SITES_COLUMN]
    if include_phases:
        cols.extend([SOM_P1_SITES_COLUMN, SOM_P2_SITES_COLUMN, SOM_PHASE_COLUMN])
    cols.extend([SOM_PROB_COLUMN, SOM_ENTROPY_COLUMN])
    if include_fame:
        cols.insert(-1, SOM_FAME_COLUMN)
    return cols


def som_atom_label(atom_id: int, probability: float) -> str:
    """Map annotation: atom index and SOM probability."""
    return f"{int(atom_id)}; {float(probability):.2f}"


def som_probability_rgb(probability: float) -> tuple[float, float, float]:
    """Yellow (low) to orange-red (high) highlight color."""
    t = min(max(float(probability), 0.0), 1.0)
    return (1.0 - 0.05 * t, 0.92 - 0.50 * t, 0.22 - 0.14 * t)


def _apply_emphasized_atom(
    mol: Chem.Mol,
    *,
    atom_id: int,
    highlight: list[int],
    colors: dict[int, tuple[float, float, float]],
    radii: dict[int, float],
    atom_color: tuple[float, float, float] | None = None,
    probability: float | None = None,
) -> None:
    """Slightly enlarge one atom on the map without changing its highlight hue."""
    n_atoms = mol.GetNumAtoms()
    if atom_id < 0 or atom_id >= n_atoms:
        return
    if atom_id not in highlight:
        highlight.append(atom_id)
    keep = colors.get(atom_id) or atom_color or som_probability_rgb(0.5)
    colors[atom_id] = keep
    radii[atom_id] = radii.get(atom_id, 0.38) + 0.10
    atom = mol.GetAtomWithIdx(atom_id)
    if not atom.HasProp("atomNote"):
        if probability is None:
            atom.SetProp("atomNote", str(atom_id))
        else:
            atom.SetProp("atomNote", som_atom_label(atom_id, probability))


def _match_reference_2d(mol: Chem.Mol, reference: Chem.Mol | None) -> None:
    """Orient *mol* like the table Structure column when a 2D reference is available."""
    if mol is None or reference is None:
        return
    if mol.GetNumAtoms() == 0 or reference.GetNumAtoms() == 0:
        return
    try:
        from rdkit.Chem import rdDepictor
    except Exception:
        return
    ref = Chem.Mol(reference)
    try:
        if ref.GetNumConformers() == 0:
            rdDepictor.Compute2DCoords(ref)
        elif bool(ref.GetConformer().Is3D()):
            rdDepictor.Compute2DCoords(ref)
    except Exception:
        return
    try:
        rdDepictor.GenerateDepictionMatching2DStructure(mol, ref)
    except Exception:
        logger.debug("SOM map could not match structure-column orientation", exc_info=True)


def _draw_som_molecule(
    drawer: rdMolDraw2D.MolDraw2DCairo,
    mol: Chem.Mol,
    *,
    highlight: list[int],
    colors: dict[int, tuple[float, float, float]],
    radii: dict[int, float],
    bonds: list[int],
    bond_colors: dict[int, tuple[float, float, float]],
) -> None:
    """Draw *mol* with the same scale path as table 2D depictions."""
    if highlight:
        try:
            rdMolDraw2D.PrepareAndDrawMolecule(
                drawer,
                mol,
                highlightAtoms=highlight,
                highlightAtomColors=colors,
                highlightAtomRadii=radii,
                highlightBonds=bonds,
                highlightBondColors=bond_colors,
            )
            return
        except TypeError:
            rdMolDraw2D.PrepareAndDrawMolecule(
                drawer,
                mol,
                highlightAtoms=highlight,
                highlightAtomColors=colors,
                highlightAtomRadii=radii,
            )
            return
    rdMolDraw2D.PrepareAndDrawMolecule(drawer, mol)


def render_som_map_png(
    smiles: str,
    atoms: tuple[SomAtomHit, ...] | list[SomAtomHit],
    *,
    width: int,
    height: int,
    min_highlight: float = 0.05,
    emphasize_atom: int | None = None,
    reference_mol: Chem.Mol | None = None,
) -> bytes | None:
    """Draw a 2D map with SOM probabilities as atom highlights and labels."""
    mol = Chem.MolFromSmiles((smiles or "").strip())
    if mol is None or mol.GetNumAtoms() == 0:
        return None
    _match_reference_2d(mol, reference_mol)
    n_atoms = mol.GetNumAtoms()
    highlight: list[int] = []
    colors: dict[int, tuple[float, float, float]] = {}
    radii: dict[int, float] = {}
    for hit in atoms:
        idx = int(hit.atom_id)
        if idx < 0 or idx >= n_atoms:
            continue
        if hit.probability < min_highlight and not hit.is_som:
            continue
        highlight.append(idx)
        colors[idx] = som_probability_rgb(hit.probability)
        radii[idx] = 0.55 if hit.is_som else 0.38
        atom = mol.GetAtomWithIdx(idx)
        if hit.is_som:
            atom.SetProp("atomNote", som_atom_label(idx, hit.probability))
    bonds: list[int] = []
    bond_colors: dict[int, tuple[float, float, float]] = {}
    highlight_set = set(highlight)
    color_by_atom = {int(h.atom_id): som_probability_rgb(h.probability) for h in atoms}
    if highlight_set:
        for bond in mol.GetBonds():
            a = bond.GetBeginAtomIdx()
            b = bond.GetEndAtomIdx()
            if a in highlight_set and b in highlight_set:
                bonds.append(bond.GetIdx())
                ca = color_by_atom.get(a, som_probability_rgb(0.5))
                cb = color_by_atom.get(b, som_probability_rgb(0.5))
                bond_colors[bond.GetIdx()] = tuple((x + y) / 2.0 for x, y in zip(ca, cb))
    if emphasize_atom is not None:
        eid = int(emphasize_atom)
        _apply_emphasized_atom(
            mol,
            atom_id=eid,
            highlight=highlight,
            colors=colors,
            radii=radii,
            atom_color=color_by_atom.get(eid),
            probability=next(
                (float(h.probability) for h in atoms if int(h.atom_id) == eid),
                None,
            ),
        )
    cw, ch = structure_cairo_dimensions(width, height)
    drawer = rdMolDraw2D.MolDraw2DCairo(int(cw), int(ch))
    configure_mol_drawer(drawer, int(cw))
    opts = drawer.drawOptions()
    opts.annotationFontScale = 0.75
    try:
        _draw_som_molecule(
            drawer,
            mol,
            highlight=highlight,
            colors=colors,
            radii=radii,
            bonds=bonds,
            bond_colors=bond_colors,
        )
    except Exception:
        logger.debug("SOM map render failed for %s", smiles[:80], exc_info=True)
        return None
    drawer.FinishDrawing()
    png = drawer.GetDrawingText()
    return png if png else None
