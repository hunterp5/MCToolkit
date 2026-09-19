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

"""Neutralize structures (formal charge → 0)."""

from __future__ import annotations

from rdkit import Chem

from molmanager.descriptors.medchem_descriptors import mol_net_formal_charge
from molmanager.chem.structure_neutralize import neutralize_mol


def test_neutralize_ammonium() -> None:
    mol = Chem.MolFromSmiles("[NH4+]")
    assert mol is not None
    assert mol_net_formal_charge(mol) == 1
    out = neutralize_mol(mol)
    assert out is not None
    assert mol_net_formal_charge(out) == 0


def test_neutralize_carboxylate() -> None:
    mol = Chem.MolFromSmiles("[O-]C(=O)c1ccccc1")
    assert mol is not None
    assert mol_net_formal_charge(mol) == -1
    out = neutralize_mol(mol)
    assert out is not None
    assert mol_net_formal_charge(out) == 0


def test_neutralize_already_neutral() -> None:
    mol = Chem.MolFromSmiles("CCO")
    assert mol is not None
    out = neutralize_mol(mol)
    assert out is not None
    assert mol_net_formal_charge(out) == 0
