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

"""Add explicit hydrogen atoms to RDKit molecules."""

from __future__ import annotations

from rdkit import Chem


def add_explicit_hydrogens(mol: Chem.Mol) -> Chem.Mol | None:
    """
    Return a copy of *mol* with implicit hydrogens expanded to explicit H atoms.

    When a 3D conformer is present, hydrogen coordinates are computed from it.
    """
    if mol is None or mol.GetNumAtoms() == 0:
        return None
    try:
        m = Chem.Mol(mol)
        Chem.SanitizeMol(m)
        if m.GetNumConformers() > 0:
            return Chem.AddHs(m, addCoords=True)
        return Chem.AddHs(m)
    except Exception:
        return None


def remove_explicit_hydrogens(mol: Chem.Mol) -> Chem.Mol | None:
    """Return a copy of *mol* with explicit hydrogen atoms removed (RDKit RemoveHs)."""
    if mol is None or mol.GetNumAtoms() == 0:
        return None
    try:
        m = Chem.Mol(mol)
        Chem.SanitizeMol(m)
        out = Chem.RemoveHs(m)
        if out is None or out.GetNumAtoms() == 0:
            return None
        return out
    except Exception:
        return None
