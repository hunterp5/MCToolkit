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
# along with MolManager. If not, see <https://www.gnu.org/licenses/>.

"""Compound-table Open / Import / Save format helpers."""

from __future__ import annotations

import gzip
from pathlib import Path

from rdkit import Chem

from molmanager.ingest_text import find_smiles_column
from molmanager.table_file_formats import (
    TABLE_OPEN_FILTER,
    TABLE_SAVE_FILTER,
    iter_mol2_mols,
    iter_pdbqt_mols,
    iter_sdf_mols,
    iter_structure_mols,
    load_xlsx_table,
    logical_suffix,
    table_path_parts,
    write_openbabel_mols,
    write_xlsx_table,
)

_ETHANOL_MOL2 = """@<TRIPOS>MOLECULE
ethanol
 3 2 0 0 0
SMALL
NO_CHARGES

@<TRIPOS>ATOM
      1 C1          0.0000    0.0000    0.0000 C.3       1  LIG  0.0000
      2 C2          1.5000    0.0000    0.0000 C.3       1  LIG  0.0000
      3 O3          2.0000    1.2000    0.0000 O.3       1  LIG  0.0000
@<TRIPOS>BOND
     1     1     2    1
     2     2     3    1
"""

_CARBON_PDBQT = """MODEL 1
REMARK VINA RESULT:      -5.00      0.000      0.000
ATOM      1  C   LIG     1       0.000   0.000   0.000  0.00  0.00     0.000 C
ENDMDL
"""


def _write_sdf(path: Path, smiles: str = "CCO") -> None:
    mol = Chem.MolFromSmiles(smiles)
    assert mol is not None
    writer = Chem.SDWriter(str(path))
    writer.write(mol)
    writer.close()


def test_logical_suffix_strips_gzip() -> None:
    assert table_path_parts("lib.sdf.gz") == (".sdf", True)
    assert logical_suffix("hits.smiles") == ".smiles"
    assert logical_suffix("assay.tsv") == ".tsv"
    assert logical_suffix("file.PDBQT.GZ") == ".pdbqt"


def test_open_save_filters_list_new_formats() -> None:
    assert "*.sd" in TABLE_OPEN_FILTER
    assert "*.smiles" in TABLE_OPEN_FILTER
    assert "*.mol2" in TABLE_OPEN_FILTER
    assert "*.xlsx" in TABLE_OPEN_FILTER
    assert "*.pdbqt" in TABLE_OPEN_FILTER
    assert "*.tsv" in TABLE_OPEN_FILTER
    assert "*.gz" in TABLE_OPEN_FILTER
    assert "*.mol2" in TABLE_SAVE_FILTER
    assert "*.xlsx" in TABLE_SAVE_FILTER
    assert "*.pdbqt" in TABLE_SAVE_FILTER
    assert "*.tsv" in TABLE_SAVE_FILTER


def test_find_smiles_column() -> None:
    assert find_smiles_column(["Name", "SMILES", "IC50"]) == "SMILES"
    assert find_smiles_column(["id", "smi"]) == "smi"
    assert find_smiles_column(["foo", "bar"]) == "foo"
    assert find_smiles_column([]) is None


def test_iter_sd_and_gzip_sdf(tmp_path: Path) -> None:
    sd = tmp_path / "mols.sd"
    _write_sdf(sd)
    mols = list(iter_sdf_mols(sd))
    assert len(mols) == 1
    assert Chem.MolToSmiles(mols[0]) == "CCO"

    gz = tmp_path / "mols.sdf.gz"
    gz.write_bytes(gzip.compress(sd.read_bytes()))
    gz_mols = list(iter_sdf_mols(gz))
    assert len(gz_mols) == 1
    assert Chem.MolToSmiles(gz_mols[0]) == "CCO"


def test_iter_mol2(tmp_path: Path) -> None:
    path = tmp_path / "lig.mol2"
    path.write_text(_ETHANOL_MOL2, encoding="utf-8")
    mols = list(iter_mol2_mols(path))
    assert len(mols) == 1
    assert mols[0].GetNumAtoms() == 3


def test_iter_pdbqt(tmp_path: Path) -> None:
    path = tmp_path / "pose.pdbqt"
    path.write_text(_CARBON_PDBQT, encoding="utf-8")
    mols = list(iter_pdbqt_mols(path))
    assert len(mols) == 1
    assert mols[0].GetNumAtoms() >= 1


def test_xlsx_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "assay.xlsx"
    write_xlsx_table(path, ["SMILES", "Name"], [{"SMILES": "CCO", "Name": "ethanol"}])
    fields, rows = load_xlsx_table(path)
    assert "SMILES" in fields
    assert rows[0]["SMILES"] == "CCO"
    assert rows[0]["Name"] == "ethanol"


def test_openbabel_mol2_write_and_read(tmp_path: Path) -> None:
    mol = Chem.MolFromSmiles("CCO")
    assert mol is not None
    dest = tmp_path / "out.mol2"
    n = write_openbabel_mols(dest, [mol], "mol2")
    assert n == 1
    loaded = list(iter_structure_mols(dest))
    assert len(loaded) == 1
    assert loaded[0].GetNumHeavyAtoms() == 3


def test_universal_load_smiles_and_gzip_csv(tmp_path: Path, qapp) -> None:  # noqa: ARG001
    from molmanager.workers.load_render import UniversalLoadWorker
    from molmanager.workers.signals import WorkerSignals

    smi = tmp_path / "set.smiles"
    smi.write_text("CCO\nc1ccccc1\n", encoding="utf-8")
    csv_path = tmp_path / "set.csv.gz"
    with gzip.open(csv_path, "wt", encoding="utf-8") as fh:
        fh.write("SMILES,Name\nCCO,ethanol\n")

    def _load(path: Path) -> list:
        sig = WorkerSignals()
        batches: list = []
        sig.mols_loaded.connect(lambda batch, _h, _f, _l: batches.append(batch))
        UniversalLoadWorker(str(path), sig, batch_size=50).run()
        return [row for batch in batches for row in batch]

    smi_rows = _load(smi)
    assert len(smi_rows) == 2
    assert smi_rows[0]["SMILES"] == "CCO"

    csv_rows = _load(csv_path)
    assert len(csv_rows) == 1
    assert csv_rows[0]["Name"] == "ethanol"
