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
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with MolManager. If not, see <https://www.gnu.org/licenses/>.

"""Protein Viewer Minimize dialog and complex-minimization runtime."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from molmanager.workers.protein_complex_minimize import (
    ProteinMinimizeRequest,
    minimize_protein_complex,
)

_ALA_PDB = """\
ATOM      1  N   ALA A   1      11.104   6.134  10.000  1.00  0.00           N
ATOM      2  CA  ALA A   1      12.260   6.859  10.000  1.00  0.00           C
ATOM      3  C   ALA A   1      13.498   6.000  10.000  1.00  0.00           C
ATOM      4  O   ALA A   1      13.400   4.780  10.000  1.00  0.00           O
ATOM      5  CB  ALA A   1      12.250   7.800   8.800  1.00  0.00           C
END
"""

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


def _min_req(tmp_path: Path, *, text: str = _HOLO_PDB, **kwargs) -> ProteinMinimizeRequest:
    in_path = tmp_path / "in.pdb"
    in_path.write_text(text, encoding="utf-8")
    defaults = dict(
        input_path=str(in_path),
        output_path=str(tmp_path / "out.cif"),
        ligand_ff="gaff2",
        ligand_smiles="C",
        keep_water=True,
    )
    defaults.update(kwargs)
    return ProteinMinimizeRequest(**defaults)


@patch("molmanager.workers.protein_prepare_ligand.prepare_ligands_for_gaff")
@patch("molmanager.workers.protein_complex_minimize._restrained_minimize_pdb")
@patch("molmanager.workers.protein_complex_minimize._write_prepared_output")
def test_minimize_gaff_keeps_ligand_in_openmm(mock_write, mock_min, mock_ligands, tmp_path):
    mock_ligands.side_effect = lambda text, _keys, **_k: ([object()], text)
    seen: dict = {}

    def _min(src, dest, **kwargs):
        seen["text"] = Path(src).read_text(encoding="utf-8")
        seen["kwargs"] = kwargs
        dest.write_text(seen["text"], encoding="utf-8")

    mock_min.side_effect = _min
    mock_write.side_effect = lambda _text, path, **_k: path.write_text("ok", encoding="utf-8")
    out = minimize_protein_complex(_min_req(tmp_path))
    mock_min.assert_called_once()
    assert "AXI" in seen["text"]
    assert "HOH" in seen["text"]
    assert seen["kwargs"]["ligand_ff"] == "gaff2"
    assert seen["kwargs"]["ligand_keys"]
    assert seen["kwargs"]["ligand_mols"]
    assert Path(out).is_file()


@patch("molmanager.workers.protein_complex_minimize._restrained_minimize_pdb")
@patch("molmanager.workers.protein_complex_minimize._write_prepared_output")
def test_minimize_protein_only_holds_ligand_out(mock_write, mock_min, tmp_path):
    seen: dict = {}

    def _min(src, dest, **kwargs):
        seen["text"] = Path(src).read_text(encoding="utf-8")
        seen["kwargs"] = kwargs
        dest.write_text(seen["text"], encoding="utf-8")

    mock_min.side_effect = _min
    mock_write.side_effect = lambda text, path, **_k: path.write_text(text, encoding="utf-8")
    minimize_protein_complex(_min_req(tmp_path, ligand_ff="none", ligand_smiles=""))
    mock_min.assert_called_once()
    assert "AXI" not in seen["text"]
    assert "HOH" in seen["text"]
    assert seen["kwargs"]["ligand_ff"] == "none"
    assert not seen["kwargs"]["ligand_keys"]
    assert seen["kwargs"]["ligand_mols"] is None


@patch("molmanager.workers.protein_complex_minimize._restrained_minimize_pdb")
@patch("molmanager.workers.protein_complex_minimize._write_prepared_output")
def test_minimize_drops_waters_when_unchecked(mock_write, mock_min, tmp_path):
    seen: dict = {}

    def _min(src, dest, **kwargs):
        seen["text"] = Path(src).read_text(encoding="utf-8")
        seen["kwargs"] = kwargs
        dest.write_text(seen["text"], encoding="utf-8")

    mock_min.side_effect = _min
    mock_write.side_effect = lambda text, path, **_k: path.write_text(text, encoding="utf-8")
    minimize_protein_complex(
        _min_req(tmp_path, ligand_ff="none", ligand_smiles="", keep_water=False)
    )
    assert "HOH" not in seen["text"]
    assert seen["kwargs"]["keep_water"] is False


@patch("molmanager.workers.protein_prepare_ligand.prepare_ligands_for_gaff")
def test_minimize_gaff_requires_ligand_chemistry(mock_ligands, tmp_path):
    mock_ligands.return_value = ([], _HOLO_PDB)
    req = _min_req(tmp_path, ligand_smiles="", ligand_ref_path="")
    with pytest.raises(RuntimeError, match="GAFF/GAFF2"):
        minimize_protein_complex(req)


def test_minimize_dialog_defaults_and_menu(qapp, tmp_path, monkeypatch):  # noqa: ARG001
    from PyQt5.QtWidgets import QMenuBar, QMessageBox

    from molmanager.ui.dialogs.protein_minimize import ProteinMinimizeDialog
    from molmanager.ui.protein_viewer import ProteinViewerDialog

    dlg = ProteinViewerDialog()
    mb = dlg.findChild(QMenuBar)
    labels = [a.text().replace("&", "") for a in mb.actions()]
    assert any(label.startswith("Minimize") for label in labels)

    shown: list[str] = []

    def _info(*_a, **_k):
        shown.append("info")
        return QMessageBox.Ok

    monkeypatch.setattr(QMessageBox, "information", _info)
    dlg.open_minimize_dialog()
    assert shown

    path = tmp_path / "holo.pdb"
    path.write_text(_HOLO_PDB, encoding="utf-8")
    dlg.load_structure_path(path)
    dlg.open_minimize_dialog()
    mini = dlg._minimize_dialog
    assert isinstance(mini, ProteinMinimizeDialog)
    assert mini.combo_ligand_ff.currentData() == "gaff2"
    assert mini.combo_protein_ff.currentData() == "amber14"
    assert mini.combo_solvent.currentData() == "gbn2"
    assert mini.combo_restraint.currentData() == "backbone_ligand"
    assert mini.chk_keep_water.isChecked()
    assert mini.combo_out_fmt.currentData() == "cif"
    assert mini.edit_out.text().endswith("holo_minimized.cif")
    assert mini.combo_ligand_ff.isEnabled()
    assert mini.edit_ligand_smiles.isEnabled()
    assert mini.combo_ligand.count() >= 2
    mini.combo_ligand_ff.setCurrentIndex(mini.combo_ligand_ff.findData("none"))
    assert not mini.edit_ligand_smiles.isEnabled()
    dlg.close()
