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

"""Tautomer / protomer result browser (pose-style 2D table + arrows)."""

from __future__ import annotations

from mctoolkit.ui.browsers.chrome import BrowserHostDialog
from mctoolkit.ui.dockable_plot import is_dockable_workspace_widget
from mctoolkit.ui.protomer_browser import ProtomerBrowserDialog, groups_from_protomer_rows
from mctoolkit.ui.tautomer_browser import (
    TautomerBrowserDialog,
    TautomerBrowserWidget,
    groups_from_tautomer_rows,
)


def test_form_browser_widgets_are_workspace_dockable():
    assert getattr(TautomerBrowserWidget, "dockable_in_workspace", False) is True
    assert is_dockable_workspace_widget(TautomerBrowserWidget)
    assert issubclass(TautomerBrowserDialog, BrowserHostDialog)
    assert issubclass(ProtomerBrowserDialog, BrowserHostDialog)


def test_groups_from_tautomer_rows_sorts_by_score():
    groups = groups_from_tautomer_rows(
        [
            (1, "Oc1ccccn1", 100, False, True),
            (1, "O=c1cccc[nH]1", 102, True, False),
            (2, "CCO", 5, True, True),
        ]
    )
    assert [g.source_oid for g in groups] == [1, 2]
    assert [h.smiles for h in groups[0].hits] == ["O=c1cccc[nH]1", "Oc1ccccn1"]
    assert groups[0].hits[0].canonical == "Yes"
    assert groups[1].hits[0].smiles == "CCO"


def test_groups_from_protomer_rows_sorts_by_percent():
    groups = groups_from_protomer_rows(
        [
            (3, "CC(=O)[O-]", 12.5),
            (3, "CC(=O)O", 87.5),
        ]
    )
    assert len(groups) == 1
    assert [h.score_text for h in groups[0].hits] == ["87.50", "12.50"]


def test_tautomer_browser_arrows_step_forms(qapp):  # noqa: ARG001
    w = TautomerBrowserWidget(None)
    w.set_groups(
        groups_from_tautomer_rows(
            [
                (1, "Oc1ccccn1", 100, False, True),
                (1, "O=c1cccc[nH]1", 102, True, False),
            ]
        )
    )
    assert w._row_table.rowCount() == 2
    assert w._row_table.horizontalHeaderItem(1).text() == "Score"
    assert w.current_hit().smiles == "O=c1cccc[nH]1"
    w._step(1)
    assert w.current_hit().smiles == "Oc1ccccn1"
    w._step(1)
    assert w.current_hit().smiles == "O=c1cccc[nH]1"
    w.close()


def test_tautomer_dialog_opens_browser_on_finish(qapp):  # noqa: ARG001
    from mctoolkit.ui.dialogs.tautomer import TautomerGeneratorDialog

    opened: list = []

    class _App:
        def _selected_logical_rows(self):
            return []

        def _finish_tool_progress(self, *_a, **_k):
            return None

        def _consume_partial_results_notice(self):
            return None

        def open_tautomer_browser(self, rows):
            opened.append(list(rows))

    dlg = TautomerGeneratorDialog(None)
    dlg.parent_app = _App()
    try:
        assert not hasattr(dlg, "results_table")
        dlg._on_finished([(1, "CCO", 5, True, True)])
        assert opened and opened[0][0][1] == "CCO"
    finally:
        dlg.close()


def test_protomer_dialog_opens_browser_on_finish(qapp):  # noqa: ARG001
    from mctoolkit.ui.dialogs.protomer import ProtomerGeneratorDialog

    opened: list = []

    class _App:
        mols = {}
        _table_model = type("M", (), {"logical_row_for_oid": staticmethod(lambda oid: -1)})()

        def _selected_logical_rows(self):
            return []

        def _finish_tool_progress(self, *_a, **_k):
            return None

        def _consume_partial_results_notice(self):
            return None

        def open_protomer_browser(self, rows):
            opened.append(list(rows))

        def on_calc_finished(self, *_a, **_k):
            return None

    dlg = ProtomerGeneratorDialog(None)
    dlg.parent_app = _App()
    try:
        assert not hasattr(dlg, "results_table")
        dlg._on_finished([(1, "CCO", 100.0)])
        assert opened and opened[0][0][1] == "CCO"
    finally:
        dlg.close()
