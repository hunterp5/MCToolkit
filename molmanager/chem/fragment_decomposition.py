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

"""BRICS and RECAP fragment decomposition and recomposition (RDKit, no Qt)."""

from __future__ import annotations

import re
import threading
from collections.abc import Callable
from typing import Literal

from rdkit import Chem
from rdkit.Chem import BRICS, Recap

from ..platform_support.config import load_config
from .fragment_recomposition_filters import (
    compile_recomposition_filters,
    parse_recomposition_filter_text,
    product_passes_compiled,
)

DecompositionMethod = Literal["brics", "recap"]
RecompositionMethod = Literal["brics", "recap"]

_FRAGMENT_COL_RE = re.compile(r"^(.+)_(\d+)$")


def decompose_brics(mol: Chem.Mol) -> list[str]:
    """Return sorted BRICS fragment SMILES for ``mol`` (may be a single fragment)."""
    frags = BRICS.BRICSDecompose(mol)
    return sorted(str(s) for s in frags)


def decompose_recap(mol: Chem.Mol) -> list[str]:
    """Return sorted RECAP leaf fragment SMILES; use the root when no leaves exist."""
    tree = Recap.RecapDecompose(mol)
    if tree is None:
        return []
    leaves = tree.GetLeaves()
    if leaves:
        return sorted(str(k) for k in leaves.keys())
    if tree.smiles:
        return [str(tree.smiles)]
    return []


def decompose_fragments(mol: Chem.Mol, method: DecompositionMethod) -> list[str]:
    if method == "brics":
        return decompose_brics(mol)
    return decompose_recap(mol)


def assemble_fragment_table_rows(
    oids: list[int],
    per_row_fragments: list[list[str]],
    column_prefix: str,
) -> tuple[list[tuple[int, dict[str, str]]], list[str]]:
    """Build table rows and column headers; pad short rows with ``N/A``."""
    prefix = (column_prefix or "Frag").strip() or "Frag"
    max_n = max((len(fr) for fr in per_row_fragments), default=0)
    if max_n == 0:
        return [], []
    headers = [f"{prefix}_{i}" for i in range(1, max_n + 1)]
    rows: list[tuple[int, dict[str, str]]] = []
    for oid, frags in zip(oids, per_row_fragments, strict=True):
        row = {h: (frags[i] if i < len(frags) else "N/A") for i, h in enumerate(headers)}
        rows.append((int(oid), row))
    return rows, headers


def detect_fragment_column_prefixes(headers: list[str]) -> list[str]:
    """Return sorted unique prefixes from columns like ``BRICS_1``, ``RECAP_2``."""
    found: set[str] = set()
    for h in headers:
        m = _FRAGMENT_COL_RE.match((h or "").strip())
        if m:
            found.add(m.group(1))
    return sorted(found, key=str.lower)


def fragment_columns_for_prefix(headers: list[str], prefix: str) -> list[str]:
    """Ordered ``PREFIX_1``, ``PREFIX_2``, … column names present in ``headers``."""
    pref = (prefix or "").strip()
    if not pref:
        return []
    cols = [h for h in headers if _FRAGMENT_COL_RE.match(h) and h.startswith(f"{pref}_")]
    return sorted(cols, key=lambda name: int(_FRAGMENT_COL_RE.match(name).group(2)))


def _recap_smiles_for_brics_coupling(smi: str) -> str:
    """Map RECAP ``*`` attachment points to BRICS-style ``[16*]`` for coupling."""
    return re.sub(r"(?<!\[)\*(?!\])", "[16*]", smi)


def fragment_smiles_to_mol(smi: str, method: RecompositionMethod) -> Chem.Mol | None:
    """Parse a decomposition fragment SMILES for recomposition."""
    text = (smi or "").strip()
    if not text or text.upper() == "N/A":
        return None
    if method == "recap":
        text = _recap_smiles_for_brics_coupling(text)
    return Chem.MolFromSmiles(text)


def unique_fragment_smiles(fragment_smiles: list[str]) -> list[str]:
    """Stable unique list, skipping blanks and ``N/A``."""
    seen: set[str] = set()
    out: list[str] = []
    for smi in fragment_smiles:
        text = (smi or "").strip()
        if not text or text.upper() == "N/A" or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def recompose_fragments(
    fragment_smiles: list[str],
    method: RecompositionMethod,
    *,
    max_depth: int = 3,
    max_products: int = 2000,
    uniquify: bool = True,
    output_filters: str = "",
    cancel_event: threading.Event | None = None,
    progress_callback: Callable[[int, int, int], None] | None = None,
) -> tuple[list[str], int, bool]:
    """
    Combine fragment SMILES into new molecules using :func:`BRICS.BRICSBuild`.

    RECAP fragments (``*`` attachment points) are mapped to BRICS dummies before coupling.
    When ``output_filters`` is set, only assemblies that satisfy all constraints are retained;
    ``max_products`` counts accepted products (the build continues until that cap is met or
    candidates are exhausted).

    Returns ``(product_smiles, n_candidates_skipped_by_constraints, cancelled)``.
    """
    if cancel_event is not None and cancel_event.is_set():
        return [], 0, True
    unique = unique_fragment_smiles(fragment_smiles)
    mols: list[Chem.Mol] = []
    for smi in unique:
        mol = fragment_smiles_to_mol(smi, method)
        if mol is not None:
            mols.append(mol)
    if len(mols) < 2:
        raise ValueError("Need at least two distinct, parseable fragments to recompose.")

    rules = parse_recomposition_filter_text(output_filters)
    compiled = compile_recomposition_filters(rules)
    depth = max(1, int(max_depth))
    cap = max(1, int(max_products))
    cfg = load_config()
    max_candidates: int | None = None
    if compiled:
        max_candidates = max(
            int(cfg.recomp_constraint_min_candidates),
            cap * int(cfg.recomp_constraint_candidate_multiplier),
        )
    seen: set[str] = set()
    products: list[str] = []
    skipped = 0
    examined = 0
    last_progress = -1

    def _report_progress() -> None:
        nonlocal last_progress
        if progress_callback is None:
            return
        accepted = len(products)
        if accepted == last_progress and examined % 64 != 0:
            return
        last_progress = accepted
        progress_callback(accepted, cap, examined)

    _report_progress()
    for mol in BRICS.BRICSBuild(
        mols,
        maxDepth=depth,
        uniquify=bool(uniquify),
        scrambleReagents=False,
        onlyCompleteMols=True,
    ):
        examined += 1
        if cancel_event is not None and cancel_event.is_set():
            return sorted(products), skipped, True
        if max_candidates is not None and examined > max_candidates:
            break
        try:
            smi = Chem.MolToSmiles(mol)
        except Exception:
            continue
        if smi in seen:
            continue
        check_mol = Chem.MolFromSmiles(smi)
        if check_mol is None:
            continue
        seen.add(smi)
        if compiled and not product_passes_compiled(check_mol, compiled):
            skipped += 1
            if examined % 16 == 0:
                _report_progress()
            continue
        products.append(smi)
        _report_progress()
        if len(products) >= cap:
            break
    if cancel_event is not None and cancel_event.is_set():
        return sorted(products), skipped, True
    if not products:
        if compiled:
            if max_candidates is not None and examined >= max_candidates:
                raise ValueError(
                    "No products met the generation constraints within the candidate limit. "
                    "Relax the property limits or increase max products."
                )
            raise ValueError(
                "No products met the generation constraints. "
                "Relax the property limits or increase max products."
            )
        raise ValueError("No products were generated from the fragment pool.")
    return sorted(products), skipped, False
