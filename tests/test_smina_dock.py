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

"""Smina CLI dialog: autobox vs manual search box."""

from __future__ import annotations

import pytest

pytest.importorskip("PyQt5.QtWidgets")

from molmanager.ui.smina_dock import SminaDockDialog


def _filled_dialog(qapp):  # noqa: ARG001
    dlg = SminaDockDialog(None)
    dlg.edit_receptor.setText("rec.pdbqt")
    dlg.edit_ligand.setText("lig.pdbqt")
    dlg.edit_out.setText("out.pdbqt")
    return dlg


def test_smina_argv_manual_box(qapp):  # noqa: ARG001
    dlg = _filled_dialog(qapp)
    dlg.autobox_cb.setChecked(False)
    dlg.spin_cx.setValue(1.5)
    dlg.spin_sx.setValue(22.0)
    argv = dlg._build_argv()
    assert "--autobox_ligand" not in argv
    assert argv[argv.index("--center_x") + 1] == "1.500"
    assert argv[argv.index("--size_x") + 1] == "22.00"
    dlg.close()


def test_smina_autobox_uses_docking_ligand(qapp):  # noqa: ARG001
    dlg = _filled_dialog(qapp)
    dlg.autobox_cb.setChecked(True)
    dlg.spin_autobox_add.setValue(5.5)
    assert not dlg.spin_cx.isEnabled()
    argv = dlg._build_argv()
    assert "--center_x" not in argv
    assert argv[argv.index("--autobox_ligand") + 1] == "lig.pdbqt"
    assert argv[argv.index("--autobox_add") + 1] == "5.50"
    dlg.close()


def test_smina_autobox_optional_box_ligand(qapp):  # noqa: ARG001
    dlg = _filled_dialog(qapp)
    dlg.autobox_cb.setChecked(True)
    assert dlg.edit_autobox_ligand.isEnabled()
    assert dlg.btn_autobox_ligand.isEnabled()
    dlg.edit_autobox_ligand.setText("crystal.pdb")
    argv = dlg._build_argv()
    assert argv[argv.index("--autobox_ligand") + 1] == "crystal.pdb"
    assert argv[argv.index("--ligand") + 1] == "lig.pdbqt"
    dlg.edit_autobox_ligand.setText("crystal.pdbqt")
    argv = dlg._build_argv()
    assert argv[argv.index("--autobox_ligand") + 1] == "crystal.pdbqt"
    dlg.autobox_cb.setChecked(False)
    assert not dlg.edit_autobox_ligand.isEnabled()
    assert not dlg.btn_autobox_ligand.isEnabled()
    dlg.close()


def test_smina_dialog_defaults_to_resolved_executable(qapp):  # noqa: ARG001
    from molmanager.bundled_paths import default_external_executable

    dlg = SminaDockDialog(None)
    assert dlg.edit_exe.text() == default_external_executable("smina")
    assert not hasattr(dlg, "progress")
    assert dlg.save_sdf_cb.isChecked()
    assert not dlg.minimize_poses_cb.isChecked()
    assert dlg.edit_out.placeholderText() == "out.sdf"
    dlg.close()


def test_smina_argv_uses_sdf_out_when_save_sdf(qapp):  # noqa: ARG001
    dlg = _filled_dialog(qapp)
    argv = dlg._build_argv()
    assert argv[argv.index("--out") + 1] == "out.sdf"
    dlg.save_sdf_cb.setChecked(False)
    argv = dlg._build_argv()
    assert argv[argv.index("--out") + 1] == "out.pdbqt"
    dlg.close()


def test_smina_writes_sidecar_sdf_on_success(qapp, tmp_path):  # noqa: ARG001
    from pathlib import Path

    sample = Path(__file__).resolve().parents[1] / "samples" / "4AGC_liigand.pdbqt"
    pdbqt = tmp_path / "out.pdbqt"
    pdbqt.write_bytes(sample.read_bytes())
    dlg = SminaDockDialog(None)
    dlg.save_sdf_cb.setChecked(False)
    dlg.edit_out.setText(str(pdbqt))
    dlg.save_sdf_cb.setChecked(True)
    dlg._write_final_sdf(str(pdbqt))
    sdf = tmp_path / "out.sdf"
    assert sdf.is_file()
    dlg.close()


def test_smina_prepares_ligand_batch_from_concatenated_pdbqt(qapp, tmp_path):  # noqa: ARG001
    from pathlib import Path

    from rdkit import Chem

    sample = Path(__file__).resolve().parents[1] / "samples" / "axitininb_conformers.pdbqt"
    dlg = SminaDockDialog(None)
    dlg.edit_receptor.setText("rec.pdbqt")
    dlg.edit_ligand.setText(str(sample))
    out = str(tmp_path / "out.sdf")
    dlg.edit_out.setText(out)
    paths = dlg._prepare_smina_ligands(str(sample))
    assert len(paths) == 1
    assert paths[0].suffix.lower() == ".sdf"
    mols = [m for m in Chem.SDMolSupplier(str(paths[0]), removeHs=False) if m is not None]
    assert len(mols) > 1
    assert any(
        b.GetBondType() == Chem.BondType.DOUBLE or b.GetIsAromatic() for b in mols[0].GetBonds()
    )
    argv = dlg._build_argv(ligand=str(paths[0]), out=out)
    assert argv.count("--ligand") == 1
    assert argv[argv.index("--ligand") + 1] == str(paths[0])
    assert argv[argv.index("--out") + 1] == out
    dlg._clear_batch()
    dlg.close()


def test_smina_sdf_ligand_skips_pdbqt_split(qapp, tmp_path):  # noqa: ARG001
    from pathlib import Path

    from rdkit import Chem

    sample = Path(__file__).resolve().parents[1] / "samples" / "axitininb_conformers.sdf"
    dlg = _filled_dialog(qapp)
    dlg.edit_ligand.setText(str(sample))
    n = dlg._prepare_ligand_batch(str(sample))
    assert n == 1
    assert dlg._batch_ligands == []
    argv = dlg._build_argv(ligand=str(sample), out=str(tmp_path / "out.sdf"))
    assert argv[argv.index("--ligand") + 1] == str(sample)
    tmpl = dlg._ligand_template_mol()
    assert tmpl is not None
    assert any(
        b.GetBondType() == Chem.BondType.DOUBLE or b.GetIsAromatic() for b in tmpl.GetBonds()
    )
    dlg.close()


def test_smina_launch_argv_uses_config_for_multi_ligand(qapp, tmp_path):  # noqa: ARG001
    from pathlib import Path

    dlg = _filled_dialog(qapp)
    argv = dlg._build_argv(ligand=["a.pdbqt", "b.pdbqt"], out=str(tmp_path / "out.pdbqt"))
    launch = dlg._launch_argv(argv)
    assert launch[:1] == ["--config"]
    cfg = Path(launch[1])
    assert cfg.is_file()
    assert cfg.read_text(encoding="utf-8").count("ligand = ") == 2
    dlg._clear_batch()
    dlg.close()


def test_smina_ligand_cli_args_repeats_flag():
    from molmanager.ui.smina_dock import _ligand_cli_args

    args, first = _ligand_cli_args(["a.pdbqt", "b.pdbqt"])
    assert args == ["--ligand", "a.pdbqt", "--ligand", "b.pdbqt"]
    assert first == "a.pdbqt"
    one, only = _ligand_cli_args("lig.pdbqt")
    assert one == ["--ligand", "lig.pdbqt"]
    assert only == "lig.pdbqt"


def test_write_smina_config_repeats_ligand(tmp_path):
    from molmanager.ui.smina_dock import _write_smina_config

    dest = tmp_path / "smina.conf"
    _write_smina_config(
        [
            "--receptor",
            "rec.pdbqt",
            "--ligand",
            "a.pdbqt",
            "--ligand",
            "b.pdbqt",
            "--out",
            "out.pdbqt",
            "--minimize",
            "--center_x",
            "-1.5",
        ],
        dest,
    )
    text = dest.read_text(encoding="utf-8")
    assert text.count("ligand = ") == 2
    assert "minimize = true" in text
    assert "center_x = -1.5" in text


def test_smina_skips_sidecar_sdf_when_unchecked(qapp, tmp_path):  # noqa: ARG001
    from pathlib import Path

    from PyQt5.QtCore import QProcess

    sample = Path(__file__).resolve().parents[1] / "samples" / "4AGC_liigand.pdbqt"
    pdbqt = tmp_path / "out.pdbqt"
    pdbqt.write_bytes(sample.read_bytes())
    dlg = SminaDockDialog(None)
    dlg.save_sdf_cb.setChecked(False)
    dlg.edit_out.setText(str(pdbqt))
    dlg._on_proc_finished(0, QProcess.NormalExit)
    assert not (tmp_path / "out.sdf").exists()
    dlg.close()


def test_smina_minimize_argv_omits_search_box(qapp):  # noqa: ARG001
    dlg = _filled_dialog(qapp)
    argv = dlg._build_minimize_argv("pose.pdbqt", "min.pdbqt")
    assert "--minimize" in argv
    assert "--num_modes" not in argv
    assert "--exhaustiveness" not in argv
    assert argv[argv.index("--ligand") + 1] == "pose.pdbqt"
    assert "--minimize" not in dlg._build_argv()
    multi = dlg._build_minimize_argv(["a.pdbqt", "b.pdbqt"], "min.pdbqt")
    assert multi.count("--ligand") == 2
    assert multi[multi.index("--ligand") + 1] == "a.pdbqt"
    dlg.close()


def test_smina_present_dock_results_opens_table(qapp, tmp_path):  # noqa: ARG001
    from rdkit import Chem
    from rdkit.Chem import SDWriter

    sdf = tmp_path / "docked.sdf"
    mol = Chem.MolFromSmiles("CCO")
    assert mol is not None
    mol.SetProp("_Name", "lig_1")
    mol.SetProp("minimizedAffinity", "-9.100")
    writer = SDWriter(str(sdf))
    writer.write(mol)
    writer.close()
    opened: list = []

    class _Host:
        def open_dock_results_window(self, mols, *, title="", receptor_path=None):
            opened.append((list(mols), title, receptor_path))
            return None

    dlg = SminaDockDialog(None)
    dlg._main_window = _Host()
    dlg._stdout_buf = (
        "mode |   affinity | dist from best mode\n"
        "     | (kcal/mol) | rmsd l.b.| rmsd u.b.\n"
        "-----+------------+----------+----------\n"
        "   1         -9.10      0.000      0.000\n"
    )
    rec = tmp_path / "rec.pdbqt"
    rec.write_text("ATOM      1  CA  ALA A   1       0.000   0.000   0.000\n", encoding="utf-8")
    dlg.edit_receptor.setText(str(rec))
    dlg._present_dock_results(str(sdf))
    assert opened
    mols, title, receptor_path = opened[0]
    assert "docked.sdf" in title
    assert receptor_path == str(rec)
    assert mols[0].GetProp("minimizedAffinity") == "-9.100"
    assert mols[0].GetProp("mode") == "1"
    assert mols[0].GetProp("rmsd_lb") == "0.000"
    dlg.close()


def test_apply_prepare_result_fills_numeric_box(qapp, tmp_path):  # noqa: ARG001
    from molmanager.docking_box import DockingBox
    from molmanager.workers.protein_prepare_smina import ProteinPrepareResult

    rec = tmp_path / "rec_receptor.pdbqt"
    lig = tmp_path / "rec_ligand.sdf"
    lig_pdb = tmp_path / "rec_ligand.pdb"
    rec.write_text("ATOM\n", encoding="utf-8")
    lig.write_text("lig\n", encoding="utf-8")
    lig_pdb.write_text("HETATM\n", encoding="utf-8")
    box = DockingBox(1.5, -2.0, 3.25, 22.0, 18.0, 20.0, padding=4.0)
    result = ProteinPrepareResult(
        output_path=str(tmp_path / "rec.cif"),
        receptor_pdbqt=str(rec),
        ligand_sdf=str(lig),
        ligand_pdb=str(lig_pdb),
        box_path=str(tmp_path / "rec_box.txt"),
        box=box,
    )
    dlg = SminaDockDialog(None)
    dlg.apply_prepare_result(result)
    assert dlg.edit_receptor.text() == str(rec)
    assert dlg.edit_ligand.text() == str(lig)
    assert dlg.edit_autobox_ligand.text() == str(lig_pdb)
    assert dlg.autobox_cb.isChecked() is False
    assert dlg.spin_cx.value() == 1.5
    assert dlg.spin_sx.value() == 22.0
    assert dlg.edit_out.text().endswith("rec_ligand_docked.sdf")
    argv = dlg._build_argv()
    assert argv[argv.index("--center_x") + 1] == "1.500"
    assert argv[argv.index("--size_x") + 1] == "22.00"
    dlg.close()
