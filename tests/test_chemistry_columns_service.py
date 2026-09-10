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

"""Tests for pure chemistry column policy helpers."""

from __future__ import annotations

from molmanager.services.chemistry_columns import (
    canonical_smiles_header_for_updates,
    cell_texts_have_parseable_molecule,
    data_headers_confirmed_for_chemistry_tools,
    is_smiles_named_header,
    ordered_headers_for_molecule_lookup,
    skip_chemistry_tool_column_dropdown,
    should_skip_chemical_scan_column,
)
from molmanager.utils import canonical_structure_key_from_smiles, mol_from_binary_blob


def test_skip_chemistry_tool_column_dropdown():
    assert skip_chemistry_tool_column_dropdown("Structure")
    assert skip_chemistry_tool_column_dropdown("pKa")
    assert skip_chemistry_tool_column_dropdown("SOM Map")
    assert skip_chemistry_tool_column_dropdown("SOM Sites Phase 1")
    assert skip_chemistry_tool_column_dropdown("SOM Phase")
    assert skip_chemistry_tool_column_dropdown("Cluster (Morgan)")
    assert not skip_chemistry_tool_column_dropdown("SMILES")


def test_is_smiles_named_header():
    assert is_smiles_named_header("SMILES")
    assert is_smiles_named_header("canonical_smiles")
    assert not is_smiles_named_header("InChIKey")


def test_canonical_smiles_header_for_updates():
    headers = ["ID_HIDDEN", "Structure", "Name", "SMILES", "MW"]
    assert canonical_smiles_header_for_updates(headers) == "SMILES"
    headers2 = ["ID_HIDDEN", "Structure", "mol_smiles"]
    assert canonical_smiles_header_for_updates(headers2) == "mol_smiles"


def test_ordered_headers_prefer_smiles():
    headers = ["ID_HIDDEN", "Structure", "MW", "SMILES", "Name"]
    ordered = ordered_headers_for_molecule_lookup(headers)
    assert ordered[0] == "SMILES"


def test_should_skip_pixmap_via_callback():
    assert should_skip_chemical_scan_column(
        "Render2D",
        is_pixmap_column=lambda h: h == "Render2D",
    )


def test_data_headers_confirmed_structural():
    headers = ["ID_HIDDEN", "Structure", "SMILES", "MW"]
    out = data_headers_confirmed_for_chemistry_tools(headers)
    assert "SMILES" in out
    assert "MW" not in out


def test_cell_texts_have_parseable_molecule():
    assert cell_texts_have_parseable_molecule(["CCO", "not-a-mol"])
    assert not cell_texts_have_parseable_molecule(["", "???"])


def test_canonical_structure_key_from_smiles():
    key = canonical_structure_key_from_smiles("CCO")
    assert key
    assert canonical_structure_key_from_smiles("not-smiles") is None


def test_mol_from_binary_blob_roundtrip():
    from rdkit import Chem

    mol = Chem.MolFromSmiles("CCO")
    assert mol is not None
    rebuilt = mol_from_binary_blob(mol.ToBinary())
    assert rebuilt is not None
    assert Chem.MolToSmiles(rebuilt) == "CCO"
    assert mol_from_binary_blob(None) is None
