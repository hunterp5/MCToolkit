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

"""Tests for multi-pane workspace layout presets and docking into panes."""

from __future__ import annotations

import pytest

pytest.importorskip("PyQt5.QtWidgets")

from PyQt5.QtWidgets import QApplication, QLabel, QWidget

from molmanager.ui.main_window.workspace_layout import (
    DEFAULT_LAYOUT_ID,
    LAYOUT_QUADRANTS,
    LAYOUT_TABLE_GRID,
    LAYOUT_TABLE_ONLY,
    LAYOUT_TABLE_SIDE,
    LAYOUT_TABLE_SINGLE,
    LAYOUT_TABLE_STACK,
    PlotPane,
    WorkspaceLayoutManager,
)


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _manager(qapp) -> WorkspaceLayoutManager:
    table = QWidget()
    mgr = WorkspaceLayoutManager(table)
    mgr.apply_layout(LAYOUT_TABLE_STACK, preserve_plots=False)
    return mgr


def test_default_layout_is_table_only(qapp):
    table = QWidget()
    mgr = WorkspaceLayoutManager(table)
    assert mgr.layout_id == DEFAULT_LAYOUT_ID == LAYOUT_TABLE_ONLY
    assert mgr.plot_panes() == []


def test_apply_layout_pane_counts(qapp):
    mgr = _manager(qapp)
    mgr.apply_layout(LAYOUT_TABLE_ONLY, preserve_plots=False)
    assert len(mgr.plot_panes()) == 0
    mgr.apply_layout(LAYOUT_TABLE_SINGLE, preserve_plots=False)
    assert len(mgr.plot_panes()) == 1
    mgr.apply_layout(LAYOUT_TABLE_SIDE, preserve_plots=False)
    assert len(mgr.plot_panes()) == 2
    mgr.apply_layout(LAYOUT_QUADRANTS, preserve_plots=False)
    assert len(mgr.plot_panes()) == 3
    mgr.apply_layout(LAYOUT_TABLE_GRID, preserve_plots=False)
    assert len(mgr.plot_panes()) == 5
    mgr.apply_layout(LAYOUT_TABLE_STACK, preserve_plots=False)
    assert len(mgr.plot_panes()) == 2


def test_table_only_releases_all_plots(qapp):
    mgr = _manager(qapp)
    w0 = QLabel("a")
    w1 = QLabel("b")
    mgr.dock_into_pane(mgr.plot_panes()[0], w0)
    mgr.dock_into_pane(mgr.plot_panes()[1], w1)
    extras = mgr.apply_layout(LAYOUT_TABLE_ONLY, preserve_plots=True)
    assert mgr.layout_id == LAYOUT_TABLE_ONLY
    assert mgr.plot_panes() == []
    assert set(extras) == {w0, w1}
    assert mgr.preferred_pane() is None


def test_dock_into_pane_and_release(qapp):
    mgr = _manager(qapp)
    pane = mgr.plot_panes()[0]
    widget = QLabel("plot")
    prev = mgr.dock_into_pane(pane, widget)
    assert prev is None
    assert pane.plot_widget() is widget
    assert not pane.is_empty()
    assert mgr.pane_for_widget(widget) is pane
    assert list(mgr.iter_docked_widgets()) == [widget]
    assert mgr.release_widget(widget) is True
    assert pane.is_empty()


def test_apply_layout_preserves_plots_and_returns_extras(qapp):
    mgr = _manager(qapp)
    w0 = QLabel("a")
    w1 = QLabel("b")
    w2 = QLabel("c")
    mgr.dock_into_pane(mgr.plot_panes()[0], w0)
    mgr.dock_into_pane(mgr.plot_panes()[1], w1)
    # Stack has 2 panes; add a third logically by switching to single after 3 docks on stack
    # First expand to side (2), then we only have 2. Use stack with 2, switch to single → 1 extra.
    extras = mgr.apply_layout(LAYOUT_TABLE_SINGLE, preserve_plots=True)
    assert len(mgr.plot_panes()) == 1
    assert mgr.plot_panes()[0].plot_widget() is w0
    assert extras == [w1]
    # Re-dock leftover and another, then go to single again from stack with 2
    mgr.apply_layout(LAYOUT_TABLE_STACK, preserve_plots=True)
    assert len(mgr.plot_panes()) == 2
    mgr.dock_into_pane(mgr.plot_panes()[0], w0)
    mgr.dock_into_pane(mgr.plot_panes()[1], w1)
    # Can't fit w2 on stack; simulate three kept by manually calling with three
    # via temporary side layout then adding third through apply from a custom keep list:
    mgr.dock_into_pane(mgr.plot_panes()[0], w2)
    # Now panes hold w2 and w1; apply single keeps first only
    extras2 = mgr.apply_layout(LAYOUT_TABLE_SINGLE, preserve_plots=True)
    assert mgr.plot_panes()[0].plot_widget() is w2
    assert w1 in extras2


def test_splitter_size_roundtrip(qapp):
    mgr = _manager(qapp)
    payload = mgr.collect_splitter_sizes()
    assert payload["layout_id"] == LAYOUT_TABLE_STACK
    assert "sizes" in payload
    assert "preferred_pane_id" in payload
    mgr.apply_layout(LAYOUT_TABLE_SIDE, preserve_plots=False)
    mgr.restore_splitter_sizes(payload)  # different layout; sizes keys may not match count
    payload2 = mgr.collect_splitter_sizes()
    mgr.restore_splitter_sizes(payload2)
    assert mgr.collect_splitter_sizes()["layout_id"] == LAYOUT_TABLE_SIDE


def test_preferred_pane_tracks_activation(qapp):
    mgr = _manager(qapp)
    p0, p1 = mgr.plot_panes()
    mgr.set_preferred_pane(p1)
    assert mgr.preferred_pane() is p1
    mgr.dock_into_pane(p0, QLabel("x"))
    assert mgr.preferred_pane() is p0


def test_dock_appends_and_paginates_in_same_pane(qapp):
    mgr = _manager(qapp)
    pane = mgr.plot_panes()[0]
    w0 = QLabel("first")
    w0._window_title = "Alpha"
    w1 = QLabel("second")
    w1._window_title = "Beta"
    mgr.dock_into_pane(pane, w0)
    mgr.dock_into_pane(pane, w1)
    assert pane.plot_widgets() == [w0, w1]
    assert pane.plot_widget() is w1
    assert pane.page_count() == 2
    assert pane.page_index() == 1
    assert not pane._pager.isHidden()
    assert "2 / 2" in pane._page_label.text()
    assert pane.display_title() == "Beta"
    pane.show_previous_page()
    assert pane.plot_widget() is w0
    assert pane.page_index() == 0
    pane.show_next_page()
    assert pane.plot_widget() is w1
    assert mgr.pane_for_widget(w0) is pane
    assert list(mgr.iter_docked_widgets()) == [w0, w1]


def test_release_one_page_keeps_the_other(qapp):
    mgr = _manager(qapp)
    pane = mgr.plot_panes()[0]
    w0 = QLabel("a")
    w1 = QLabel("b")
    mgr.dock_into_pane(pane, w0)
    mgr.dock_into_pane(pane, w1)
    assert mgr.release_widget(w1) is True
    assert pane.plot_widget() is w0
    assert pane.page_count() == 1
    assert pane.plot_widgets() == [w0]
    assert not pane.is_empty()


def test_move_widget_between_panes_keeps_other_pages(qapp):
    mgr = _manager(qapp)
    p0, p1 = mgr.plot_panes()
    a = QLabel("a")
    b = QLabel("b")
    c = QLabel("c")
    mgr.dock_into_pane(p0, a)
    mgr.dock_into_pane(p0, b)
    mgr.dock_into_pane(p1, c)
    mgr.dock_into_pane(p1, b)
    assert p0.plot_widgets() == [a]
    assert p1.plot_widgets() == [c, b]
    assert p1.plot_widget() is b


def test_plot_pane_has_close_button(qapp):
    del qapp
    pane = PlotPane("pane_test")
    assert pane._close_btn.text() == "×"


def test_remove_pane_reduces_pane_count(qapp):
    mgr = _manager(qapp)
    assert len(mgr.plot_panes()) == 2
    p1 = mgr.plot_panes()[1]
    assert mgr.remove_pane(p1) is True
    assert len(mgr.plot_panes()) == 1
    assert p1 not in mgr.plot_panes()


def test_remove_last_pane_switches_to_table_only(qapp):
    mgr = _manager(qapp)
    mgr.apply_layout(LAYOUT_TABLE_SINGLE, preserve_plots=False)
    assert len(mgr.plot_panes()) == 1
    p0 = mgr.plot_panes()[0]
    assert mgr.remove_pane(p0) is True
    assert mgr.layout_id == LAYOUT_TABLE_ONLY
    assert mgr.plot_panes() == []


def test_plot_pane_refresh_theme_reapplies_selection_outline(qapp):
    del qapp
    pane = PlotPane("pane_test")
    pane.set_active(True)
    assert "palette(highlight)" in pane.styleSheet()
    pane.set_active(False)
    assert "palette(mid)" in pane.styleSheet()
    pane.set_active(True)
    pane.refresh_theme()
    assert pane._active is True
    assert "palette(highlight)" in pane.styleSheet()


def test_workspace_layout_refresh_theme_preserves_preferred_pane(qapp):
    mgr = _manager(qapp)
    p0, p1 = mgr.plot_panes()
    mgr.set_preferred_pane(p1)
    mgr.refresh_theme()
    assert p1._active is True
    assert p0._active is False


def test_apply_layout_preserves_pane_stacks(qapp):
    mgr = _manager(qapp)
    p0, p1 = mgr.plot_panes()
    a = QLabel("a")
    b = QLabel("b")
    c = QLabel("c")
    mgr.dock_into_pane(p0, a)
    mgr.dock_into_pane(p0, b)
    mgr.dock_into_pane(p1, c)
    extras = mgr.apply_layout(LAYOUT_TABLE_STACK, preserve_plots=True)
    assert extras == []
    panes = mgr.plot_panes()
    assert panes[0].plot_widgets() == [a, b]
    assert panes[0].plot_widget() is b
    assert panes[1].plot_widgets() == [c]


def test_dock_fits_wide_widget_to_existing_splitter_sizes(qapp):
    from PyQt5.QtWidgets import QLayout, QVBoxLayout

    from molmanager.ui.dockable_plot import embed_in_plot_pane, unembed_from_plot_pane

    host = QWidget()
    ly = QVBoxLayout(host)
    ly.setSizeConstraint(QLayout.SetMinimumSize)
    ly.addWidget(QLabel("wide"))
    host.setMinimumWidth(900)
    embed_in_plot_pane(host)
    assert host.minimumWidth() == 0
    assert ly.sizeConstraint() == QLayout.SetDefaultConstraint
    unembed_from_plot_pane(host)
    assert host.minimumWidth() == 900
    assert ly.sizeConstraint() == QLayout.SetMinimumSize

    mgr = _manager(qapp)
    outer = mgr._splitters[0]
    outer.setSizes([900, 320])
    before = [int(s) for s in outer.sizes()]
    widget = QLabel("wide")
    widget.setMinimumWidth(1800)
    widget.setMinimumHeight(900)
    mgr.dock_into_pane(mgr.plot_panes()[0], widget)
    assert [int(s) for s in outer.sizes()] == before
    assert widget.minimumWidth() == 0
    assert mgr.release_widget(widget) is True
    assert widget.minimumWidth() == 1800
