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

"""Tests for text-first CSV/SMILES ingest helpers."""

from __future__ import annotations

from molmanager.ingest_text import (
    csv_row_to_cells,
    is_ingest_cell_batch,
    smi_line_to_cells,
    sniff_table_delimiter,
)


def test_csv_row_to_cells_maps_columns():
    row = {"SMILES": "CCO", "Name": "ethanol", "MW": "46.07"}
    cells = csv_row_to_cells(row, smi_col="SMILES", fieldnames=["SMILES", "Name", "MW"])
    assert cells == {"SMILES": "CCO", "Name": "ethanol", "MW": "46.07"}


def test_csv_row_to_cells_skips_empty_smiles():
    assert csv_row_to_cells({"SMILES": "  "}, smi_col="SMILES", fieldnames=["SMILES"]) is None


def test_smi_line_to_cells():
    assert smi_line_to_cells("c1ccccc1") == {"SMILES": "c1ccccc1"}
    assert smi_line_to_cells("smiles") is None


def test_is_ingest_cell_batch():
    assert is_ingest_cell_batch([{"SMILES": "C"}])
    assert not is_ingest_cell_batch([])

    from rdkit import Chem

    assert not is_ingest_cell_batch([Chem.MolFromSmiles("C")])


def test_sniff_table_delimiter_chembl_semicolon() -> None:
    header = (
        '"Molecule ChEMBL ID";"Molecule Name";"Smiles";"Standard Type";'
        '"Standard Value";"Standard Units"\n'
        '"CHEMBL1981481";"";"CCO";"IC50";"19958.0";"nM"\n'
    )
    assert sniff_table_delimiter(header) == ";"


def test_sniff_table_delimiter_comma_and_tab() -> None:
    assert sniff_table_delimiter("SMILES,Name,MW\nCCO,ethanol,46\n") == ","
    assert sniff_table_delimiter("SMILES\tName\tMW\nCCO\tethanol\t46\n") == "\t"
    assert sniff_table_delimiter("id|smiles|ic50\n1|CCO|12\n") == "|"


def test_chembl_semicolon_csv_dictreader_keeps_columns() -> None:
    import csv
    import io

    text = (
        '"Molecule ChEMBL ID";"Smiles";"Standard Value"\n'
        '"CHEMBL1";"CCO";"12.0"\n'
    )
    delim = sniff_table_delimiter(text, default=",")
    row = next(csv.DictReader(io.StringIO(text), delimiter=delim))
    assert delim == ";"
    assert row["Smiles"] == "CCO"
    assert row["Molecule ChEMBL ID"] == "CHEMBL1"
    assert row["Standard Value"] == "12.0"
    cells = csv_row_to_cells(
        row,
        smi_col="Smiles",
        fieldnames=["Molecule ChEMBL ID", "Smiles", "Standard Value"],
    )
    assert cells == {
        "SMILES": "CCO",
        "Molecule ChEMBL ID": "CHEMBL1",
        "Standard Value": "12.0",
    }
