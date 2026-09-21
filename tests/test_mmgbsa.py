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

"""MM-GBSA term arithmetic, reports, and Protein Viewer dialog wiring."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from qt_helpers import qt_submenu

from mctoolkit.md.mmgbsa import (
    MMGBSAResult,
    MMGBSATerms,
    average_mmgbsa_results,
    delta_terms,
    force_kind,
    format_mmgbsa_report,
    write_mmgbsa_csv,
)
from mctoolkit.workers.protein_mmgbsa import ProteinMMGBSARequest, score_protein_mmgbsa
from mctoolkit.workers.protein_prepare_amber import leap_input

_HOLO_PDB = """\
ATOM      1  N   ALA A   1      11.104   6.134  10.000  1.00  0.00           N
ATOM      2  CA  ALA A   1      12.260   6.859  10.000  1.00  0.00           C
ATOM      3  C   ALA A   1      13.498   6.000  10.000  1.00  0.00           C
ATOM      4  O   ALA A   1      13.400   4.780  10.000  1.00  0.00           O
ATOM      5  CB  ALA A   1      12.250   7.800   8.800  1.00  0.00           C
HETATM  100  O81 AXI A2000     -26.050  -1.540  -9.129  1.00 32.47           O
HETATM  101  C80 AXI A2000     -26.813  -2.112  -9.925  1.00 30.83           C
END
"""


def test_delta_terms_are_complex_minus_parts() -> None:
    complex_e = MMGBSATerms(total=10.0, bonded=1.0, vdw=4.0, elec=3.0, gb=1.5, sa=0.5)
    receptor = MMGBSATerms(total=6.0, bonded=1.0, vdw=2.0, elec=2.0, gb=0.8, sa=0.2)
    ligand = MMGBSATerms(total=3.0, bonded=0.0, vdw=1.0, elec=1.0, gb=0.7, sa=0.3)
    delta = delta_terms(complex_e, receptor, ligand)
    assert delta.total == pytest.approx(1.0)
    assert delta.bonded == pytest.approx(0.0)
    assert delta.vdw == pytest.approx(1.0)
    assert delta.ggas == pytest.approx(1.0)
    assert delta.gsolv == pytest.approx(0.0)


def test_force_kind_classification() -> None:
    class HarmonicBondForce:
        pass

    class NonbondedForce:
        pass

    class CustomGBForce:
        pass

    class CustomGBSAForce:
        pass

    assert force_kind(HarmonicBondForce()) == "bonded"
    assert force_kind(NonbondedForce()) == "nonbonded"
    assert force_kind(CustomGBForce()) == "gb"
    assert force_kind(CustomGBSAForce()) == "sa"


def test_mmgbsa_report_states_no_entropy() -> None:
    result = MMGBSAResult(
        complex=MMGBSATerms(total=-20.0, vdw=-10.0, elec=-5.0, gb=-4.0, sa=-1.0),
        receptor=MMGBSATerms(total=-12.0, vdw=-6.0, elec=-3.0, gb=-2.5, sa=-0.5),
        ligand=MMGBSATerms(total=-5.0, vdw=-2.0, elec=-1.5, gb=-1.2, sa=-0.3),
        solvent="gbn2",
        salt_m=0.15,
        protein_ff="AMBER14",
        ligand_ff="GAFF2",
    )
    text = format_mmgbsa_report(result)
    assert "without entropy" in text
    assert "not an experimental binding free energy" in text
    assert "GBN2" in text
    assert "TOTAL" in text
    assert "DELTA" in text


def test_average_and_csv(tmp_path: Path) -> None:
    a = MMGBSAResult(
        complex=MMGBSATerms(total=10.0),
        receptor=MMGBSATerms(total=6.0),
        ligand=MMGBSATerms(total=3.0),
        frame=1,
        time_ps=10.0,
    )
    b = MMGBSAResult(
        complex=MMGBSATerms(total=12.0),
        receptor=MMGBSATerms(total=6.0),
        ligand=MMGBSATerms(total=3.0),
        frame=2,
        time_ps=20.0,
    )
    mean, std = average_mmgbsa_results([a, b])
    assert mean.total == pytest.approx(2.0)
    assert std.total == pytest.approx(2**0.5)
    csv_path = tmp_path / "mmgbsa.csv"
    write_mmgbsa_csv(csv_path, [a, b])
    rows = csv_path.read_text(encoding="utf-8").splitlines()
    assert rows[0].startswith("frame,time_ps,dG")
    assert len(rows) == 3


def test_leap_input_writes_split_prmtops() -> None:
    text = leap_input(
        protein_pdb="protein_leap.pdb",
        ligands=[("lig0_gaff.mol2", "lig0.frcmod", "AXI")],
        protein_ff="amber14",
        ligand_ff="gaff2",
        keep_water=False,
        solvent="gbn2",
        prmtop="complex.prmtop",
        inpcrd="complex.inpcrd",
        receptor_prmtop="receptor.prmtop",
        receptor_inpcrd="receptor.inpcrd",
        ligand_prmtop="ligand.prmtop",
        ligand_inpcrd="ligand.inpcrd",
    )
    assert "saveAmberParm PROT receptor.prmtop receptor.inpcrd" in text
    assert "saveAmberParm LIG0 ligand.prmtop ligand.inpcrd" in text
    assert "saveAmberParm COMP complex.prmtop complex.inpcrd" in text


@patch("mctoolkit.workers.protein_mmgbsa._score_prepared_holo")
@patch("mctoolkit.workers.protein_mmgbsa.build_gaff_split_prmtops")
@patch("mctoolkit.workers.protein_mmgbsa._amber_holo_system")
@patch("mctoolkit.workers.protein_prepare_ligand.prepare_ligands_for_gaff")
def test_mmgbsa_requires_ligand(
    mock_ligands, mock_amber, mock_split, mock_score, tmp_path: Path
) -> None:
    ala = tmp_path / "ala.pdb"
    ala.write_text(
        "ATOM      1  CA  ALA A   1      12.260   6.859  10.000  1.00  0.00           C\nEND\n",
        encoding="utf-8",
    )
    req = ProteinMMGBSARequest(
        input_path=str(ala),
        report_path=str(tmp_path / "out.txt"),
        ligand_smiles="C",
        minimize_first=False,
    )
    with pytest.raises(RuntimeError, match="GAFF or GAFF2"):
        score_protein_mmgbsa(req)
    mock_ligands.assert_not_called()
    mock_split.assert_not_called()
    mock_amber.assert_not_called()
    mock_score.assert_not_called()


def test_mmgbsa_dialog_defaults_and_menu(qapp, tmp_path, monkeypatch):  # noqa: ARG001
    from PySide6.QtWidgets import QMenuBar, QMessageBox, QTextEdit

    from mctoolkit.ui.dialogs.protein_mmgbsa import ProteinMMGBSADialog
    from mctoolkit.ui.protein_viewer import ProteinViewerDialog
    from mctoolkit.ui.user_guides import guide_html

    dlg = ProteinViewerDialog()
    mb = dlg.findChild(QMenuBar)
    tools_menu = qt_submenu(mb, "Tools")
    sim_menu = qt_submenu(tools_menu, "Simulate")
    labels = [a.text().replace("&", "") for a in sim_menu.actions()]
    assert any(label.startswith("MM-GBSA") for label in labels)
    assert any("Dynamics" in label for label in labels)

    html = guide_html("tools_mmgbsa")
    assert "Topic unavailable" not in html
    assert "1-trajectory" in html

    monkeypatch.setattr(QMessageBox, "information", lambda *_a, **_k: QMessageBox.Ok)
    dlg.open_mmgbsa_dialog()
    score = dlg._mmgbsa_dialog
    assert isinstance(score, ProteinMMGBSADialog)
    assert not score.findChildren(QTextEdit)
    assert score.combo_ligand_ff.currentData() == "gaff2"
    assert score.combo_solvent.currentData() == "gbn2"
    assert score.chk_minimize.isChecked()
    assert not score.chk_keep_water.isChecked()

    path = tmp_path / "holo.pdb"
    path.write_text(_HOLO_PDB, encoding="utf-8")
    dlg.load_structure_path(path)
    dlg.open_mmgbsa_dialog()
    score = dlg._mmgbsa_dialog
    assert score.radio_src_manager.isChecked()
    assert score.edit_out.text().endswith("holo_mmgbsa.txt")
    dlg.close()
