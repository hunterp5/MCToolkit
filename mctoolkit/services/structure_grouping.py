# This file is part of mctoolkit.
# Copyright (C) 2026 Hunter Picard
#
# mctoolkit is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# mctoolkit is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with mctoolkit. If not, see <https://www.gnu.org/licenses/>.

"""Deduplicate table rows by chemical structure (no Qt)."""

from __future__ import annotations

from collections import defaultdict

from rdkit import Chem

from ..chem.molecule_conversion import mol_from_job_payload, mol_to_canonical_smiles


def structure_key(mol: Chem.Mol) -> str:
    """Stable key for deduplicating ionization work across rows with the same structure."""
    s = mol_to_canonical_smiles(mol)
    if s:
        return s
    try:
        from rdkit.Chem import inchi

        ik = inchi.MolToInchiKey(mol)
    except Exception:
        ik = ""
    return ik or f"__uid_{id(mol)}__"


def group_rows_by_structure(
    rows: list[tuple[int | None, Chem.Mol | None]],
) -> tuple[list[str], dict[str, Chem.Mol], dict[str, list[int | None]]]:
    """
    Collapse rows to unique structures while preserving first-seen key order.

    Returns ``(ordered_keys, key_to_representative_mol, key_to_source_oids)``.
    """
    order: list[str] = []
    rep: dict[str, Chem.Mol] = {}
    oids: dict[str, list[int | None]] = defaultdict(list)
    for oid, payload in rows:
        mol = mol_from_job_payload(payload)
        if mol is None:
            continue
        k = structure_key(mol)
        if k not in rep:
            order.append(k)
            rep[k] = mol
        oids[k].append(oid)
    return order, rep, dict(oids)
