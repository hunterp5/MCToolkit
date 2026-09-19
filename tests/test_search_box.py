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

"""Smina search-box geometry and Prepare sidecar writers."""

from __future__ import annotations

from pathlib import Path

import pytest

from molmanager.docking.search_box import box_from_points, smina_artifact_paths
from molmanager.workers.protein_prepare_smina import (
    ligand_keys_from_structure,
    write_dock_file_artifacts,
    write_smina_prepare_artifacts,
)

_HOLO_PDB = """\
ATOM      1  N   ALA A   1      11.104   6.134  10.000  1.00  0.00           N
ATOM      2  CA  ALA A   1      12.260   6.859  10.000  1.00  0.00           C
ATOM      3  C   ALA A   1      13.498   6.000  10.000  1.00  0.00           C
ATOM      4  O   ALA A   1      13.400   4.780  10.000  1.00  0.00           O
ATOM      5  CB  ALA A   1      12.250   7.800   8.800  1.00  0.00           C
HETATM  100  O81 AXI A2000     -26.050  -1.540  -9.129  1.00 32.47           O
HETATM  101  C80 AXI A2000     -26.813  -2.112  -9.925  1.00 30.83           C
HETATM  201  O   HOH A2002     -11.000   1.000   0.000  1.00 30.00           O
END
"""


def test_box_from_points_matches_smina_autobox_padding():
    box = box_from_points([(0.0, 0.0, 0.0), (2.0, 4.0, 6.0)], padding=4.0)
    assert box.center_x == 1.0
    assert box.center_y == 2.0
    assert box.center_z == 3.0
    assert box.size_x == 10.0
    assert box.size_y == 12.0
    assert box.size_z == 14.0
    assert len(box.wireframe_edges()) == 12
    payload = box.viewer_payload()
    assert payload["active"] is True
    assert len(payload["edges"]) == 12


def test_smina_artifact_paths():
    paths = smina_artifact_paths(Path("out") / "4AGC_prepared.cif")
    assert paths["receptor_pdbqt"].name == "4AGC_prepared_receptor.pdbqt"
    assert paths["ligand_sdf"].name == "4AGC_prepared_ligand.sdf"
    assert paths["ligand_pdb"].name == "4AGC_prepared_ligand.pdb"
    assert paths["box"].name == "4AGC_prepared_box.txt"
    dock = smina_artifact_paths(Path("out") / "holo_smina.pdbqt")
    assert dock["receptor_pdbqt"].name == "holo_smina.pdbqt"
    assert dock["ligand_sdf"].name == "holo_smina_ligand.sdf"


def test_protein_prepare_result_receptor_pdbqt_path():
    from molmanager.workers.protein_prepare_smina import ProteinPrepareResult

    result = ProteinPrepareResult(
        output_path="holo_smina.pdbqt",
        receptor_pdbqt="holo_smina.pdbqt",
    )
    assert result.receptor_pdbqt_path() == "holo_smina.pdbqt"
    sidecar = ProteinPrepareResult(
        output_path="holo_smina.cif",
        receptor_pdbqt="holo_smina_receptor.pdbqt",
    )
    assert sidecar.receptor_pdbqt_path() == "holo_smina_receptor.pdbqt"
    missing = ProteinPrepareResult(output_path="holo.cif")
    assert missing.receptor_pdbqt_path() == ""
    ghost = ProteinPrepareResult(output_path="holo_smina.pdbqt")
    assert ghost.receptor_pdbqt_path() == ""


def test_protein_prepare_result_output_pdbqt_fallback_requires_file(tmp_path):
    from molmanager.workers.protein_prepare_smina import ProteinPrepareResult

    rec = tmp_path / "holo_smina.pdbqt"
    rec.write_text("ATOM\n", encoding="utf-8")
    result = ProteinPrepareResult(output_path=str(rec))
    assert result.receptor_pdbqt_path() == str(rec)


def test_write_smina_artifacts_holo_skips_water(tmp_path, monkeypatch):
    def _fake_meeko(pdb_path, out_path):
        text = Path(pdb_path).read_text(encoding="utf-8")
        assert "AXI" not in text
        assert "HOH" not in text
        assert "ALA" in text
        out_path.write_text("REMARK  receptor\n", encoding="utf-8")
        return None, []

    monkeypatch.setattr(
        "molmanager.workers.pdbqt_generator._write_receptor_pdbqt_file",
        _fake_meeko,
    )
    out = tmp_path / "rec_prepared.cif"
    out.write_text("data_placeholder\n", encoding="utf-8")
    result = write_smina_prepare_artifacts(
        holo_text=_HOLO_PDB,
        fmt="pdb",
        output_path=out,
        ligand_keys={("A", "2000", "")},
        padding=4.0,
    )
    assert result.receptor_pdbqt.endswith("_receptor.pdbqt")
    assert Path(result.receptor_pdbqt).is_file()
    lig_pdb = Path(result.ligand_pdb).read_text(encoding="utf-8")
    assert "AXI" in lig_pdb
    assert "HOH" not in lig_pdb
    assert "ALA" not in lig_pdb
    assert result.box is not None
    assert result.box.size_x == pytest.approx(0.763 + 8.0)
    box_txt = Path(result.box_path).read_text(encoding="utf-8")
    assert "center_x" in box_txt
    assert "size_z" in box_txt


_APO_PDB = """\
ATOM      1  N   ALA A   1      11.104   6.134  10.000  1.00  0.00           N
ATOM      2  CA  ALA A   1      12.260   6.859  10.000  1.00  0.00           C
ATOM      3  C   ALA A   1      13.498   6.000  10.000  1.00  0.00           C
ATOM      4  O   ALA A   1      13.400   4.780  10.000  1.00  0.00           O
ATOM      5  CB  ALA A   1      12.250   7.800   8.800  1.00  0.00           C
END
"""

_HOLO_CHAIN_B = """\
ATOM      1  N   ALA A   1      11.104   6.134  10.000  1.00  0.00           N
ATOM      2  CA  ALA A   1      12.260   6.859  10.000  1.00  0.00           C
ATOM      3  C   ALA A   1      13.498   6.000  10.000  1.00  0.00           C
ATOM      4  O   ALA A   1      13.400   4.780  10.000  1.00  0.00           O
ATOM      5  CB  ALA A   1      12.250   7.800   8.800  1.00  0.00           C
HETATM  100  O81 AXI B2000     -26.050  -1.540  -9.129  1.00 32.47           O
HETATM  101  C80 AXI B2000     -26.813  -2.112  -9.925  1.00 30.83           C
END
"""


def _stub_meeko(monkeypatch):
    def _fake_meeko(pdb_path, out_path):
        out_path.write_text("REMARK  receptor\n", encoding="utf-8")
        return None, []

    monkeypatch.setattr(
        "molmanager.workers.pdbqt_generator._write_receptor_pdbqt_file",
        _fake_meeko,
    )


def test_box_uses_original_keys_when_prepared_chain_changes(tmp_path, monkeypatch):
    _stub_meeko(monkeypatch)
    out = tmp_path / "rec_prepared.cif"
    out.write_text("data_placeholder\n", encoding="utf-8")
    result = write_smina_prepare_artifacts(
        holo_text=_HOLO_CHAIN_B,
        fmt="pdb",
        output_path=out,
        ligand_keys={("B", "2000", "")},
        box_ligand_keys={("A", "2000", "")},
        orig_box_ligand_keys={("A", "2000", "")},
        padding=4.0,
        source_text=_HOLO_PDB,
        source_fmt="pdb",
    )
    assert result.box is not None
    assert "No ligand atoms" not in result.warning
    lig_pdb = Path(result.ligand_pdb).read_text(encoding="utf-8")
    assert "AXI" in lig_pdb


def test_box_falls_back_to_loaded_structure_when_ligand_stripped(tmp_path, monkeypatch):
    _stub_meeko(monkeypatch)
    out = tmp_path / "rec_prepared.cif"
    out.write_text("data_placeholder\n", encoding="utf-8")
    result = write_smina_prepare_artifacts(
        holo_text=_APO_PDB,
        fmt="pdb",
        output_path=out,
        ligand_keys=set(),
        box_ligand_keys={("A", "2000", "")},
        orig_box_ligand_keys={("A", "2000", "")},
        padding=4.0,
        source_text=_HOLO_PDB,
        source_fmt="pdb",
    )
    assert result.box is not None
    assert result.box.size_x == pytest.approx(0.763 + 8.0)
    assert "AXI" in Path(result.ligand_pdb).read_text(encoding="utf-8")


def test_box_from_external_ligand_file(tmp_path, monkeypatch):
    _stub_meeko(monkeypatch)
    lig = tmp_path / "crystal_lig.pdb"
    lig.write_text(
        "HETATM  100  O81 AXI A2000     -26.050  -1.540  -9.129  1.00 32.47           O\n"
        "HETATM  101  C80 AXI A2000     -26.813  -2.112  -9.925  1.00 30.83           C\n"
        "END\n",
        encoding="utf-8",
    )
    out = tmp_path / "rec_prepared.cif"
    out.write_text("data_placeholder\n", encoding="utf-8")
    result = write_smina_prepare_artifacts(
        holo_text=_APO_PDB,
        fmt="pdb",
        output_path=out,
        ligand_keys=set(),
        padding=4.0,
        box_ligand_path=str(lig),
    )
    assert result.box is not None
    assert result.box.size_x == pytest.approx(0.763 + 8.0)
    assert "AXI" in Path(result.ligand_pdb).read_text(encoding="utf-8")


def test_write_smina_artifacts_missing_gemmi_keeps_box(tmp_path, monkeypatch):
    def _boom(_pdb_path, _out_path):
        raise ModuleNotFoundError("No module named 'gemmi'", name="gemmi")

    monkeypatch.setattr(
        "molmanager.workers.pdbqt_generator._write_receptor_pdbqt_file",
        _boom,
    )
    out = tmp_path / "rec_prepared.cif"
    out.write_text("data_placeholder\n", encoding="utf-8")
    result = write_smina_prepare_artifacts(
        holo_text=_HOLO_PDB,
        fmt="pdb",
        output_path=out,
        ligand_keys={("A", "2000", "")},
        padding=4.0,
    )
    assert result.receptor_pdbqt == ""
    assert result.box is not None
    assert result.ligand_pdb
    assert result.can_open_smina()
    assert "pip install gemmi" in result.warning


def test_write_dock_file_artifacts_from_holo(tmp_path, monkeypatch):
    def _fake_write(_pdb_path, out_path):
        Path(out_path).write_text("REMARK  test\n", encoding="utf-8")
        return "", []

    monkeypatch.setattr(
        "molmanager.workers.pdbqt_generator._write_receptor_pdbqt_file",
        _fake_write,
    )
    keys = ligand_keys_from_structure(_HOLO_PDB, "pdb")
    assert ("A", "2000", "") in keys
    out = tmp_path / "holo_smina.cif"
    result = write_dock_file_artifacts(
        text=_HOLO_PDB,
        fmt="pdb",
        output_path=out,
        box_ligand_keys={("A", "2000", "")},
        padding=4.0,
    )
    assert result.receptor_pdbqt
    assert Path(result.receptor_pdbqt).is_file()
    assert result.box is not None
    assert result.ligand_pdb
    assert result.can_open_smina()
