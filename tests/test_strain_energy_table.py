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

"""Strain energy results table in the conformer viewer."""

from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QTableWidget
from rdkit import Chem
from rdkit.Chem import AllChem

from molmanager.confs_codec import conformer_mol_blocks_b64_json
from molmanager.ui.mol_viewer_3d import (
    Molecule3DViewerWidget,
    conf_legend_entries,
    distinct_superpose_colors,
    populate_strain_energy_table,
    superpose_color_for_conf,
)


def _overlay() -> dict:
    return {
        "energies": [10.0, 12.5, 11.0],
        "deltas": [0.0, 2.5, 1.0],
        "deltas_min": [0.0, 2.5, 1.0],
        "pop_fracs": [0.80, 0.05, 0.15],
        "rmsds": [0.0, 0.42, 0.21],
        "e_ref": 10.0,
        "e_min": 10.0,
        "ref_idx": 0,
        "ff": "MMFF",
        "energies_by_ff": {
            "MMFF": [10.0, 12.5, 11.0],
            "UFF": [3.0, 4.5, 3.5],
        },
    }


def test_populate_strain_energy_table_columns(qapp) -> None:  # noqa: ARG001
    table = QTableWidget()
    n = populate_strain_energy_table(table, _overlay())
    assert n == 3
    headers = [table.horizontalHeaderItem(i).text() for i in range(table.columnCount())]
    assert headers[:6] == ["Conf", "E", "ΔE vs ref", "ΔE vs min", "Pop. %", "RMSD"]
    assert "E (UFF)" in headers
    assert table.item(0, 0).text() == "1"
    assert int(table.item(0, 0).data(Qt.UserRole)) == 0
    assert abs(float(table.item(1, 5).text()) - 0.42) < 1e-6


def test_strain_energy_viewer_shows_conformer_table(qapp) -> None:  # noqa: ARG001
    mol = Chem.MolFromSmiles("CCO")
    AllChem.EmbedMultipleConfs(mol, numConfs=3, randomSeed=0xC0FFEE)
    viewer = Molecule3DViewerWidget(
        mol,
        None,
        window_title="Strain Energy",
        multi_conf_blocks_json_b64=conformer_mol_blocks_b64_json(mol),
        strain_overlay=_overlay(),
        multi_conf_initial_index=0,
    )
    assert viewer._strain_table is not None
    assert viewer._strain_table.rowCount() == 3
    assert viewer._conf_nav_host is not None
    from PyQt5.QtWidgets import QHBoxLayout

    assert isinstance(viewer._conf_nav_host.layout(), QHBoxLayout)
    assert viewer._btn_conf_back.parent() is viewer._conf_nav_host
    assert viewer._add_to_main_btn.parent() is viewer._footer_bar
    assert viewer._btn_export_table is not None
    assert viewer._btn_export_table.parent() is viewer._conf_nav_host
    root = viewer.layout()
    assert root.indexOf(viewer._footer_bar) == 0
    assert root.indexOf(viewer._conf_nav_host) == root.count() - 1
    assert viewer.embedded_minimum_width() >= 1200
    assert not hasattr(viewer, "_toggle_options_btn")
    assert viewer._btn_conf_back.text() == "←"
    assert viewer._btn_conf_fwd.text() == "→"
    assert not viewer._cb_superpose.isChecked()
    assert getattr(viewer, "_radio_conf_one", None) is None
    assert getattr(viewer, "_conf_label", None) is None
    from PyQt5.QtWidgets import QAbstractItemView

    assert viewer._strain_table.selectionMode() == QAbstractItemView.ExtendedSelection
    assert viewer._cb_only_selected_confs is not None
    assert viewer._cb_only_selected_confs.text() == "Selected Conformers"
    table = viewer._strain_table
    table.selectRow(0)
    from PyQt5.QtCore import QItemSelectionModel

    sm = table.selectionModel()
    assert sm is not None
    sm.select(table.model().index(2, 0), QItemSelectionModel.Select | QItemSelectionModel.Rows)
    viewer._cb_only_selected_confs.setChecked(True)
    assert viewer._visible_conf_indices() == [0, 2]
    assert viewer._conf_superposed is True
    assert viewer._cb_superpose.isChecked()
    legend = viewer._conf_legend_payload()
    colors = distinct_superpose_colors(2)
    assert legend == [
        {"id": "1", "color": colors[0]},
        {"id": "3", "color": colors[1]},
    ]
    sm.select(table.model().index(1, 0), QItemSelectionModel.Select | QItemSelectionModel.Rows)
    assert viewer._visible_conf_indices() == [0, 1, 2]
    assert viewer._conf_superposed is True
    assert viewer._conf_legend_payload() == conf_legend_entries([0, 1, 2])
    viewer._cb_only_selected_confs.setChecked(False)
    assert viewer._visible_conf_indices() == [0, 1, 2]
    assert viewer._conf_legend_payload() is None
    viewer.deleteLater()


def test_conf_legend_entries_use_table_conf_ids():
    colors = distinct_superpose_colors(2)
    assert conf_legend_entries([0, 2]) == [
        {"id": "1", "color": colors[0]},
        {"id": "3", "color": colors[1]},
    ]
    assert colors[0].lower() != colors[1].lower()
    assert superpose_color_for_conf(0) != superpose_color_for_conf(1)


def test_distinct_superpose_colors_are_unique():
    from molmanager.ui.mol_viewer_3d import _SUPERPOSE_PALETTE

    assert len(_SUPERPOSE_PALETTE) == len({c.lower() for c in _SUPERPOSE_PALETTE})
    for n in (8, 24, 32, 40, 64):
        colors = distinct_superpose_colors(n)
        assert len(colors) == n
        assert len({c.lower() for c in colors}) == n


def test_conf_legend_only_when_selected_conformers_checked(qapp) -> None:  # noqa: ARG001
    mol = Chem.MolFromSmiles("CCO")
    AllChem.EmbedMultipleConfs(mol, numConfs=3, randomSeed=0xC0FFEE)
    viewer = Molecule3DViewerWidget(
        mol,
        None,
        window_title="Strain Energy",
        multi_conf_blocks_json_b64=conformer_mol_blocks_b64_json(mol),
        strain_overlay=_overlay(),
        multi_conf_initial_superpose=True,
    )
    assert viewer._cb_superpose.isChecked()
    table = viewer._strain_table
    assert table is not None
    table.selectRow(0)
    from PyQt5.QtCore import QItemSelectionModel

    sm = table.selectionModel()
    assert sm is not None
    sm.select(table.model().index(2, 0), QItemSelectionModel.Select | QItemSelectionModel.Rows)
    viewer._show_superpose()
    assert viewer._conf_superposed is True
    assert viewer._conf_legend_payload() is None
    viewer._cb_only_selected_confs.setChecked(True)
    assert viewer._visible_conf_indices() == [0, 2]
    assert viewer._conf_legend_payload() == conf_legend_entries([0, 2])
    viewer.deleteLater()


def test_conformer_results_dialog_opens_wide_enough(qapp) -> None:  # noqa: ARG001
    from molmanager.ui.mol_viewer_3d import Molecule3DViewerDialog

    mol = Chem.MolFromSmiles("CCO")
    AllChem.EmbedMultipleConfs(mol, numConfs=3, randomSeed=0xC0FFEE)
    dlg = Molecule3DViewerDialog(
        mol,
        None,
        window_title="View Conformers",
        multi_conf_blocks_json_b64=conformer_mol_blocks_b64_json(mol),
        strain_overlay=_overlay(),
    )
    min_w = dlg.minimumWidth()
    assert min_w >= 1200
    assert dlg.width() >= min_w
    footer = dlg._viewer_widget._conf_nav_host
    assert footer is not None
    assert min_w >= footer.sizeHint().width()
    dlg.deleteLater()
