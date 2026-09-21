# This file is part of mctoolkit.
# Copyright (C) 2026 Hunter Picard
#
# mctoolkit is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# mctoolkit is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with mctoolkit. If not, see <https://www.gnu.org/licenses/>.

"""Langevin MD helpers and Protein Viewer dialog wiring."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from qt_helpers import qt_submenu

from mctoolkit.md.implicit_md import (
    ImplicitMDConfig,
    ImplicitMDResult,
    _steps_for_ps,
    production_steps_done,
    read_checkpoint_meta,
    slice_solute_positions,
    write_checkpoint_meta,
)
from mctoolkit.workers.protein_md import ProteinMDRequest, run_protein_md
from mctoolkit.workers.protein_prepare_minimize import _is_explicit_solvent

_HOLO_PDB = """\
ATOM      1  N   ALA A   1      11.104   6.134  10.000  1.00  0.00           N
ATOM      2  CA  ALA A   1      12.260   6.859  10.000  1.00  0.00           C
HETATM  100  O81 AXI A2000     -26.050  -1.540  -9.129  1.00 32.47           O
END
"""


def test_steps_for_ps() -> None:
    assert _steps_for_ps(1.0, 2.0) == 500
    assert _steps_for_ps(0.0, 2.0) == 0
    with pytest.raises(RuntimeError):
        _steps_for_ps(1.0, 0.0)


def test_slice_solute_and_checkpoint_meta(tmp_path: Path) -> None:
    assert slice_solute_positions([1, 2, 3, 4], 0) == [1, 2, 3, 4]
    assert slice_solute_positions([1, 2, 3, 4], 4) == [1, 2, 3, 4]
    assert slice_solute_positions([1, 2, 3, 4], 2) == [1, 2]
    with pytest.raises(RuntimeError, match="exceeds"):
        slice_solute_positions([1, 2], 3)
    assert production_steps_done(1500, 500) == 1000
    assert production_steps_done(100, 500) == 0
    chk = tmp_path / "run.chk"
    write_checkpoint_meta(
        chk, n_eq_steps=500, n_prod_target=5000, timestep_fs=2.0, current_step=1500
    )
    meta = read_checkpoint_meta(chk)
    assert meta["n_eq_steps"] == 500
    assert meta["current_step"] == 1500
    assert _is_explicit_solvent("tip3p")
    assert _is_explicit_solvent("PME")
    assert not _is_explicit_solvent("gbn2")


@patch("mctoolkit.workers.protein_md.run_implicit_md")
@patch("mctoolkit.workers.protein_md.add_position_restraints")
@patch("mctoolkit.workers.protein_md.build_gaff_split_prmtops")
@patch("mctoolkit.workers.protein_md._amber_holo_system")
@patch("mctoolkit.workers.protein_prepare_ligand.prepare_ligands_for_gaff")
@patch("mctoolkit.workers.protein_md._write_structure_overlay")
@patch("mctoolkit.workers.protein_prepare_io._write_openmm_structure")
def test_run_protein_md_writes_last_frame(
    mock_write_omm,
    mock_overlay,
    mock_ligands,
    mock_amber,
    mock_split,
    mock_restrain,
    mock_md,
    tmp_path: Path,
) -> None:
    in_path = tmp_path / "holo.pdb"
    in_path.write_text(_HOLO_PDB, encoding="utf-8")
    mock_ligands.side_effect = lambda text, _keys, **_k: ([object()], text)
    mock_split.return_value = MagicMock(
        complex_prmtop=tmp_path / "c.prmtop",
        complex_inpcrd=tmp_path / "c.inpcrd",
        receptor_prmtop=tmp_path / "r.prmtop",
        receptor_inpcrd=tmp_path / "r.inpcrd",
        ligand_prmtop=tmp_path / "l.prmtop",
        ligand_inpcrd=tmp_path / "l.inpcrd",
        charge_tag="AM1-BCC",
    )
    topology = MagicMock()
    topology.getNumAtoms.return_value = 3
    mock_amber.return_value = (object(), topology, [0], "GBN2")
    mock_md.return_value = ImplicitMDResult(
        positions=[1],
        n_eq_steps=10,
        n_prod_steps=50,
        dcd_path=str(tmp_path / "out.dcd"),
        mmgbsa=[],
    )
    out = tmp_path / "out.cif"
    mock_overlay.side_effect = lambda *_a, **_k: out
    mock_write_omm.side_effect = lambda *_a, **_k: None
    (tmp_path / "dummy").mkdir()
    req = ProteinMDRequest(
        input_path=str(in_path),
        output_path=str(out),
        ligand_smiles="C",
        score_mmgbsa=False,
        production_ps=0.1,
        equilibration_ps=0.0,
        minimize_iterations=0,
    )

    # Overlay reads last-frame text; write a stub before overlay is called.
    def _write(top, pos, path, **_k):
        Path(path).write_text("FRAME", encoding="utf-8")

    mock_write_omm.side_effect = _write
    result = run_protein_md(req)
    mock_md.assert_called_once()
    cfg: ImplicitMDConfig = mock_md.call_args.kwargs["config"]
    assert cfg.production_ps == pytest.approx(0.1)
    assert cfg.solute_atoms == 0
    assert result.n_snapshots == 0
    mock_restrain.assert_called_once()
    assert Path(result.topology_path).is_file()
    sidecar = json.loads(Path(result.sidecar_path).read_text(encoding="utf-8"))
    assert sidecar["topology"] == result.topology_path
    assert sidecar["dcd"] == result.dcd_path
    assert sidecar["solute_atoms"] == 3
    assert sidecar["wrap_dcd"] is False


@patch("mctoolkit.workers.protein_md.run_implicit_md")
@patch("mctoolkit.workers.protein_md.add_position_restraints")
@patch("mctoolkit.workers.protein_md.build_gaff_split_prmtops")
@patch("mctoolkit.workers.protein_md._amber_explicit_system")
@patch("mctoolkit.workers.protein_md._amber_topology_positions")
@patch("mctoolkit.workers.protein_md.align_solute_com", side_effect=lambda pos, _ref: pos)
@patch("mctoolkit.workers.protein_prepare_ligand.prepare_ligands_for_gaff")
@patch("mctoolkit.workers.protein_md._write_structure_overlay")
@patch("mctoolkit.workers.protein_prepare_io._write_openmm_structure")
def test_run_protein_md_explicit_uses_solvated_system(
    mock_write_omm,
    mock_overlay,
    mock_ligands,
    mock_align,
    mock_dry,
    mock_explicit,
    mock_split,
    mock_restrain,
    mock_md,
    tmp_path: Path,
) -> None:
    in_path = tmp_path / "holo.pdb"
    in_path.write_text(_HOLO_PDB, encoding="utf-8")
    mock_ligands.side_effect = lambda text, _keys, **_k: ([object()], text)
    mock_split.return_value = MagicMock(
        complex_prmtop=tmp_path / "c.prmtop",
        complex_inpcrd=tmp_path / "c.inpcrd",
        receptor_prmtop=tmp_path / "r.prmtop",
        receptor_inpcrd=tmp_path / "r.inpcrd",
        ligand_prmtop=tmp_path / "l.prmtop",
        ligand_inpcrd=tmp_path / "l.inpcrd",
        solvated_prmtop=tmp_path / "s.prmtop",
        solvated_inpcrd=tmp_path / "s.inpcrd",
        charge_tag="AM1-BCC",
    )
    dry_top = MagicMock()
    dry_top.getNumAtoms.return_value = 12
    mock_dry.return_value = (dry_top, [0] * 12)
    solv_top = MagicMock()
    solv_top.getNumAtoms.return_value = 400
    mock_explicit.return_value = (object(), solv_top, [0] * 400, "TIP3P PME NPT 1.00 bar")
    mock_md.return_value = ImplicitMDResult(
        positions=[1] * 12,
        n_eq_steps=10,
        n_prod_steps=50,
        dcd_path=str(tmp_path / "out.dcd"),
        mmgbsa=[],
    )
    out = tmp_path / "out.cif"
    mock_overlay.side_effect = lambda *_a, **_k: out

    def _write(top, pos, path, **_k):
        Path(path).write_text("FRAME", encoding="utf-8")

    mock_write_omm.side_effect = _write
    req = ProteinMDRequest(
        input_path=str(in_path),
        output_path=str(out),
        ligand_smiles="C",
        solvent="tip3p",
        score_mmgbsa=False,
        production_ps=0.1,
        equilibration_ps=0.0,
        minimize_iterations=0,
        box_padding_a=10.0,
        checkpoint_path=str(tmp_path / "run.chk"),
        resume=True,
    )
    result = run_protein_md(req)
    mock_explicit.assert_called_once()
    mock_md.assert_called_once()
    cfg: ImplicitMDConfig = mock_md.call_args.kwargs["config"]
    assert cfg.solute_atoms == 12
    assert cfg.wrap_dcd is True
    assert cfg.resume is True
    assert cfg.checkpoint_path.endswith("run.chk")
    kwargs = mock_split.call_args.kwargs
    assert kwargs["solvate_padding_a"] == pytest.approx(10.0)
    assert kwargs["ion_conc_m"] == pytest.approx(0.15)
    mock_align.assert_called_once()
    assert result.n_snapshots == 0
    mock_restrain.assert_called_once()
    sidecar = json.loads(Path(result.sidecar_path).read_text(encoding="utf-8"))
    assert sidecar["solute_atoms"] == 12
    assert sidecar["wrap_dcd"] is True
    assert Path(result.topology_path).is_file()


def test_md_dialog_defaults_and_help(qapp, tmp_path):  # noqa: ARG001
    from PySide6.QtWidgets import QMenuBar, QTextEdit

    from mctoolkit.ui.dialogs.protein_md import ProteinMDDialog
    from mctoolkit.ui.protein_viewer import ProteinViewerDialog
    from mctoolkit.ui.user_guides import guide_html

    html = guide_html("tools_md")
    assert "Topic unavailable" not in html
    assert "TIP3P" in html

    dlg = ProteinViewerDialog()
    mb = dlg.findChild(QMenuBar)
    tools_menu = qt_submenu(mb, "Tools")
    sim_menu = qt_submenu(tools_menu, "Simulate")
    labels = [a.text().replace("&", "") for a in sim_menu.actions()]
    assert any("Dynamics" in label for label in labels)
    assert any("Analyze Trajectory" in label for label in labels)

    path = tmp_path / "holo.pdb"
    path.write_text(_HOLO_PDB, encoding="utf-8")
    dlg.load_structure_path(path)
    dlg.open_md_dialog()
    md = dlg._md_dialog
    assert isinstance(md, ProteinMDDialog)
    assert not md.findChildren(QTextEdit)
    assert md.combo_solvent.currentData() == "gbn2"
    assert not md.spin_padding.isEnabled()
    assert md.chk_mmgbsa.isChecked()
    assert md.spin_prod.value() == pytest.approx(100.0)
    assert md.edit_out.text().endswith("holo_md.cif")
    assert md.edit_checkpoint.text().endswith("holo_md.chk")
    tip3p = md.combo_solvent.findData("tip3p")
    assert tip3p >= 0
    md.combo_solvent.setCurrentIndex(tip3p)
    assert md.spin_padding.isEnabled()
    dlg.close()
