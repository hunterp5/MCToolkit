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
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with MCToolkit. If not, see <https://www.gnu.org/licenses/>.

"""Protein Viewer Minimize dialog and complex-minimization runtime."""

from __future__ import annotations

from qt_helpers import qt_submenu

from pathlib import Path
from unittest.mock import patch

import pytest

from mctoolkit.workers.protein_complex_minimize import (
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


@patch("mctoolkit.workers.protein_prepare_ligand.prepare_ligands_for_gaff")
@patch("mctoolkit.workers.protein_complex_minimize._restrained_minimize_pdb")
@patch("mctoolkit.workers.protein_complex_minimize._write_prepared_output")
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
    assert seen["kwargs"]["openmm_platform"] == "auto"
    assert Path(out).is_file()


@patch("mctoolkit.workers.protein_complex_minimize._restrained_minimize_pdb")
@patch("mctoolkit.workers.protein_complex_minimize._write_prepared_output")
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


@patch("mctoolkit.workers.protein_complex_minimize._restrained_minimize_pdb")
@patch("mctoolkit.workers.protein_complex_minimize._write_prepared_output")
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


@patch("mctoolkit.workers.protein_prepare_ligand.prepare_ligands_for_gaff")
def test_minimize_gaff_requires_ligand_chemistry(mock_ligands, tmp_path):
    mock_ligands.return_value = ([], _HOLO_PDB)
    req = _min_req(tmp_path, ligand_smiles="", ligand_ref_path="")
    with pytest.raises(RuntimeError, match="GAFF/GAFF2"):
        minimize_protein_complex(req)


def test_minimize_dialog_defaults_and_menu(qapp, tmp_path, monkeypatch):  # noqa: ARG001
    from PySide6.QtWidgets import QMenuBar, QMessageBox, QTextEdit

    from mctoolkit.ui.dialogs.protein_minimize import ProteinMinimizeDialog
    from mctoolkit.ui.protein_viewer import ProteinViewerDialog

    dlg = ProteinViewerDialog()
    mb = dlg.findChild(QMenuBar)
    tools_menu = qt_submenu(mb, "Tools")
    prepare_menu = qt_submenu(tools_menu, "Prepare")
    prepare_labels = [a.text().replace("&", "") for a in prepare_menu.actions()]
    assert any(label.startswith("Minimize") for label in prepare_labels)

    shown: list[str] = []

    def _info(*_a, **_k):
        shown.append("info")
        return QMessageBox.Ok

    monkeypatch.setattr(QMessageBox, "information", _info)
    dlg.open_minimize_dialog()
    assert not shown
    empty = dlg._minimize_dialog
    assert empty.radio_src_file.isChecked()

    path = tmp_path / "holo.pdb"
    path.write_text(_HOLO_PDB, encoding="utf-8")
    dlg.load_structure_path(path)
    dlg.open_minimize_dialog()
    mini = dlg._minimize_dialog
    assert isinstance(mini, ProteinMinimizeDialog)
    assert not mini.findChildren(QTextEdit)
    mini._append_log("Starting OpenMM restrained minimization")
    assert "Starting OpenMM restrained minimization" in dlg.log.toPlainText()
    assert mini.combo_ligand_ff.currentData() == "gaff2"
    assert mini.combo_protein_ff.currentData() == "amber14"
    assert mini.combo_solvent.currentData() == "gbn2"
    assert mini.combo_openmm_platform.currentData() == "auto"
    assert mini.radio_src_manager.isChecked()
    assert mini.combo_src_manager.count() == 1
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


def _d7d_h_bond_lengths(text: str) -> list[float]:
    from mctoolkit.protein.structure_atoms import parse_structure_atoms
    from mctoolkit.protein.structure_cif import parse_cif_chem_comp_bonds

    by_name = {}
    for atom in parse_structure_atoms(text, "cif"):
        if (atom.resn or "").upper() != "D7D":
            continue
        by_name[atom.name] = atom
    lengths = []
    for bond in parse_cif_chem_comp_bonds(text).get("D7D") or ():
        a = by_name.get(bond.atom_id_1)
        b = by_name.get(bond.atom_id_2)
        if a is None or b is None:
            continue
        if (a.elem or "").upper() not in {"H", "D", "T"} and (b.elem or "").upper() not in {
            "H",
            "D",
            "T",
        }:
            continue
        dx = a.x - b.x
        dy = a.y - b.y
        dz = a.z - b.z
        lengths.append((dx * dx + dy * dy + dz * dz) ** 0.5)
    return lengths


def test_rebuild_hydrogen_chem_bonds_fixes_6bbu_abrocitinib():
    from pathlib import Path

    from mctoolkit.protein.structure_cif import (
        cif_viewer_bond_tables,
        parse_cif_chem_comp_atoms,
        repair_cif_hydrogen_chem_bonds,
    )

    path = Path("samples/6bbu_fixed_protonated_minimized.cif")
    if not path.is_file():
        pytest.skip("samples/6bbu_fixed_protonated_minimized.cif is not present")
    text = path.read_text(encoding="utf-8")
    before = _d7d_h_bond_lengths(text)
    assert before
    assert max(before) > 1.5
    repaired = repair_cif_hydrogen_chem_bonds(text)
    after = _d7d_h_bond_lengths(repaired)
    assert after
    assert max(after) < 1.45
    h_ids = {
        atom.atom_id
        for atom in parse_cif_chem_comp_atoms(repaired).get("D7D") or ()
        if (atom.symbol or "").upper() in {"H", "D", "T"}
    }
    tables = cif_viewer_bond_tables(text)
    for a1, a2, _order in tables.get("D7D") or []:
        assert a1 not in h_ids
        assert a2 not in h_ids
