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

"""Disconnect Largest Fragments — fragment collection."""

from __future__ import annotations

from rdkit import Chem

from mctoolkit.chem.fragment_disconnect import (
    collect_fragment_mols,
    largest_fragment_and_rest,
    split_dot_disconnected_smiles,
    split_multi_component_smiles,
)
from mctoolkit.chem.molecule_conversion import mol_to_canonical_smiles


def test_split_dot_disconnected_smiles_respects_brackets() -> None:
    parts = split_dot_disconnected_smiles("CC.[Na+].O")
    assert len(parts) == 3


def test_split_multi_component_smiles_handles_spaced_dots() -> None:
    parts = split_multi_component_smiles("CC . OCC")
    assert len(parts) == 2
    assert parts[0] == "CC"
    assert parts[1] == "OCC"


def test_largest_fragment_and_rest_lists_all_smaller_components() -> None:
    mol = Chem.MolFromSmiles("C.CC.CCC")
    parent, rest = largest_fragment_and_rest(mol, "C.CC.CCC")
    assert parent is not None
    assert parent.GetNumHeavyAtoms() == 3
    rest_parts = [p.strip() for p in rest.split(" . ") if p.strip()]
    assert len(rest_parts) == 2
    assert mol_to_canonical_smiles(Chem.MolFromSmiles("C")) in rest_parts
    assert mol_to_canonical_smiles(Chem.MolFromSmiles("CC")) in rest_parts


def test_identical_counterions_are_all_listed() -> None:
    """Ditosylate-style salts: two identical tosylates must both appear in Fragments."""
    core = "CCCCCCCCCCCC"
    tosyl = "Cc1ccc(S(=O)(=O)[O-])cc1"
    raw = f"{core}.{tosyl}.{tosyl}"
    frags = collect_fragment_mols(None, raw)
    assert len(frags) == 3
    parent, rest = largest_fragment_and_rest(None, raw)
    assert parent is not None
    assert mol_to_canonical_smiles(parent) == mol_to_canonical_smiles(Chem.MolFromSmiles(core))
    rest_parts = [p.strip() for p in rest.split(" . ") if p.strip()]
    assert len(rest_parts) == 2
    ts = mol_to_canonical_smiles(Chem.MolFromSmiles(tosyl))
    assert rest_parts.count(ts) == 2


def test_rerun_on_fragments_column_splits_spaced_components() -> None:
    """Second pass on Fragments cell text (``A . B``) treats each component separately."""
    tosyl = "Cc1ccc(S(=O)(=O)[O-])cc1"
    ts = mol_to_canonical_smiles(Chem.MolFromSmiles(tosyl))
    raw = f"{ts} . {ts}"
    frags = collect_fragment_mols(None, raw)
    assert len(frags) == 2
    parent, rest = largest_fragment_and_rest(None, raw)
    assert parent is not None
    rest_parts = [p.strip() for p in rest.split(" . ") if p.strip()]
    assert len(rest_parts) == 1
    assert rest_parts[0] == ts


def test_collect_fragment_mols_from_dot_smiles_when_single_mol_parsed() -> None:
    mol = Chem.MolFromSmiles("CC.O")
    frags = collect_fragment_mols(mol, "CC.O")
    assert len(frags) >= 2


def test_single_fragment_yields_empty_rest() -> None:
    mol = Chem.MolFromSmiles("c1ccccc1")
    parent, rest = largest_fragment_and_rest(mol)
    assert parent is not None
    assert rest == ""
