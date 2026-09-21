# This file is part of MCToolkit.
# Copyright (C) 2026 Hunter Picard
#
# MCToolkit is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# MCToolkit is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with MCToolkit.  If not, see <https://www.gnu.org/licenses/>.

"""Split multi-component structures for Disconnect Largest Fragments."""

from __future__ import annotations

import re

from .molecule_conversion import mol_to_canonical_smiles, parse_molecule_from_cell_text

# App output and common table text: "smi1 . smi2" (spaces around dots).
_MULTI_COMP_DOT_RE = re.compile(r"\s*\.\s*")


def split_dot_disconnected_smiles(smiles: str) -> list[str]:
    """Split multi-component SMILES on ``.`` outside square brackets."""
    text = (smiles or "").strip()
    if not text or "." not in text:
        return []
    parts: list[str] = []
    depth = 0
    start = 0
    for i, ch in enumerate(text):
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth = max(0, depth - 1)
        elif ch == "." and depth == 0:
            part = text[start:i].strip()
            if part:
                parts.append(part)
            start = i + 1
    tail = text[start:].strip()
    if tail:
        parts.append(tail)
    return parts if len(parts) > 1 else []


def split_multi_component_smiles(smiles: str) -> list[str]:
    """
    Split disconnected components from cell text.

    Handles canonical dot notation (``A.B``) and spaced separators (``A . B``)
    written by this tool or pasted from spreadsheets.
    """
    text = (smiles or "").strip()
    if not text:
        return []
    normalized = _MULTI_COMP_DOT_RE.sub(".", text)
    return split_dot_disconnected_smiles(normalized)


def _fragment_sort_key(mol) -> tuple[int, int]:
    return (mol.GetNumHeavyAtoms(), mol.GetNumAtoms())


def _parse_component_smiles(part: str):
    from rdkit import Chem

    piece = (part or "").strip()
    if not piece:
        return None
    try:
        m = Chem.MolFromSmiles(piece)
        if m is not None:
            return m
    except Exception:
        pass
    return parse_molecule_from_cell_text(piece)


def collect_fragment_mols(mol, source_text: str | None = None) -> list:
    """
    All disconnected fragment molecules for one table entry.

    Each physical component is kept even when canonical SMILES match (e.g. two
    identical tosylate counterions). Prefer explicit multi-component text in
    *source_text*; otherwise use RDKit ``GetMolFrags`` on *mol*.
    """
    from rdkit import Chem

    raw = (source_text or "").strip()
    parts = split_multi_component_smiles(raw)
    if len(parts) >= 2:
        frags: list = []
        for part in parts:
            m = _parse_component_smiles(part)
            if m is not None:
                frags.append(m)
        if frags:
            return frags

    if mol is not None:
        frags = list(Chem.GetMolFrags(mol, asMols=True, sanitizeFrags=True))
        if len(frags) >= 2:
            return frags
        if len(frags) == 1:
            return frags

    if raw:
        m = parse_molecule_from_cell_text(_MULTI_COMP_DOT_RE.sub(".", raw))
        if m is not None:
            frags = list(Chem.GetMolFrags(m, asMols=True, sanitizeFrags=True))
            if frags:
                return frags
        one = _parse_component_smiles(raw)
        if one is not None:
            return [one]

    return []


def largest_fragment_and_rest(mol, source_text: str | None = None) -> tuple[object | None, str]:
    """
    Return ``(largest_fragment_mol, smaller_fragments_text)``.

    *smaller_fragments_text* lists every other component as canonical SMILES joined
    with ``" . "`` (empty when there is only one fragment). Identical counterions
    are each listed separately.
    """
    frags = collect_fragment_mols(mol, source_text)
    if not frags:
        return None, ""
    ordered = sorted(frags, key=_fragment_sort_key, reverse=True)
    rest_smiles = [mol_to_canonical_smiles(m) for m in ordered[1:]]
    rest_smiles = [s for s in rest_smiles if s]
    return ordered[0], " . ".join(rest_smiles)
