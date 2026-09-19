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

"""Shared table ↔ Plotly selection helpers (Plotter and PlotlyInteractiveView)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt5.QtCore import QItemSelectionModel, QTimer
from PyQt5.QtWidgets import QAbstractItemView

from .table_selection import item_selection_for_view_rows

if TYPE_CHECKING:
    from .main_window import ChemistryWorkspaceWindow

# Coalesce rapid plot→table updates (lasso echo / additive clicks).
_PLOT_TABLE_SELECT_DEBOUNCE_MS = 60


def visible_oids_for_plot(app: ChemistryWorkspaceWindow | None) -> frozenset[int] | None:
    """OIDs currently shown by table filters. ``None`` means every row is visible."""
    if app is None:
        return None
    fn = getattr(app, "_visible_oids_set", None)
    if not callable(fn):
        return None
    oids = fn()
    if oids is None:
        return None
    return frozenset(int(x) for x in oids)


def selection_visual_push_key(indices: set[int] | frozenset[int]) -> tuple[int, int]:
    """Cheap dedupe key for plot selection restyles (avoids sorting large index sets)."""
    if not indices:
        return (0, 0)
    return (len(indices), hash(frozenset(indices)))


def run_javascript_apply_figure(page, payload_json: str) -> None:
    """Push a Plotly figure payload into the shell without double-encoding the JSON string."""
    # ``payload_json`` is already serialized; embed as a JS value (object or parseable).
    page.runJavaScript(f"window.molmanagerApply({payload_json});")


def run_javascript_set_selection(
    page, point_indices: list[int] | set[int] | frozenset[int]
) -> None:
    """Push selection indices as a JS array (``parseSelectionIndices`` accepts arrays)."""
    import json

    page.runJavaScript(f"window.molmanagerSetSelection({json.dumps(list(point_indices))});")


def selected_oids_for_plot(parent_app: ChemistryWorkspaceWindow) -> set[int]:
    """
    OIDs that should drive plot highlighting — matches what the table shows as selected.

    Includes Qt selection, large-selection override, and model-level highlighted OIDs.
    Reuses a short-lived fan-out cache when the main window is syncing many plots.
    """
    cached = getattr(parent_app, "_cached_plot_selected_oids", None)
    if cached is not None:
        return set(cached)
    override = getattr(parent_app, "_selected_oids_override", None)
    if override:
        return {int(x) for x in override}
    oids: set[int] = set()
    model = parent_app._table_model
    for r in parent_app._selected_logical_rows():
        try:
            oids.add(int(model.row_oid(r)))
        except (IndexError, ValueError, TypeError):
            continue
    highlighted = model.highlighted_oids()
    if highlighted:
        oids |= {int(x) for x in highlighted}
    return oids


def build_oid_point_index(
    plotted_oids: list[int],
    partner_oids: list[int] | None = None,
) -> dict[int, list[int]]:
    """Map OID → point indices (includes optional pair-partner OIDs for the same index)."""
    index: dict[int, list[int]] = {}
    for i, oid in enumerate(plotted_oids):
        try:
            key = int(oid)
        except (TypeError, ValueError):
            continue
        index.setdefault(key, []).append(i)
    if partner_oids:
        for i, oid in enumerate(partner_oids):
            if i >= len(plotted_oids):
                break
            try:
                key = int(oid)
            except (TypeError, ValueError):
                continue
            bucket = index.setdefault(key, [])
            if i not in bucket:
                bucket.append(i)
    return index


def point_indices_for_oids(
    plotted_oids: list[int],
    selected_oids: set[int] | frozenset[int],
    *,
    oid_index: dict[int, list[int]] | None = None,
) -> set[int]:
    """Map table OIDs to scatter point indices for the current plot."""
    if not selected_oids:
        return set()
    if oid_index is not None:
        out: set[int] = set()
        for oid in selected_oids:
            try:
                key = int(oid)
            except (TypeError, ValueError):
                continue
            idxs = oid_index.get(key)
            if idxs:
                out.update(idxs)
        return out
    if not plotted_oids:
        return set()
    sel = selected_oids if isinstance(selected_oids, frozenset) else frozenset(selected_oids)
    return {i for i, oid in enumerate(plotted_oids) if int(oid) in sel}


def source_rows_for_point_indices(
    parent_app: ChemistryWorkspaceWindow,
    plotted_oids: list[int],
    point_indices: list[int],
    *,
    partner_oids: list[int] | None = None,
) -> list[int]:
    rows: list[int] = []
    n = len(plotted_oids)
    for idx in point_indices:
        if idx < 0 or idx >= n:
            continue
        for oid in (plotted_oids[idx],):
            row = parent_app.logical_row_for_oid(int(oid))
            if row >= 0:
                rows.append(int(row))
        if partner_oids is not None and idx < len(partner_oids):
            row = parent_app.logical_row_for_oid(int(partner_oids[idx]))
            if row >= 0:
                rows.append(int(row))
    return sorted(set(rows))


def _source_rows_already_selected(parent_app: ChemistryWorkspaceWindow, source_rows: list[int]) -> bool:
    """True when the table already reflects this source-row selection."""
    uniq = sorted({int(r) for r in source_rows})
    override = getattr(parent_app, "_selected_oids_override", None)
    model = getattr(parent_app, "_table_model", None)
    if override is not None and model is not None:
        want: set[int] = set()
        for r in uniq:
            try:
                want.add(int(model.row_oid(r)))
            except (IndexError, ValueError, TypeError):
                continue
        return want == {int(x) for x in override}
    sm = parent_app.table.selectionModel()
    if sm is None:
        return False
    view_rows = parent_app._source_rows_to_view_rows(uniq)
    current_view = {ix.row() for ix in sm.selectedRows()}
    return current_view == set(view_rows)


def _apply_table_selection_now(
    parent_app: ChemistryWorkspaceWindow,
    source_rows: list[int],
    *,
    scroll: bool,
) -> None:
    """Select visible proxy rows for source-model row indices (plot lasso / click)."""
    if not source_rows:
        return
    uniq = sorted({int(r) for r in source_rows})
    if _source_rows_already_selected(parent_app, uniq):
        return

    # Large sets: use the app's chunked / OID-override path (keeps UI responsive).
    select_rows = getattr(parent_app, "select_table_rows", None)
    if callable(select_rows):
        select_rows(uniq)
        if scroll:
            _scroll_table_to_first_source_row(parent_app, uniq)
        return

    sm = parent_app.table.selectionModel()
    if sm is None:
        return
    view_model = parent_app.table.model()
    if view_model is None:
        return
    view_rows = parent_app._source_rows_to_view_rows(uniq)
    if not view_rows:
        return
    col_last = max(0, view_model.columnCount() - 1)
    selection = item_selection_for_view_rows(view_model, view_rows, last_col=col_last)
    if selection.isEmpty():
        return
    table = parent_app.table
    was_programmatic = bool(getattr(parent_app, "_in_programmatic_table_selection", False))
    parent_app._in_programmatic_table_selection = True
    table.setUpdatesEnabled(False)
    try:
        sm.select(selection, QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows)
        anchor_col = 1 if col_last > 1 else 0
        idx = view_model.index(view_rows[0], anchor_col)
        sm.setCurrentIndex(idx, QItemSelectionModel.NoUpdate)
        if scroll and idx.isValid():
            table.scrollTo(idx, QAbstractItemView.PositionAtCenter)
    finally:
        table.setUpdatesEnabled(True)
        parent_app._in_programmatic_table_selection = was_programmatic
    table.viewport().update()


def _scroll_table_to_first_source_row(parent_app: ChemistryWorkspaceWindow, source_rows: list[int]) -> None:
    if not source_rows:
        return
    view_rows = parent_app._source_rows_to_view_rows(source_rows[:1])
    if not view_rows:
        return
    view_model = parent_app.table.model()
    if view_model is None:
        return
    col_last = max(0, view_model.columnCount() - 1)
    anchor_col = 1 if col_last > 1 else 0
    idx = view_model.index(view_rows[0], anchor_col)
    if idx.isValid():
        parent_app.table.scrollTo(idx, QAbstractItemView.PositionAtCenter)


def apply_table_selection_for_source_rows(
    parent_app: ChemistryWorkspaceWindow,
    source_rows: list[int],
    *,
    scroll: bool = True,
    debounce: bool = False,
) -> None:
    """Select visible proxy rows for source-model row indices (plot lasso / click).

    When ``scroll`` is True (user-driven plot select), reveal the first selected row.
    Re-sync paths should pass ``scroll=False`` so table scrolling is not fought.

    When ``debounce`` is True, coalesce rapid updates (large lassos / echo events).
    """
    if not source_rows:
        return
    uniq = sorted({int(r) for r in source_rows})
    if not debounce or len(uniq) <= 1:
        _apply_table_selection_now(parent_app, uniq, scroll=scroll)
        return

    parent_app._plot_table_select_pending = (uniq, scroll)  # type: ignore[attr-defined]
    timer = getattr(parent_app, "_plot_table_select_timer", None)
    if timer is None:
        timer = QTimer(parent_app)
        timer.setSingleShot(True)

        def _flush() -> None:
            pending = getattr(parent_app, "_plot_table_select_pending", None)
            parent_app._plot_table_select_pending = None  # type: ignore[attr-defined]
            if not pending:
                return
            rows, do_scroll = pending
            _apply_table_selection_now(parent_app, rows, scroll=bool(do_scroll))

        timer.timeout.connect(_flush)
        parent_app._plot_table_select_timer = timer  # type: ignore[attr-defined]
    timer.start(_PLOT_TABLE_SELECT_DEBOUNCE_MS)


def clear_table_selection_from_plot(parent_app: ChemistryWorkspaceWindow) -> None:
    """Clear Qt, logical, and highlight selection when a plot deselects."""
    timer = getattr(parent_app, "_plot_table_select_timer", None)
    if timer is not None:
        timer.stop()
    parent_app._plot_table_select_pending = None  # type: ignore[attr-defined]
    clear_fn = getattr(parent_app, "clear_table_selection", None)
    if callable(clear_fn):
        clear_fn()
        return
    parent_app._selected_oids_override = None
    model = getattr(parent_app, "_table_model", None)
    if model is not None and callable(getattr(model, "set_highlighted_oids", None)):
        model.set_highlighted_oids(None)
    table = parent_app.table
    table.clearSelection()
    table.viewport().update()
