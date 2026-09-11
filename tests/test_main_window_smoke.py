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

"""Main-window mixin smoke tests (clear_all, selection, chemistry sources)."""

from __future__ import annotations

from rdkit import Chem

from molmanager.ui.main_window import ChemicalTableApp


def _seed_two_rows(w: ChemicalTableApp) -> None:
    w.headers = ["ID_HIDDEN", "Structure", "SMILES", "MW"]
    w._table_model.set_headers(list(w.headers))
    w._table_model.append_row(0, {"SMILES": "CCO", "MW": "46.07"})
    w._table_model.append_row(1, {"SMILES": "CC", "MW": "30.07"})
    w.mols[0] = Chem.MolFromSmiles("CCO")
    w.mols[1] = Chem.MolFromSmiles("CC")
    w.next_oid = 2


def test_clear_all_resets_table_and_ingest_flags(qapp):  # noqa: ARG001
    w = ChemicalTableApp()
    _seed_two_rows(w)
    w._selected_oids_override = frozenset({0})
    w._set_ingest_loading(True)

    w.clear_all()

    assert w._table_model.rowCount() == 0
    assert w.mols == {}
    assert w.headers == []
    assert w.next_oid == 0
    assert w._selected_oids_override is None
    assert w._ingest_loading is False


def test_exit_save_prompt_skipped_when_clean(qapp, monkeypatch):  # noqa: ARG001
    from PyQt5.QtGui import QCloseEvent
    from PyQt5.QtWidgets import QMessageBox

    w = ChemicalTableApp()
    w._suppress_exit_session_prompt = False
    assert not w._session_has_unsaved_changes()

    called = {"n": 0}

    def boom(*_a, **_k):
        called["n"] += 1
        return QMessageBox.Cancel

    monkeypatch.setattr(QMessageBox, "question", boom)
    ev = QCloseEvent()
    w.closeEvent(ev)
    assert called["n"] == 0
    assert ev.isAccepted()


def test_exit_save_prompt_shown_when_dirty(qapp, monkeypatch):  # noqa: ARG001
    from PyQt5.QtGui import QCloseEvent
    from PyQt5.QtWidgets import QMessageBox

    w = ChemicalTableApp()
    w._suppress_exit_session_prompt = False
    _seed_two_rows(w)
    w._mark_session_dirty()
    assert w._session_has_unsaved_changes()

    called = {"n": 0}

    def discard(*_a, **_k):
        called["n"] += 1
        return QMessageBox.Discard

    monkeypatch.setattr(QMessageBox, "question", discard)
    monkeypatch.setattr(w, "_prepare_application_shutdown", lambda: None)
    ev = QCloseEvent()
    w.closeEvent(ev)
    assert called["n"] == 1
    assert ev.isAccepted()


def test_save_session_clears_dirty(qapp, monkeypatch, tmp_path):  # noqa: ARG001
    from PyQt5.QtWidgets import QFileDialog

    w = ChemicalTableApp()
    _seed_two_rows(w)
    w._mark_session_dirty()
    out = tmp_path / "t.cms"
    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: (str(out), "MolManager Session (*.cms)"),
    )
    assert w.save_session_as() is True
    assert not w._session_has_unsaved_changes()


def test_session_load_uses_loading_page_then_reveals(qapp, monkeypatch):  # noqa: ARG001
    monkeypatch.setattr(
        ChemicalTableApp,
        "_try_auto_render_all_structures_after_ingest",
        lambda self: False,
    )
    w = ChemicalTableApp()
    doc = {
        "format": "molmanager_session",
        "version": w._SESSION_VERSION,
        "headers": ["ID_HIDDEN", "Structure", "SMILES", "MW"],
        "rows": [{"id": 0, "cells": {"SMILES": "CCO", "MW": "46"}}],
        "next_oid": 1,
    }
    seen = {"loading": False}

    orig_finalize = w._finalize_session_restore

    def wrap_finalize(d, max_id):
        seen["loading"] = w._table_stack.currentIndex() == 0
        return orig_finalize(d, max_id)

    monkeypatch.setattr(w, "_finalize_session_restore", wrap_finalize)
    w._apply_session_document(doc)
    assert seen["loading"] is True
    assert w._table_stack.currentIndex() == 1
    assert not w._session_has_unsaved_changes()
    assert not w._ingest_loading


def test_select_table_oids_updates_selection_set(qapp):  # noqa: ARG001
    w = ChemicalTableApp()
    _seed_two_rows(w)

    n = w.select_table_oids({1})
    qapp.processEvents()

    assert n == 1
    assert w._selected_oids_set() == {1}
    assert w._selected_logical_rows() == [1]


def test_selected_oids_override_preferred(qapp):  # noqa: ARG001
    w = ChemicalTableApp()
    _seed_two_rows(w)
    w.select_table_oids({0})
    qapp.processEvents()
    w._selected_oids_override = frozenset({1})

    assert w._selected_oids_set() == {1}


def test_chemistry_tool_structure_sources_smoke(qapp):  # noqa: ARG001
    w = ChemicalTableApp()
    _seed_two_rows(w)

    sources = w.chemistry_tool_structure_sources()
    assert sources[0] == "Structure"
    assert "SMILES" in sources
    assert "MW" not in sources
    assert w._canonical_smiles_header_for_updates() == "SMILES"


def test_new_window_and_file_load_use_table_only_layout(qapp):  # noqa: ARG001
    from molmanager.ui.main_window.workspace_layout import LAYOUT_TABLE_ONLY, LAYOUT_TABLE_STACK

    w = ChemicalTableApp()
    assert w._workspace_layout.layout_id == LAYOUT_TABLE_ONLY
    w.apply_workspace_layout(LAYOUT_TABLE_STACK)
    assert w._workspace_layout.layout_id == LAYOUT_TABLE_STACK
    w._apply_table_only_layout_for_file_load()
    assert w._workspace_layout.layout_id == LAYOUT_TABLE_ONLY


def test_docking_from_table_only_uses_split_view(qapp):  # noqa: ARG001
    from molmanager.ui.main_window.workspace_layout import LAYOUT_TABLE_ONLY, LAYOUT_TABLE_SINGLE

    w = ChemicalTableApp()
    assert w._workspace_layout.layout_id == LAYOUT_TABLE_ONLY
    pane = w._target_plot_pane()
    assert pane is not None
    assert w._workspace_layout.layout_id == LAYOUT_TABLE_SINGLE
    assert len(w._workspace_layout.plot_panes()) == 1
    assert w._workspace_layout.preferred_pane() is pane


def test_close_docked_plot_closes_without_prompt(qapp, monkeypatch):  # noqa: ARG001
    from PyQt5.QtWidgets import QLabel, QMessageBox

    from molmanager.ui.main_window.workspace_layout import LAYOUT_TABLE_SINGLE

    w = ChemicalTableApp()
    w.apply_workspace_layout(LAYOUT_TABLE_SINGLE)
    pane = w._workspace_layout.plot_panes()[0]
    plot = QLabel("plot")
    w._workspace_layout.dock_into_pane(pane, plot)

    prompted = []

    def _question(*args, **kwargs):
        prompted.append(True)
        return QMessageBox.No

    monkeypatch.setattr(QMessageBox, "question", _question)
    w.close_docked_plot(plot)
    assert prompted == []
    assert list(pane.plot_widgets()) == []


def test_close_plot_pane_prompts_when_occupied(qapp, monkeypatch):  # noqa: ARG001
    from PyQt5.QtWidgets import QLabel, QMessageBox

    from molmanager.ui.main_window.workspace_layout import LAYOUT_TABLE_SINGLE

    w = ChemicalTableApp()
    w.apply_workspace_layout(LAYOUT_TABLE_SINGLE)
    pane = w._workspace_layout.plot_panes()[0]
    w._workspace_layout.dock_into_pane(pane, QLabel("plot"))

    answers = iter([QMessageBox.No, QMessageBox.Yes])
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: next(answers),
    )
    w.close_plot_pane(pane)
    assert pane in w._workspace_layout.plot_panes()
    assert list(pane.plot_widgets())

    w.close_plot_pane(pane)
    from molmanager.ui.main_window.workspace_layout import LAYOUT_TABLE_ONLY

    assert w._workspace_layout.layout_id == LAYOUT_TABLE_ONLY
    assert list(w.iter_docked_plot_widgets()) == []


def test_close_empty_plot_pane_skips_prompt(qapp, monkeypatch):  # noqa: ARG001
    from PyQt5.QtWidgets import QMessageBox

    from molmanager.ui.main_window.workspace_layout import LAYOUT_TABLE_SIDE

    w = ChemicalTableApp()
    w.apply_workspace_layout(LAYOUT_TABLE_SIDE)
    pane = w._workspace_layout.plot_panes()[1]
    assert pane.is_empty()

    called = {"n": 0}

    def boom(*_a, **_k):
        called["n"] += 1
        return QMessageBox.No

    monkeypatch.setattr(QMessageBox, "question", boom)
    w.close_plot_pane(pane)
    assert called["n"] == 0
    assert len(w._workspace_layout.plot_panes()) == 1
    assert pane not in w._workspace_layout.plot_panes()


def test_clear_all_re_enables_menubar_after_ingest(qapp):  # noqa: ARG001
    w = ChemicalTableApp()
    _seed_two_rows(w)
    mb = w.menuBar()
    file_menu = next(a.menu() for a in mb.actions() if a.menu() is not None)
    w._set_ingest_loading(True)
    assert not file_menu.isEnabled()

    w.clear_all()

    assert file_menu.isEnabled()
    assert w._btn_workspace_layout.isEnabled()
