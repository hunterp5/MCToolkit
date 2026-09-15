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
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with MolManager. If not, see <https://www.gnu.org/licenses/>.

"""PubChem preferred names and synonyms for Calculate Descriptors → Name."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from rdkit import Chem

from molmanager.medchem_descriptors import mol_inchi_key
from molmanager.utils import mol_to_canonical_smiles

logger = logging.getLogger(__name__)

NAME_LOOKUP_FNS = frozenset({"COMMON_NAME", "SYNONYMS"})
MAX_SYNONYMS = 50
_INCHIKEY_BATCH = 25
_PUBCHEM_MIN_INTERVAL_S = 0.21
_PUBCHEM_RETRIES = 3

ProgressFn = Callable[[int, int], None]
FetchInchiBatch = Callable[[list[str], bool, bool], dict[str, "CompoundNames"]]
FetchSmilesOne = Callable[[str, bool, bool], "CompoundNames | None"]


@dataclass(frozen=True)
class CompoundNames:
    """PubChem names for one structure (empty strings mean not found)."""

    common_name: str = ""
    synonyms: str = ""


def int_fns_need_name_lookup(int_fns) -> bool:
    """True when Calculate Descriptors requested PubChem name columns."""
    return any(isinstance(f, str) and f in NAME_LOOKUP_FNS for f in int_fns)


def split_name_lookup_descriptors(
    disp_headers: Sequence[str], int_fns: Sequence[str]
) -> tuple[list[str], list[str], list[str], list[str]]:
    """Split display/internal pairs into local descriptors vs PubChem name columns."""
    local_disp: list[str] = []
    local_fns: list[str] = []
    name_disp: list[str] = []
    name_fns: list[str] = []
    for disp, fn in zip(disp_headers, int_fns):
        if isinstance(fn, str) and fn in NAME_LOOKUP_FNS:
            name_disp.append(str(disp))
            name_fns.append(fn)
        else:
            local_disp.append(str(disp))
            local_fns.append(fn)
    return local_disp, local_fns, name_disp, name_fns


def names_cell_value(record: CompoundNames | None, int_fn: str) -> str:
    """Table cell for a name descriptor; ``N/A`` when PubChem has no value."""
    if record is None:
        return "N/A"
    if int_fn == "COMMON_NAME":
        return record.common_name.strip() or "N/A"
    if int_fn == "SYNONYMS":
        return record.synonyms.strip() or "N/A"
    return "N/A"


def format_synonym_list(names: Sequence[object], *, limit: int = MAX_SYNONYMS) -> str:
    """Deduped, semicolon-separated synonyms with a stable cap."""
    out: list[str] = []
    seen: set[str] = set()
    cap = max(1, int(limit))
    for raw in names:
        text = str(raw or "").strip()
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
        if len(out) >= cap:
            break
    return "; ".join(out)


def _structure_query(mol: Chem.Mol | None) -> tuple[str, str] | None:
    """Prefer InChIKey identity; fall back to canonical SMILES."""
    if mol is None:
        return None
    key = (mol_inchi_key(mol) or "").strip()
    if key:
        return ("inchikey", key)
    smi = (mol_to_canonical_smiles(mol) or "").strip()
    if smi:
        return ("smiles", smi)
    return None


class _RateLimiter:
    def __init__(self, min_interval_s: float = _PUBCHEM_MIN_INTERVAL_S) -> None:
        self._min = max(0.0, float(min_interval_s))
        self._last = 0.0

    def wait(self) -> None:
        if self._min <= 0.0:
            return
        now = time.monotonic()
        delay = self._min - (now - self._last)
        if delay > 0:
            time.sleep(delay)
        self._last = time.monotonic()


def _pubchem_retry(fn, *, retries: int = _PUBCHEM_RETRIES):
    """Retry PubChem HTTP/server errors with linear backoff."""
    last_exc: BaseException | None = None
    for attempt in range(max(1, int(retries))):
        try:
            return fn()
        except Exception as exc:
            last_exc = exc
            name = type(exc).__name__
            if name not in {"PubChemHTTPError", "ServerError", "TimeoutError", "Timeout"}:
                if "HTTP" not in name and "Timeout" not in name and "URLError" not in name:
                    raise
            if attempt + 1 >= retries:
                break
            time.sleep(0.5 * (attempt + 1))
    if last_exc is not None:
        raise last_exc
    return None


def names_from_title_and_synonyms(title: str, synonyms: Sequence[object]) -> CompoundNames:
    """Build a name record from a PubChem Title and synonym list."""
    formatted = format_synonym_list(synonyms)
    common = (title or "").strip()
    if not common:
        for raw in synonyms:
            text = str(raw or "").strip()
            if text:
                common = text
                break
    return CompoundNames(common_name=common, synonyms=formatted)


def fetch_pubchem_names_for_inchikeys(
    inchikeys: Sequence[str],
    *,
    want_common: bool,
    want_synonyms: bool,
    before_request: Callable[[], None] | None = None,
    get_properties=None,
    get_synonyms=None,
) -> dict[str, CompoundNames]:
    """Map InChIKeys to PubChem Title / synonym lists (one or two PUG calls)."""
    keys = [str(k).strip() for k in inchikeys if str(k).strip()]
    if not keys or (not want_common and not want_synonyms):
        return {}
    if get_properties is None or get_synonyms is None:
        import pubchempy as pcp

        if get_properties is None:
            get_properties = pcp.get_properties
        if get_synonyms is None:
            get_synonyms = pcp.get_synonyms
    hook = before_request or (lambda: None)
    props_needed = ["InChIKey"]
    if want_common:
        props_needed.append("Title")

    def _props():
        hook()
        return get_properties(props_needed, keys, "inchikey")

    try:
        props = _pubchem_retry(_props) or []
    except Exception:
        logger.exception("PubChem Title lookup failed for %s InChIKey(s)", len(keys))
        return {}

    out: dict[str, CompoundNames] = {}
    cid_to_key: dict[int, str] = {}
    for row in props:
        if not isinstance(row, dict):
            continue
        key = str(row.get("InChIKey") or "").strip()
        if not key:
            continue
        title = str(row.get("Title") or "").strip() if want_common else ""
        cid = row.get("CID")
        try:
            if cid is not None:
                cid_to_key[int(cid)] = key
        except (TypeError, ValueError):
            pass
        out[key] = CompoundNames(common_name=title, synonyms="")

    if not want_synonyms or not cid_to_key:
        return out

    def _syns():
        hook()
        return get_synonyms(list(cid_to_key.keys()), "cid")

    try:
        syn_rows = _pubchem_retry(_syns) or []
    except Exception:
        logger.exception("PubChem synonym lookup failed for %s CID(s)", len(cid_to_key))
        return out

    for srow in syn_rows:
        if not isinstance(srow, dict):
            continue
        cid = srow.get("CID")
        try:
            key = cid_to_key.get(int(cid)) if cid is not None else None
        except (TypeError, ValueError):
            key = None
        if not key:
            continue
        syns = srow.get("Synonym") or []
        if not isinstance(syns, (list, tuple)):
            syns = [syns]
        prev = out.get(key) or CompoundNames()
        merged = names_from_title_and_synonyms(prev.common_name, syns)
        out[key] = merged
    return out


def fetch_pubchem_names_for_smiles(
    smiles: str,
    *,
    want_common: bool,
    want_synonyms: bool,
    before_request: Callable[[], None] | None = None,
    get_properties=None,
    get_synonyms=None,
) -> CompoundNames | None:
    """Lookup one SMILES when InChIKey generation failed."""
    smi = (smiles or "").strip()
    if not smi or (not want_common and not want_synonyms):
        return None
    if get_properties is None or get_synonyms is None:
        import pubchempy as pcp

        if get_properties is None:
            get_properties = pcp.get_properties
        if get_synonyms is None:
            get_synonyms = pcp.get_synonyms
    hook = before_request or (lambda: None)
    props_needed = ["Title"] if want_common else ["MolecularFormula"]

    def _props():
        hook()
        return get_properties(props_needed, smi, "smiles")

    try:
        props = _pubchem_retry(_props) or []
    except Exception:
        logger.exception("PubChem SMILES lookup failed")
        return None
    if not props:
        return None
    row = props[0] if isinstance(props[0], dict) else {}
    title = str(row.get("Title") or "").strip() if want_common else ""
    cid = row.get("CID")
    syns: list[object] = []
    if want_synonyms and cid is not None:

        def _syns():
            hook()
            return get_synonyms(int(cid), "cid")

        try:
            syn_rows = _pubchem_retry(_syns) or []
        except Exception:
            logger.exception("PubChem SMILES synonym lookup failed")
            syn_rows = []
        if syn_rows and isinstance(syn_rows[0], dict):
            raw = syn_rows[0].get("Synonym") or []
            syns = list(raw) if isinstance(raw, (list, tuple)) else [raw]
    names = names_from_title_and_synonyms(title, syns)
    if not names.common_name and not names.synonyms:
        return None
    return names


def lookup_names_for_mols(
    mols: Sequence[Chem.Mol | None],
    *,
    want_common: bool,
    want_synonyms: bool,
    cancel_event=None,
    on_progress: ProgressFn | None = None,
    fetch_inchikey_batch: FetchInchiBatch | None = None,
    fetch_smiles_one: FetchSmilesOne | None = None,
    min_interval_s: float = _PUBCHEM_MIN_INTERVAL_S,
) -> list[CompoundNames | None]:
    """Look up unique structures, then map names back onto ``mols`` order."""
    n = len(mols)
    if n == 0 or (not want_common and not want_synonyms):
        return [None] * n
    queries = [_structure_query(m) for m in mols]
    inchikeys: list[str] = []
    smiles_list: list[str] = []
    seen_inchi: set[str] = set()
    seen_smi: set[str] = set()
    for q in queries:
        if q is None:
            continue
        ns, ident = q
        if ns == "inchikey" and ident not in seen_inchi:
            seen_inchi.add(ident)
            inchikeys.append(ident)
        elif ns == "smiles" and ident not in seen_smi:
            seen_smi.add(ident)
            smiles_list.append(ident)
    unique_total = len(inchikeys) + len(smiles_list)
    if on_progress is not None:
        on_progress(0, max(unique_total, 1))
    if unique_total == 0:
        return [None] * n

    limiter = _RateLimiter(min_interval_s)
    fetch_inchi = fetch_inchikey_batch or (
        lambda keys, wc, ws: fetch_pubchem_names_for_inchikeys(
            keys, want_common=wc, want_synonyms=ws, before_request=limiter.wait
        )
    )
    fetch_smi = fetch_smiles_one or (
        lambda smi, wc, ws: fetch_pubchem_names_for_smiles(
            smi, want_common=wc, want_synonyms=ws, before_request=limiter.wait
        )
    )

    by_inchi: dict[str, CompoundNames] = {}
    by_smi: dict[str, CompoundNames] = {}
    done = 0

    def _cancelled() -> bool:
        return cancel_event is not None and cancel_event.is_set()

    for start in range(0, len(inchikeys), _INCHIKEY_BATCH):
        if _cancelled():
            break
        batch = inchikeys[start : start + _INCHIKEY_BATCH]
        try:
            by_inchi.update(fetch_inchi(batch, want_common, want_synonyms))
        except Exception:
            logger.exception("PubChem InChIKey name batch failed")
        done += len(batch)
        if on_progress is not None:
            on_progress(min(done, unique_total), unique_total)

    for smi in smiles_list:
        if _cancelled():
            break
        try:
            rec = fetch_smi(smi, want_common, want_synonyms)
        except Exception:
            logger.exception("PubChem SMILES name lookup failed")
            rec = None
        if rec is not None:
            by_smi[smi] = rec
        done += 1
        if on_progress is not None:
            on_progress(min(done, unique_total), unique_total)

    if on_progress is not None:
        on_progress(min(done, unique_total), max(unique_total, 1))

    out: list[CompoundNames | None] = []
    for q in queries:
        if q is None:
            out.append(None)
            continue
        ns, ident = q
        if ns == "inchikey":
            out.append(by_inchi.get(ident))
        else:
            out.append(by_smi.get(ident))
    return out
