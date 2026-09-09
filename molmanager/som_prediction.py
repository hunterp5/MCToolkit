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

from .structure_draw import configure_mol_drawer, structure_cairo_dimensions

logger = logging.getLogger(__name__)

NERDD_API_BASE = "https://nerdd.univie.ac.at/api"
DEFAULT_THRESHOLD = 0.3
DEFAULT_BATCH_SIZE = 10
DEFAULT_POLL_INTERVAL_S = 2.0
DEFAULT_JOB_TIMEOUT_S = 600.0
_USER_AGENT = "MolManager/1.0 (FAME3R SOM; local desktop app)"
SOM_CANCELLED_ERROR = "Cancelled."

MetabolismSubset = Literal["all", "phase1", "phase2", "cyp"]

METABOLISM_SUBSET_OPTIONS: tuple[tuple[str, str], ...] = (
    ("all", "Phase 1 and 2"),
    ("phase1", "Phase 1"),
    ("phase2", "Phase 2"),
    ("cyp", "CYP-mediated"),
)

SOM_MAP_COLUMN = "SOM Map"
SOM_SITES_COLUMN = "SOM Sites"
SOM_PROB_COLUMN = "SOM Probabilities"
SOM_FAME_COLUMN = "SOM FAME Score"
SOM_ENTROPY_COLUMN = "SOM Entropy"

CancelCallback = Callable[[], bool]


@dataclass(frozen=True)
class SomAtomHit:
    """One atom-level FAME3R prediction."""

    atom_id: int
    probability: float
    is_som: bool
    fame_score: float | None = None
    shannon_entropy: float | None = None


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
        from .workers.process_pool_utils import application_is_shutting_down

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


def _poll_job(
    job_id: str,
    *,
    base: str,
    poll_interval_s: float,
    timeout_s: float,
    cancel: CancelCallback | None,
    progress: Callable[[int, int], None] | None,
) -> dict[str, Any]:
    deadline = time.monotonic() + max(5.0, float(timeout_s))
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        if _app_is_shutting_down() or (cancel is not None and cancel()):
            raise RuntimeError("Cancelled.")
        last = _json_request(f"{base}/jobs/{job_id}", timeout=15.0) or {}
        status = str(last.get("status") or "")
        processed = int(last.get("num_entries_processed") or 0)
        total = int(last.get("num_entries_total") or 0)
        if progress is not None and total > 0:
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
    if metabolism_subset not in {k for k, _ in METABOLISM_SUBSET_OPTIONS}:
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
                # NERDD counts atoms; approximate molecule progress from the chunk.
                frac = processed / max(total, 1)
                progress(_done + max(1, int(round(frac * len(chunk)))), n_pending)

            job = _poll_job(
                job_id,
                base=base,
                poll_interval_s=poll_interval_s,
                timeout_s=timeout_s,
                cancel=cancel,
                progress=_chunk_progress,
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


def format_som_columns(
    pred: SomMoleculePrediction | None,
    *,
    include_fame: bool = False,
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
    return row


def som_output_columns(*, include_fame: bool) -> list[str]:
    cols = [SOM_MAP_COLUMN, SOM_SITES_COLUMN, SOM_PROB_COLUMN, SOM_ENTROPY_COLUMN]
    if include_fame:
        cols.insert(3, SOM_FAME_COLUMN)
    return cols


def _som_rgb(probability: float) -> tuple[float, float, float]:
    """Yellow (low) to orange-red (high) highlight color."""
    t = min(max(float(probability), 0.0), 1.0)
    return (1.0 - 0.05 * t, 0.92 - 0.50 * t, 0.22 - 0.14 * t)


# Cyan-blue, distinct from the yellow→red SOM probability scale.
_SOM_EMPHASIS_RGB = (0.10, 0.58, 1.00)


def _apply_emphasized_atom(
    mol: Chem.Mol,
    *,
    atom_id: int,
    highlight: list[int],
    colors: dict[int, tuple[float, float, float]],
    radii: dict[int, float],
    bonds: list[int],
    bond_colors: dict[int, tuple[float, float, float]],
) -> None:
    """Make one atom pop on the map (browser row selection)."""
    n_atoms = mol.GetNumAtoms()
    if atom_id < 0 or atom_id >= n_atoms:
        return
    if atom_id not in highlight:
        highlight.append(atom_id)
    colors[atom_id] = _SOM_EMPHASIS_RGB
    radii[atom_id] = 0.88
    atom = mol.GetAtomWithIdx(atom_id)
    if not atom.HasProp("atomNote"):
        atom.SetProp("atomNote", str(atom_id))
    for bond in atom.GetBonds():
        bi = bond.GetIdx()
        if bi not in bond_colors:
            bonds.append(bi)
        bond_colors[bi] = _SOM_EMPHASIS_RGB


def render_som_map_png(
    smiles: str,
    atoms: tuple[SomAtomHit, ...] | list[SomAtomHit],
    *,
    width: int,
    height: int,
    min_highlight: float = 0.05,
    emphasize_atom: int | None = None,
) -> bytes | None:
    """Draw a 2D map with SOM probabilities as atom highlights and labels."""
    mol = Chem.MolFromSmiles((smiles or "").strip())
    if mol is None or mol.GetNumAtoms() == 0:
        return None
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
        colors[idx] = _som_rgb(hit.probability)
        radii[idx] = 0.55 if hit.is_som else 0.38
        atom = mol.GetAtomWithIdx(idx)
        if hit.is_som:
            atom.SetProp("atomNote", f"{hit.probability:.2f}")
    bonds: list[int] = []
    bond_colors: dict[int, tuple[float, float, float]] = {}
    highlight_set = set(highlight)
    prob_by_atom = {int(h.atom_id): h.probability for h in atoms}
    if highlight_set:
        for bond in mol.GetBonds():
            a = bond.GetBeginAtomIdx()
            b = bond.GetEndAtomIdx()
            if a in highlight_set and b in highlight_set:
                bonds.append(bond.GetIdx())
                pa = prob_by_atom.get(a, 0.0)
                pb = prob_by_atom.get(b, 0.0)
                bond_colors[bond.GetIdx()] = _som_rgb(0.5 * (pa + pb))
    if emphasize_atom is not None:
        _apply_emphasized_atom(
            mol,
            atom_id=int(emphasize_atom),
            highlight=highlight,
            colors=colors,
            radii=radii,
            bonds=bonds,
            bond_colors=bond_colors,
        )
    cw, ch = structure_cairo_dimensions(width, height)
    drawer = rdMolDraw2D.MolDraw2DCairo(int(cw), int(ch))
    configure_mol_drawer(drawer, int(cw))
    opts = drawer.drawOptions()
    opts.annotationFontScale = 0.75
    try:
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
            except TypeError:
                rdMolDraw2D.PrepareAndDrawMolecule(
                    drawer,
                    mol,
                    highlightAtoms=highlight,
                    highlightAtomColors=colors,
                    highlightAtomRadii=radii,
                )
        else:
            rdMolDraw2D.PrepareAndDrawMolecule(drawer, mol)
    except Exception:
        logger.debug("SOM map render failed for %s", smiles[:80], exc_info=True)
        return None
    drawer.FinishDrawing()
    png = drawer.GetDrawingText()
    return png if png else None
