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

"""MD trajectory analysis: RMSD/RMSF engine, sidecar, and Analyze dialog."""

from __future__ import annotations

import json
import struct
from pathlib import Path

import numpy as np
import pytest
from qt_helpers import qt_submenu

from mctoolkit.md.analysis import (
    TrajectoryAtom,
    analyze_trajectory,
    analyze_xyz,
    extract_frame_pdb,
    parse_pdb_atoms,
    read_dcd_xyz,
    read_run_sidecar,
    write_analysis_csv,
    write_run_sidecar,
)
from mctoolkit.workers.protein_md import ProteinMDJobResult


def _atom(index: int, name: str, resn: str, resi: str, element: str) -> TrajectoryAtom:
    return TrajectoryAtom(
        index=index, name=name, resn=resn, chain="A", resi=resi, icode="", element=element
    )


def _write_dcd(path: Path, xyz: np.ndarray) -> None:
    n_frames, n_atoms, _ = xyz.shape
    header = bytearray(276)
    struct.pack_into("<i", header, 0, 84)
    header[4:8] = b"CORD"
    struct.pack_into("<i", header, 268, n_atoms)
    chunks = [bytes(header)]
    rec_n = 4 * n_atoms
    for frame in xyz:
        for axis in range(3):
            coords = np.asarray(frame[:, axis], dtype="<f4")
            chunks.append(struct.pack("<i", rec_n) + coords.tobytes() + struct.pack("<i", rec_n))
    path.write_bytes(b"".join(chunks))


def test_analyze_xyz_identity_and_ligand_shift() -> None:
    atoms = [
        _atom(0, "CA", "ALA", "1", "C"),
        _atom(1, "CA", "ALA", "2", "C"),
        _atom(2, "C1", "LIG", "10", "C"),
        _atom(3, "CA", "ALA", "99", "C"),
    ]
    frame0 = np.array([[0.0, 0.0, 0.0], [3.0, 0.0, 0.0], [1.0, 2.0, 0.0], [8.0, 8.0, 8.0]])
    xyz = np.stack([frame0, frame0.copy(), frame0.copy()], axis=0)
    xyz[2, 2, 0] += 2.0
    xyz[2, 3, :] += 5.0
    result = analyze_xyz(xyz, atoms, solute_atoms=3)
    assert result.n_frames == 3
    assert result.n_solute == 3
    assert result.protein_ca_rmsd[0] == pytest.approx(0.0)
    assert result.protein_ca_rmsd[1] == pytest.approx(0.0)
    assert result.protein_ca_rmsd[2] == pytest.approx(0.0)
    assert result.ligand_rmsd[0] == pytest.approx(0.0)
    assert result.ligand_rmsd[2] == pytest.approx(2.0)
    assert result.ligand_com_drift[2] == pytest.approx(2.0)
    assert all(row.resi != "99" for row in result.rmsf)
    assert all(row.rmsf == pytest.approx(0.0) for row in result.rmsf)


def test_analyze_xyz_joins_energy_and_dg() -> None:
    atoms = [_atom(0, "CA", "ALA", "1", "C"), _atom(1, "C1", "LIG", "2", "C")]
    xyz = np.zeros((2, 2, 3))
    times = np.array([1.0, 2.0])
    result = analyze_xyz(
        xyz,
        atoms,
        time_ps=times,
        energy_t=np.array([2.0]),
        energy_v=np.array([-10.0]),
        dg_t=np.array([1.5]),
        dg_v=np.array([-3.0]),
    )
    assert result.e_pot[1] == pytest.approx(-10.0)
    assert result.dg[0] == pytest.approx(-3.0)


def test_dcd_sidecar_and_csv_roundtrip(tmp_path: Path) -> None:
    atoms_pdb = (
        "ATOM      1  CA  ALA A   1       0.000   0.000   0.000  1.00  0.00           C\n"
        "HETATM    2  C1  LIG A  10       1.000   2.000   0.000  1.00  0.00           C\n"
        "HETATM    3  O   HOH A  99      10.000  10.000  10.000  1.00  0.00           O\n"
        "END\n"
    )
    top = tmp_path / "run_top.pdb"
    top.write_text(atoms_pdb, encoding="utf-8")
    xyz = np.array(
        [
            [[0.0, 0.0, 0.0], [1.0, 2.0, 0.0], [10.0, 10.0, 10.0]],
            [[0.0, 0.0, 0.0], [1.0, 2.0, 0.0], [10.0, 10.0, 10.0]],
        ]
    )
    dcd = tmp_path / "run.dcd"
    _write_dcd(dcd, xyz)
    got = read_dcd_xyz(dcd)
    assert got.shape == (2, 3, 3)
    np.testing.assert_allclose(got[0], xyz[0], atol=1e-4)
    energy = tmp_path / "run_energy.csv"
    energy.write_text("time_ps,E_pot_kcal\n2.0,-5.5\n", encoding="utf-8")
    mmgbsa = tmp_path / "run_mmgbsa.csv"
    mmgbsa.write_text("time_ps,dG\n2.0,-1.25\n", encoding="utf-8")
    sidecar = write_run_sidecar(
        dcd,
        topology=str(top),
        energy_csv=str(energy),
        mmgbsa_csv=str(mmgbsa),
        timestep_fs=2.0,
        dcd_interval_steps=500,
        solute_atoms=2,
        ligand_keys=(("A", "10", ""),),
    )
    meta = read_run_sidecar(dcd)
    assert meta["topology"] == str(top)
    assert meta["solute_atoms"] == 2
    assert sidecar.name.endswith(".dcd.json")
    result = analyze_trajectory(dcd_path=str(dcd), topology_path="", sidecar_path=str(sidecar))
    assert result.n_solute == 2
    assert result.n_frames == 2
    assert result.protein_ca_rmsd[0] == pytest.approx(0.0)
    assert result.e_pot[-1] == pytest.approx(-5.5)
    assert result.dg[-1] == pytest.approx(-1.25)
    csv_path = tmp_path / "run_analysis.csv"
    write_analysis_csv(csv_path, result)
    text = csv_path.read_text(encoding="utf-8")
    assert "protein_ca_rmsd" in text
    frame_pdb = extract_frame_pdb(
        dcd_path=str(dcd),
        topology_path=str(top),
        frame=0,
        dest=tmp_path / "frame0.pdb",
        sidecar_path=str(sidecar),
    )
    parsed = parse_pdb_atoms(frame_pdb.read_text(encoding="utf-8"))
    assert len(parsed) == 2
    assert parsed[1].resn == "LIG"


def test_md_analysis_dialog_menu_help_and_prefill(qapp, tmp_path):  # noqa: ARG001
    from PySide6.QtWidgets import QLabel, QMenuBar

    from mctoolkit.ui.dialogs.protein_md import ProteinMDDialog
    from mctoolkit.ui.dialogs.protein_md_analysis import ProteinMDAnalysisDialog
    from mctoolkit.ui.protein_viewer import ProteinViewerDialog
    from mctoolkit.ui.user_guides import guide_html

    html = guide_html("tools_md_analysis")
    assert "Topic unavailable" not in html
    assert "not a DCD player" in html
    assert "Kabsch" in html or "Cα" in html or "CA" in html

    dlg = ProteinViewerDialog()
    mb = dlg.findChild(QMenuBar)
    tools_menu = qt_submenu(mb, "Tools")
    sim_menu = qt_submenu(tools_menu, "Simulate")
    labels = [a.text().replace("&", "") for a in sim_menu.actions()]
    assert any("Analyze Trajectory" in label for label in labels)

    dcd = tmp_path / "holo_md.dcd"
    dcd.write_bytes(b"")
    top = tmp_path / "holo_md_top.pdb"
    top.write_text(
        "ATOM      1  CA  ALA A   1       0.000   0.000   0.000  1.00  0.00           C\n"
    )
    energy = tmp_path / "holo_md_energy.csv"
    energy.write_text("time_ps,E_pot_kcal\n1.0,0.0\n", encoding="utf-8")
    sidecar = tmp_path / "holo_md.dcd.json"
    sidecar.write_text(
        json.dumps(
            {
                "dcd": str(dcd),
                "topology": str(top),
                "energy_csv": str(energy),
                "mmgbsa_csv": "",
            }
        ),
        encoding="utf-8",
    )
    fake = ProteinMDJobResult(
        structure_path="",
        dcd_path=str(dcd),
        topology_path=str(top),
        energy_csv_path=str(energy),
        sidecar_path=str(sidecar),
        csv_path="",
    )
    dlg.open_md_dialog()
    md = dlg._md_dialog
    assert isinstance(md, ProteinMDDialog)
    assert not md.btn_analyze.isEnabled()
    md._on_finished(fake)
    assert md.btn_analyze.isEnabled()
    md._on_analyze()
    analysis = dlg._md_analysis_dialog
    assert isinstance(analysis, ProteinMDAnalysisDialog)
    assert analysis.edit_dcd.text() == str(dcd)
    assert analysis.edit_topology.text() == str(top)
    assert analysis.edit_energy.text() == str(energy)
    assert analysis.edit_sidecar.text() == str(sidecar)
    footer = " ".join(lbl.text() for lbl in analysis.findChildren(QLabel))
    assert "Kabsch" in footer
    assert "DCD player" in footer
    analysis.close()
    dlg.close()
