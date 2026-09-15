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
        "filter_panel_visible": True,
    }
    seen = {"loading": False, "filters_covered": False}

    orig_begin = w._begin_session_finalize
    orig_filters = w._finalize_session_filters

    def wrap_begin(d, max_id, *, gen):
        seen["loading"] = w._table_stack.currentWidget() is w._loading_page
        return orig_begin(d, max_id, gen=gen)

    def wrap_filters(d, max_id):
        orig_filters(d, max_id)
        seen["filters_covered"] = not w.f_panel.isVisibleTo(w._workspace_stack)
        seen["filters_restored"] = not w.f_panel.isHidden()

    monkeypatch.setattr(w, "_begin_session_finalize", wrap_begin)
    monkeypatch.setattr(w, "_finalize_session_filters", wrap_filters)
    w._apply_session_document(doc)
    assert seen["loading"] is True
    assert seen["filters_covered"] is True
    assert seen["filters_restored"] is True
    assert w._table_stack.currentWidget() is w._workspace_ready_page
    assert w.f_panel.isVisibleTo(w._workspace_stack)
    assert not w._session_has_unsaved_changes()
    assert not w._ingest_loading


def test_session_load_holds_table_until_render_finishes(qapp, monkeypatch):  # noqa: ARG001
    from PyQt5.QtCore import QTimer

    held = {"loading": False}

    def fake_render(self):
        held["loading"] = self._table_stack.currentIndex() == 0
        QTimer.singleShot(0, self._session_on_render2d_batch_finished)
        return True

    monkeypatch.setattr(
        ChemicalTableApp,
        "_try_auto_render_all_structures_after_ingest",
        fake_render,
    )
    w = ChemicalTableApp()
    doc = {
        "format": "molmanager_session",
        "version": w._SESSION_VERSION,
        "headers": ["ID_HIDDEN", "Structure", "SMILES", "MW"],
        "rows": [{"id": 0, "cells": {"SMILES": "CCO", "MW": "46"}}],
        "next_oid": 1,
    }
    w._apply_session_document(doc)
    assert held["loading"] is True
    assert w._table_stack.currentIndex() == 1
    assert not w._session_awaiting_ready
    assert not w._ingest_loading


def test_file_ingest_holds_table_until_render_finishes(qapp, monkeypatch):  # noqa: ARG001
    from PyQt5.QtCore import QTimer

    monkeypatch.setattr("molmanager.ui.theme.load_status_bar_visible", lambda: True)
    monkeypatch.setattr("molmanager.ui.gui_settings_mixin.load_status_bar_visible", lambda: True)

    held = {"loading": False}

    def fake_render(self):
        held["loading"] = self._table_stack.currentIndex() == 0
        QTimer.singleShot(0, self._ingest_on_render2d_batch_finished)
        return True

    monkeypatch.setattr(
        ChemicalTableApp,
        "_try_auto_render_all_structures_after_ingest",
        fake_render,
    )
    w = ChemicalTableApp()
    _seed_two_rows(w)
    w._set_ingest_loading(True)
    w._ingest_prep_before_reveal = True
    w._set_workspace_stack_index(0)
    w._post_ingest_after_color_caches()
    # Bounds complete via QTimer before auto-render starts.
    qapp.processEvents()
    assert held["loading"] is True
    assert w._table_stack.currentIndex() == 0
    assert w._ingest_waiting_for_render is True
    assert "Render 2D" in (w._loading_detail.text() or "")
    assert w._status_host.isHidden()
    assert not w._memory_status_timer.isActive()
    qapp.processEvents()
    assert w._table_stack.currentIndex() == 1
    assert not w._ingest_waiting_for_render
    assert not w._ingest_loading
    assert not w._status_host.isHidden()
    assert w._memory_status_timer.isActive()


def test_file_ingest_reveals_immediately_when_auto_render_skipped(qapp, monkeypatch):  # noqa: ARG001
    monkeypatch.setattr("molmanager.ui.theme.load_status_bar_visible", lambda: True)
    monkeypatch.setattr("molmanager.ui.gui_settings_mixin.load_status_bar_visible", lambda: True)

    def fake_render(self):
        self.status_label.setText("Loaded 2 rows — auto 2D render skipped (limit 1).")
        return False

    monkeypatch.setattr(
        ChemicalTableApp,
        "_try_auto_render_all_structures_after_ingest",
        fake_render,
    )
    w = ChemicalTableApp()
    _seed_two_rows(w)
    w._set_ingest_loading(True)
    w._ingest_prep_before_reveal = True
    w._set_workspace_stack_index(0)
    w._post_ingest_after_color_caches()
    qapp.processEvents()
    assert w._table_stack.currentIndex() == 1
    assert not w._ingest_waiting_for_render
    assert not w._ingest_loading
    assert "auto 2D render skipped" in w.status_label.text()


def test_file_ingest_holds_overlay_for_large_auto_render(qapp, monkeypatch):  # noqa: ARG001
    """Auto Render 2D always blocks reveal (no progressive background reveal)."""
    monkeypatch.setattr("molmanager.ui.theme.load_status_bar_visible", lambda: True)
    monkeypatch.setattr("molmanager.ui.gui_settings_mixin.load_status_bar_visible", lambda: True)

    def fake_render(self):
        return True

    monkeypatch.setattr(
        ChemicalTableApp,
        "_try_auto_render_all_structures_after_ingest",
        fake_render,
    )
    w = ChemicalTableApp()
    _seed_two_rows(w)
    w._set_ingest_loading(True)
    w._ingest_prep_before_reveal = True
    w._set_workspace_stack_index(0)
    w._post_ingest_after_color_caches()
    qapp.processEvents()
    assert w._table_stack.currentIndex() == 0
    assert w._ingest_waiting_for_render is True
    assert w._ingest_loading
    assert w._status_host.isHidden()
    w._ingest_on_render2d_batch_finished()
    assert w._table_stack.currentIndex() == 1
    assert not w._ingest_waiting_for_render
    assert not w._ingest_loading


def test_file_ingest_progress_updates_loading_overlay(qapp, monkeypatch):  # noqa: ARG001
    monkeypatch.setattr("molmanager.ui.theme.load_status_bar_visible", lambda: True)
    monkeypatch.setattr("molmanager.ui.gui_settings_mixin.load_status_bar_visible", lambda: True)
    w = ChemicalTableApp()
    _seed_two_rows(w)
    w._set_ingest_loading(True)
    w._set_workspace_stack_index(0)
    w._on_tool_progress("Render 2D", 3, 10)
    assert "Render 2D" in (w._loading_detail.text() or "")
    assert "3/10" in (w._loading_detail.text() or "")
    assert w._status_host.isHidden()
    assert not w._memory_status_timer.isActive()
    w._set_ingest_loading(False)
    w._set_workspace_stack_index(1)
    assert not w._status_host.isHidden()
    assert w._memory_status_timer.isActive()


def test_search_open_does_not_inset_filter_cards(qapp):  # noqa: ARG001
    w = ChemicalTableApp()
    w.f_panel.setVisible(True)
    w._search_panel.setVisible(True)
    w._search_panel.resize(400, 64)
    w._sync_filter_panel_scroll_content()
    assert getattr(w, "_filter_table_top_pad", None) is None
    layout = w.f_panel.layout()
    assert layout is not None
    assert layout.itemAt(0).widget() is w._filter_scroll


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


def test_delete_selection_kind_rows_columns_cells(qapp):  # noqa: ARG001
    from PyQt5.QtCore import QItemSelectionModel

    w = ChemicalTableApp()
    _seed_two_rows(w)
    assert w._delete_selection_kind() == "empty"

    w.select_table_oids({0})
    qapp.processEvents()
    assert w._delete_selection_kind() == "rows"

    w.clear_table_selection()
    w._select_columns([3])
    qapp.processEvents()
    assert w._delete_selection_kind() == "columns"
    assert w._selected_full_column_indices() == [3]

    w.clear_table_selection()
    sm = w.table.selectionModel()
    view = w.table.model()
    sm.select(view.index(0, 3), QItemSelectionModel.ClearAndSelect)
    qapp.processEvents()
    assert w._delete_selection_kind() == "cells"

    w._selected_oids_override = frozenset({0})
    w._select_columns([3])
    qapp.processEvents()
    assert w._delete_selection_kind() == "both"


def test_delete_selection_clears_cells_after_confirm(qapp, monkeypatch):  # noqa: ARG001
    from PyQt5.QtCore import QItemSelectionModel
    from PyQt5.QtWidgets import QMessageBox

    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    w = ChemicalTableApp()
    _seed_two_rows(w)
    sm = w.table.selectionModel()
    view = w.table.model()
    sm.select(view.index(0, 3), QItemSelectionModel.ClearAndSelect)
    w.edit_delete_selection()
    assert w._table_model.cell_text(0, 3) == ""
    assert w._table_model.cell_text(1, 3) == "30.07"


def test_delete_selection_deletes_column_after_confirm(qapp, monkeypatch):  # noqa: ARG001
    from PyQt5.QtWidgets import QMessageBox

    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    w = ChemicalTableApp()
    _seed_two_rows(w)
    w._select_columns([3])
    w.edit_delete_selection()
    assert "MW" not in w.headers
    assert w._table_model.rowCount() == 2


def test_delete_selection_both_can_choose_columns(qapp, monkeypatch):  # noqa: ARG001
    from PyQt5.QtWidgets import QMessageBox

    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    w = ChemicalTableApp()
    _seed_two_rows(w)
    w._selected_oids_override = frozenset({0})
    w._select_columns([3])
    monkeypatch.setattr(w, "_ask_delete_rows_or_columns", lambda *a, **k: "columns")
    w.edit_delete_selection()
    assert "MW" not in w.headers
    assert w._table_model.rowCount() == 2


def test_delete_selection_both_can_choose_rows(qapp, monkeypatch):  # noqa: ARG001
    from PyQt5.QtWidgets import QMessageBox

    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    w = ChemicalTableApp()
    _seed_two_rows(w)
    w._selected_oids_override = frozenset({0})
    w._select_columns([3])
    monkeypatch.setattr(w, "_ask_delete_rows_or_columns", lambda *a, **k: "rows")
    w.edit_delete_selection()
    assert "MW" in w.headers
    assert w._table_model.rowCount() == 1
    assert w._table_model.cell_text(0, 0) == "1"


def test_chemistry_tool_structure_sources_smoke(qapp):  # noqa: ARG001
    w = ChemicalTableApp()
    _seed_two_rows(w)

    sources = w.chemistry_tool_structure_sources()
    assert sources[0] == "Structure"
    assert "SMILES" in sources
    assert "MW" not in sources
    assert w._canonical_smiles_header_for_updates() == "SMILES"


def test_structure_header_menu_offers_duplicate_not_rename(qapp):  # noqa: ARG001
    w = ChemicalTableApp()
    _seed_two_rows(w)
    menu = w._create_header_context_menu(1)
    assert menu is not None
    names = [a.objectName() for a in menu.actions()]
    assert "header_duplicate" in names
    assert "header_rename" not in names
    assert "header_delete" not in names
    select_menu = next(a.menu() for a in menu.actions() if a.text() == "Select")
    select_names = [a.objectName() for a in select_menu.actions() if a.objectName()]
    assert "header_select_all" in select_names
    assert "header_select_all_visible" not in select_names
    assert "header_select_first_occurrence" in select_names


def test_header_select_all_uses_visible_rows_only(qapp):  # noqa: ARG001
    from molmanager.ui.widgets import FilterCard

    w = ChemicalTableApp()
    _seed_two_rows(w)
    w.calculate_global_bounds()
    card = FilterCard(list(w.global_bounds.keys()), w, initial_property="MW")
    card.restore_state("MW", 40.0, 50.0)
    w.filters = [card]
    w._apply_filters_impl_sync(None)
    assert w._visible_oids_set() == frozenset({0})

    w._select_all_rows()
    qapp.processEvents()
    assert w._selected_oids_set() == {0}
    w.close()


def test_plot_clear_selection_drops_header_select_highlight(qapp):  # noqa: ARG001
    from molmanager.ui.plot_table_sync import clear_table_selection_from_plot

    w = ChemicalTableApp()
    _seed_two_rows(w)
    w._select_first_occurrence_per_distinct_structure()
    qapp.processEvents()
    assert w._selected_oids_set() == {0, 1}

    w._selected_oids_override = frozenset({0, 1})
    w._table_model.set_highlighted_oids(frozenset({0, 1}))
    sm = w.table.selectionModel()
    if sm is not None:
        sm.clearSelection()

    clear_table_selection_from_plot(w)
    assert w._selected_oids_override is None
    assert w._table_model.highlighted_oids() is None
    assert w._selected_oids_set() == set()
    assert sm is None or not sm.hasSelection()
    w.close()


def test_duplicate_structure_column_is_chemistry_source(qapp):  # noqa: ARG001
    from molmanager.display_constants import structure_column_minimum_width
    from molmanager.ui.compound_table_model import CompoundTableModel
    from molmanager.ui.main_window.table_undo_commands import UndoDuplicateColumnCommand

    w = ChemicalTableApp()
    _seed_two_rows(w)
    struct_w = structure_column_minimum_width() + 40
    w.table.setColumnWidth(CompoundTableModel.STRUCTURE_COL, struct_w)
    w._undo_stack.push(UndoDuplicateColumnCommand(w, 1, "Structure"))
    assert "Structure (Copy)" in w.headers
    assert w._table_model.is_pixmap_data_column("Structure (Copy)")
    assert w._table_model.backing_value_for_row_header(0, "Structure (Copy)") == "CCO"
    assert w._table_model.backing_value_for_row_header(1, "Structure (Copy)") == "CC"
    assert "Structure (Copy)" in w.chemistry_tool_structure_sources()
    copy_col = w.headers.index("Structure (Copy)")
    assert w.table.columnWidth(copy_col) == w.table.columnWidth(CompoundTableModel.STRUCTURE_COL)
    assert w.table.columnWidth(copy_col) == struct_w
    assert w._undo_stack.canUndo()
    w._undo_stack.undo()
    assert "Structure (Copy)" not in w.headers


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


def test_status_memory_tracker_starts_before_window_shown(qapp, monkeypatch):  # noqa: ARG001
    """Polling must start during __init__; isVisible() is False until show()."""
    monkeypatch.setattr("molmanager.ui.theme.load_status_bar_visible", lambda: True)
    monkeypatch.setattr("molmanager.ui.gui_settings_mixin.load_status_bar_visible", lambda: True)
    w = ChemicalTableApp()
    assert not w.isVisible()
    assert not w._status_host.isHidden()
    assert w._memory_status_timer.isActive()
    assert w._memory_status_label.text().startswith("Mem: ")


def test_status_memory_tracker_stops_when_status_bar_hidden(qapp, monkeypatch):  # noqa: ARG001
    monkeypatch.setattr("molmanager.ui.theme.load_status_bar_visible", lambda: True)
    monkeypatch.setattr("molmanager.ui.gui_settings_mixin.load_status_bar_visible", lambda: True)
    w = ChemicalTableApp()
    w._apply_status_bar_visible(False, persist=False)
    assert w._status_host.isHidden()
    assert not w._memory_status_timer.isActive()
    w._apply_status_bar_visible(True, persist=False)
    assert w._memory_status_timer.isActive()
    assert w._memory_status_label.text().startswith("Mem: ")


def test_pka_prediction_writes_pi_only_when_requested(qapp):  # noqa: ARG001
    w = ChemicalTableApp()
    _seed_two_rows(w)
    w._on_pka_prediction_finished([(0, "4.76", "N/A")], False)
    assert "pKa" in w.headers
    assert "pI" not in w.headers
    assert w._table_model.value_for_header(0, "pKa") == "4.76"
    w._on_pka_prediction_finished([(0, "4.76", "5.97")], True)
    assert "pI" in w.headers
    assert w._table_model.value_for_header(0, "pI") == "5.97"
