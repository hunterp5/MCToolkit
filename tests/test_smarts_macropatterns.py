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

"""Tests for ChemAxon-style SMARTS macropattern expansion."""

from __future__ import annotations

from rdkit import Chem

from molmanager.chem.smarts_macropatterns import expand_cx_smarts_macros, mol_from_smarts


def test_mol_from_smarts_metal_macro_matches_iron() -> None:
    q = mol_from_smarts("[M]")
    assert q is not None
    fe = Chem.MolFromSmiles("Cl[Fe]Cl")
    assert fe is not None
    assert fe.HasSubstructMatch(q)
    organic = Chem.MolFromSmiles("CCO")
    assert organic is not None
    assert not organic.HasSubstructMatch(q)


def test_mol_from_smarts_mh_and_q_macros() -> None:
    mh = mol_from_smarts("[MH]")
    q = mol_from_smarts("[Q]")
    assert mh is not None and q is not None
    fe = Chem.MolFromSmiles("[Fe]")
    assert fe is not None and fe.HasSubstructMatch(mh)
    ethanol = Chem.MolFromSmiles("CCO")
    assert ethanol is not None and ethanol.HasSubstructMatch(q)


def test_expand_preserves_ordinary_smarts() -> None:
    assert expand_cx_smarts_macros("c1ccccc1") == "c1ccccc1"
    assert expand_cx_smarts_macros("[OH]") == "[OH]"
    assert expand_cx_smarts_macros("[Cl]") == "[Cl]"


def test_daylight_logic_examples_parse_and_match() -> None:
    """Canonical Daylight SMARTS and/or/not examples must parse and match as documented."""
    cases = [
        ("[F,Cl,Br,I]", "CF", True),
        ("[F,Cl,Br,I]", "CCO", False),
        ("[!C;R]", "C1CCCCC1", False),  # aliphatic ring carbon
        ("[!C;R]", "O1CCCC1", True),  # ring oxygen
        ("[n&H1]", "[nH]1cccc1", True),
        ("[c,n;H1]", "c1ccccc1", True),
        ("[C,c]=,#[C,c]", "C#CC", True),
        ("[C,c]=,#[C,c]", "CC", False),
        ("*@;!:*", "C1CCCCC1", True),
    ]
    for smarts, smiles, expect in cases:
        q = mol_from_smarts(smarts)
        assert q is not None, smarts
        mol = Chem.MolFromSmiles(smiles)
        assert mol is not None, smiles
        assert bool(mol.HasSubstructMatch(q)) is expect, (smarts, smiles)


def test_expand_metal_inside_list_and_charge() -> None:
    expanded = expand_cx_smarts_macros("[M+2]")
    assert expanded.startswith("[") and expanded.endswith("+2]")
    assert "M+2" not in expanded
    q = mol_from_smarts("[M+2]")
    assert q is not None
    fe = Chem.MolFromSmiles("[Fe+2]")
    assert fe is not None and fe.HasSubstructMatch(q)


def test_native_macros_still_parse() -> None:
    assert mol_from_smarts("[X]") is not None
    assert mol_from_smarts("[A]") is not None
    assert mol_from_smarts("[*]") is not None
