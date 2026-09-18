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

"""Unified Superpose dialog configuration."""

from __future__ import annotations

import pytest

pytest.importorskip("PyQt5.QtWidgets")

from molmanager.ui.dialogs.mol_tools import SuperposeDialog
from molmanager.workers import SuperposeParams, SuperposeStructuresParams


def _set_combo_data(combo, data) -> None:
    for i in range(combo.count()):
        if combo.itemData(i) == data or (data == "" and not combo.itemData(i)):
            combo.setCurrentIndex(i)
            return
    raise AssertionError(repr(data))


def test_superpose_dialog_unifies_modes(qapp):  # noqa: ARG001
    d = SuperposeDialog(
        2,
        source_columns=["Structure", "confs"],
        has_confs=True,
        default_target="structures",
    )
    assert d.windowTitle() == "Superpose"
    assert d.target() == "structures"
    assert isinstance(d.params(), SuperposeStructuresParams)
    _set_combo_data(d.target_combo, "conformers")
    assert d.target() == "conformers"
    p = d.conformer_params()
    assert isinstance(p, SuperposeParams)
    assert p.geometry == "3d"
    assert p.align_mode == ""
    _set_combo_data(d.geom_combo, "2d")
    assert d.conformer_params().geometry == "2d"
    _set_combo_data(d.target_combo, "structures")
    sp = d.structure_params()
    assert isinstance(sp, SuperposeStructuresParams)
    assert sp.geometry == "2d"
    assert sp.use_mcs is True
    assert sp.use_o3a is True
    d.close()


def test_superpose_dialog_disables_conformers_without_confs(qapp):  # noqa: ARG001
    d = SuperposeDialog(0, has_confs=False, default_target="conformers")
    item = d.target_combo.model().item(0)
    assert item is not None
    assert item.isEnabled() is False
    assert d.target() == "structures"
    d.close()


def test_superpose_dialog_ring_and_pattern_params(qapp):  # noqa: ARG001
    d = SuperposeDialog(0, has_confs=True, default_target="conformers")
    _set_combo_data(d.align_on_combo, "largest_ring")
    p = d.conformer_params()
    assert p.align_mode == "largest_ring"
    assert p.align_pattern == ""
    _set_combo_data(d.align_on_combo, "central_ring")
    assert d.conformer_params().align_mode == "central_ring"
    _set_combo_data(d.align_on_combo, "pattern")
    d.align_pat_edit.setText("c1ccccc1")
    d.align_smarts_cb.setChecked(True)
    p = d.conformer_params()
    assert p.align_mode == ""
    assert p.align_pattern == "c1ccccc1"
    assert p.align_pattern_is_smarts is True
    sp = d.structure_params()
    assert sp.align_mode == ""
    assert sp.align_pattern == "c1ccccc1"
    d.close()


def test_open_superpose_keeps_table_selectable(qapp):  # noqa: ARG001
    from PyQt5.QtCore import Qt
    from PyQt5.QtWidgets import QAbstractItemView

    from molmanager.ui.main_window import ChemicalTableApp

    w = ChemicalTableApp()
    w.headers = ["ID_HIDDEN", "Structure", "SMILES"]
    w._table_model.set_headers(list(w.headers))
    w._table_model.append_row(0, {"SMILES": "CCO"})
    w.next_oid = 1
    w.open_superpose()
    qapp.processEvents()
    dlg = next(iter(w.findChildren(SuperposeDialog)), None)
    assert dlg is not None
    assert dlg.isModal() is False
    assert dlg.windowModality() == Qt.NonModal
    assert w.table.isEnabled()
    assert w.table.selectionMode() == QAbstractItemView.ExtendedSelection
    dlg.close()
    w.close()
