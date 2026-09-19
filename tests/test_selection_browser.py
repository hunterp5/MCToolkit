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

"""Data → Browser shows the current table row in a compact table."""

from __future__ import annotations

from PyQt5.QtWidgets import QSizePolicy
from rdkit import Chem

from molmanager.ui.main_window import ChemistryWorkspaceWindow
from molmanager.ui.selection_browser import SelectionBrowserWidget


def _seed_row(app: ChemistryWorkspaceWindow) -> None:
    app.headers = ["ID_HIDDEN", "Structure", "SMILES", "Name", "MW"]
    app._table_model.set_headers(list(app.headers))
    app._table_model.append_row(0, {"SMILES": "CCO", "Name": "ethanol", "MW": "46.07"})
    app.mols[0] = Chem.MolFromSmiles("CCO")
    app.next_oid = 1


def test_selection_browser_shows_current_row_table(qapp):  # noqa: ARG001
    w = ChemistryWorkspaceWindow()
    _seed_row(w)
    panel = SelectionBrowserWidget(w)
    assert getattr(panel, "_prop_panel", None) is None
    assert not hasattr(panel, "_spin_field_count")
    table = panel._row_table
    assert table.rowCount() == 1
    headers = [table.horizontalHeaderItem(i).text() for i in range(table.columnCount())]
    assert headers == ["SMILES", "Name", "MW"]
    assert table.item(0, 0).text() == "CCO"
    assert table.item(0, 1).text() == "ethanol"
    assert table.item(0, 2).text() == "46.07"
    assert panel._btn_toggle_select.text() == ""
    assert not panel._btn_toggle_select.icon().isNull()
    assert panel._btn_toggle_select.isCheckable()
    assert panel._btn_toggle_select.sizePolicy().horizontalPolicy() == QSizePolicy.Expanding
    panel.deleteLater()
    w.close()


def test_selection_browser_row_table_follows_navigation(qapp):  # noqa: ARG001
    w = ChemistryWorkspaceWindow()
    _seed_row(w)
    w._table_model.append_row(1, {"SMILES": "CCC", "Name": "propane", "MW": "44.10"})
    w.mols[1] = Chem.MolFromSmiles("CCC")
    w.next_oid = 2
    panel = SelectionBrowserWidget(w)
    panel._cb_only_selected.setChecked(False)
    panel.refresh_from_app()
    assert panel._row_table.item(0, 1).text() == "ethanol"
    panel._step(1)
    assert panel._row_table.item(0, 0).text() == "CCC"
    assert panel._row_table.item(0, 1).text() == "propane"
    panel.deleteLater()
    w.close()


def test_selection_browser_row_table_keeps_size_while_navigating(qapp):  # noqa: ARG001
    w = ChemistryWorkspaceWindow()
    _seed_row(w)
    w._table_model.append_row(
        1,
        {
            "SMILES": "CCCCCCCCCCCCCCCCCCCC",
            "Name": "a much longer compound name than ethanol",
            "MW": "1234.5678",
        },
    )
    w.mols[1] = Chem.MolFromSmiles("CCCCCCCCCC")
    w.next_oid = 2
    panel = SelectionBrowserWidget(w)
    panel._cb_only_selected.setChecked(False)
    panel.refresh_from_app()
    table = panel._row_table
    height = table.height()
    col_w = table.columnWidth(0)
    panel._step(1)
    assert table.height() == height
    assert table.columnWidth(0) == col_w
    panel.deleteLater()
    w.close()


def test_selection_browser_caption_in_header_bar(qapp):  # noqa: ARG001
    w = ChemistryWorkspaceWindow()
    _seed_row(w)
    panel = SelectionBrowserWidget(w)
    panel._cb_only_selected.setChecked(False)
    panel.refresh_from_app()
    assert panel._meta.parent() is panel._footer_bar
    assert panel.layout().indexOf(panel._footer_bar) == 0
    assert panel.layout().indexOf(panel._meta) == -1
    foot = panel._footer_bar.layout()
    assert foot.indexOf(panel._header_left) == 0
    assert foot.indexOf(panel._meta) == 1
    assert foot.indexOf(panel._header_right) == 2
    assert panel._opts_btn.parent() is panel._header_left
    assert panel._add_to_main_btn.parent() is panel._header_right
    assert "Table:" in panel._meta.text()
    assert "1 / 1" in panel._meta.text()
    header_font = w.table.horizontalHeader().font()
    assert panel._meta.font().pointSize() == header_font.pointSize()
    assert panel._meta.font().family() == header_font.family()
    panel.deleteLater()
    w.close()
