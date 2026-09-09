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

"""Tests for the Predict SOM results browser."""

from __future__ import annotations

from molmanager.som_prediction import (
    SOM_CANCELLED_ERROR,
    SOM_MAP_COLUMN,
    SOM_PROB_COLUMN,
    SOM_SITES_COLUMN,
    SomAtomHit,
)
from molmanager.ui.dockable_plot import is_dockable_workspace_widget
from molmanager.ui.som_browser import (
    SomBrowseRecord,
    SomBrowserWidget,
    records_from_worker_rows,
)


def test_records_from_worker_rows_maps_atoms() -> None:
    rows = [
        (
            7,
            {SOM_MAP_COLUMN: "CCO", SOM_SITES_COLUMN: "0", SOM_PROB_COLUMN: "0:0.90"},
            b"",
            [SomAtomHit(0, 0.9, True), SomAtomHit(1, 0.1, False)],
            [SOM_MAP_COLUMN],
        ),
        (
            None,
            {SOM_MAP_COLUMN: "Empty SMILES."},
            None,
            [],
            [SOM_MAP_COLUMN],
        ),
    ]
    recs = records_from_worker_rows(rows)
    assert len(recs) == 2
    assert recs[0].oid == 7
    assert recs[0].smiles == "CCO"
    assert recs[0].atoms[0].is_som
    assert recs[0].error is None
    assert recs[1].oid is None
    assert recs[1].error == "Empty SMILES."
    assert recs[1].smiles == ""


def test_records_from_worker_rows_omits_cancelled() -> None:
    rows = [
        (
            1,
            {SOM_MAP_COLUMN: "CCO", SOM_SITES_COLUMN: "0", SOM_PROB_COLUMN: "0:0.90"},
            b"",
            [SomAtomHit(0, 0.9, True)],
            [SOM_MAP_COLUMN],
        ),
        (
            2,
            {SOM_MAP_COLUMN: SOM_CANCELLED_ERROR},
            None,
            [],
            [SOM_MAP_COLUMN],
        ),
    ]
    recs = records_from_worker_rows(rows)
    assert len(recs) == 1
    assert recs[0].oid == 1
    all_recs = records_from_worker_rows(rows, include_cancelled=True)
    assert len(all_recs) == 2
    assert all_recs[1].error == SOM_CANCELLED_ERROR


def test_som_browser_widget_is_workspace_dockable():
    assert getattr(SomBrowserWidget, "dockable_in_workspace", False) is True
    assert is_dockable_workspace_widget(SomBrowserWidget)
    assert hasattr(SomBrowserWidget, "create_floating_dialog")
    assert hasattr(SomBrowserWidget, "_toggle_options_visible")


def test_som_browser_steps_between_maps(qapp) -> None:  # noqa: ARG001
    recs = [
        SomBrowseRecord(
            oid=1,
            smiles="CCO",
            atoms=(SomAtomHit(0, 0.9, True), SomAtomHit(1, 0.1, False)),
            columns={SOM_SITES_COLUMN: "0", SOM_PROB_COLUMN: "0:0.90"},
        ),
        SomBrowseRecord(
            oid=2,
            smiles="c1ccccc1",
            atoms=(SomAtomHit(0, 0.2, False),),
            columns={SOM_SITES_COLUMN: "—", SOM_PROB_COLUMN: "0:0.20"},
        ),
    ]
    w = SomBrowserWidget(None)
    w.set_records(recs)
    assert "1 / 2" in w._meta.text()
    assert "SOM sites 0" in w._summary.text()
    assert w._atom_table.rowCount() == 2
    w._step(1)
    assert "2 / 2" in w._meta.text()
    assert w._atom_table.rowCount() == 1
    w._go_first()
    assert "1 / 2" in w._meta.text()
    w.close()


def test_som_browser_emphasizes_selected_atom(qapp) -> None:  # noqa: ARG001
    recs = [
        SomBrowseRecord(
            oid=1,
            smiles="CCO",
            atoms=(SomAtomHit(0, 0.9, True), SomAtomHit(1, 0.1, False)),
            columns={SOM_SITES_COLUMN: "0", SOM_PROB_COLUMN: "0:0.90"},
        ),
    ]
    w = SomBrowserWidget(None)
    w.set_records(recs)
    assert w._emphasized_atom is None
    w._atom_table.selectRow(1)
    assert w._emphasized_atom == 1
    w._atom_table.clearSelection()
    assert w._emphasized_atom is None
    w.close()


def test_som_browser_dialog_set_records_without_panel(qapp) -> None:  # noqa: ARG001
    from molmanager.ui.som_browser import SomBrowserDialog

    dlg = SomBrowserDialog(None)
    dlg._panel = None
    dlg.set_records([])
    dlg.close()


def test_som_browser_nav_shortcuts_are_widget_scoped(qapp) -> None:  # noqa: ARG001
    from PyQt5.QtCore import Qt
    from PyQt5.QtWidgets import QShortcut

    w = SomBrowserWidget(None)
    scs = w.findChildren(QShortcut)
    assert scs
    assert all(sc.context() == Qt.WidgetWithChildrenShortcut for sc in scs)
    w.close()


def test_discard_host_dialog_after_dock_clears_attr(qapp) -> None:  # noqa: ARG001
    from PyQt5.QtWidgets import QDialog

    from molmanager.ui.dockable_plot import discard_host_dialog_after_dock

    class Host:
        _dlg = None

    host = Host()
    dlg = QDialog()
    dlg._panel = object()
    dlg._force_close = False
    host._dlg = dlg
    discard_host_dialog_after_dock(dlg, host, "_dlg")
    assert host._dlg is None
    qapp.processEvents()
