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

"""Table row/column selection, visibility, and OID override helpers."""

from __future__ import annotations

from PySide6.QtCore import QEventLoop, QItemSelection, QItemSelectionModel, Qt, QTimer
from PySide6.QtWidgets import QAbstractItemView, QApplication
from ..chem.molecule_conversion import looks_like_mol_block, mol_to_canonical_smiles
from ..chem.structure_source_headers import is_tool_generated_structure_header
from ..platform_support.config import load_config
from ..services.table_selection import (
    cached_string_key,
    first_rows_for_distinct_keys,
    logical_rows_for_oids,
    oids_for_source_rows,
    oids_from_id_hidden_cells,
    rows_where,
    structure_row_is_empty,
)
from .plot_table_sync import selected_oids_for_plot
from .qt_widget_utils import qobject_is_deleted
from .table_selection import item_selection_for_view_rows, merge_sorted_row_indices

# Sentinel: visible source-row cache is empty (distinct from cached ``None`` = all rows visible).
_VISIBLE_SOURCE_ROWS_UNSET = object()


class TableSessionSelection:
    """Programmatic and user-driven table selection (including large OID overrides)."""

    def _select_column(self, col: int) -> None:
        self._app._column_selection_anchor = col
        self._select_columns([col], anchor_col=col)

    def _select_column_range(self, anchor_col: int, end_col: int) -> None:
        """Select all visible columns from ``anchor_col`` to ``end_col`` (inclusive)."""
        hh = self._app.table.horizontalHeader()
        vis_a = hh.visualIndex(int(anchor_col))
        vis_b = hh.visualIndex(int(end_col))
        if vis_a < 0 or vis_b < 0:
            self._select_columns([end_col], anchor_col=end_col)
            return
        lo, hi = (vis_a, vis_b) if vis_a <= vis_b else (vis_b, vis_a)
        cols: list[int] = []
        for vis in range(lo, hi + 1):
            logical = hh.logicalIndex(vis)
            if logical < 0 or logical >= len(self._app.headers):
                continue
            if self._app.headers[logical] == "ID_HIDDEN":
                continue
            cols.append(logical)
        self._select_columns(cols, anchor_col=end_col)

    def _select_columns(self, cols: list[int], *, anchor_col: int | None = None) -> None:
        view_model = self._app.table.model()
        if view_model is None:
            self._report_table_selection_status(0)
            return
        n = view_model.rowCount()
        if n <= 0:
            self._report_table_selection_status(0)
            return
        unique_cols: list[int] = []
        seen: set[int] = set()
        for col in cols:
            c = int(col)
            if c < 0 or c >= len(self._app.headers) or c in seen:
                continue
            if self._app.headers[c] == "ID_HIDDEN":
                continue
            seen.add(c)
            unique_cols.append(c)
        if not unique_cols:
            self._report_table_selection_status(0)
            return
        prev_behavior = self._app.table.selectionBehavior()
        was_auto_scroll = bool(self._app.table.hasAutoScroll())
        self._app.table.setSelectionBehavior(QAbstractItemView.SelectColumns)
        self._app.table.setAutoScroll(False)
        sel = QItemSelection()
        for col in unique_cols:
            top = view_model.index(0, col)
            bottom = view_model.index(n - 1, col)
            sel.select(top, bottom)
        sm = self._app.table.selectionModel()
        scroll_pos = self._table_scroll_pos()
        current = sm.currentIndex() if sm is not None else None
        was_programmatic = bool(getattr(self._app, "_in_programmatic_table_selection", False))
        self._app._in_programmatic_table_selection = True
        try:
            if sm is not None:
                sm.select(sel, QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Columns)
                if current is not None and current.isValid():
                    keep = view_model.index(current.row(), unique_cols[0])
                    if keep.isValid():
                        sm.setCurrentIndex(keep, QItemSelectionModel.NoUpdate)
        finally:
            self._app._in_programmatic_table_selection = was_programmatic
            self._app.table.setSelectionBehavior(prev_behavior)
            self._app.table.setAutoScroll(was_auto_scroll)
            self._restore_table_scroll_pos(scroll_pos)
        focus_col = (
            int(anchor_col)
            if anchor_col is not None and int(anchor_col) in seen
            else unique_cols[-1]
        )
        self._refresh_table_selection_visual(
            None,
            anchor_col=focus_col,
            preserve_scroll=True,
            scroll_pos=scroll_pos,
        )
        n_cols = len(unique_cols)
        extra = f"{n_cols} column{'s' if n_cols != 1 else ''}."
        self._report_table_selection_status(n, extra=extra)
        self._restore_table_scroll_pos(scroll_pos)

    def _table_scroll_pos(self) -> tuple[int, int]:
        vbar = self._app.table.verticalScrollBar()
        hbar = self._app.table.horizontalScrollBar()
        return (
            int(vbar.value()) if vbar is not None else 0,
            int(hbar.value()) if hbar is not None else 0,
        )

    def _restore_table_scroll_pos(self, pos: tuple[int, int]) -> None:
        vbar = self._app.table.verticalScrollBar()
        hbar = self._app.table.horizontalScrollBar()
        if vbar is not None:
            vbar.setValue(int(pos[0]))
        if hbar is not None:
            hbar.setValue(int(pos[1]))

    def _refresh_table_selection_visual(
        self,
        anchor_rows: list[int] | None,
        anchor_col: int | None = None,
        *,
        preserve_scroll: bool = False,
        scroll_pos: tuple[int, int] | None = None,
    ) -> None:
        """
        Show selection highlight immediately after programmatic select.

        Deferred one event-loop tick so context-menu focus is released first; then
        anchor the current cell, scroll if needed, focus the table, and repaint.

        When ``anchor_col`` is given (e.g. column selection), the current cell and any
        auto-scroll target that column so the horizontal scroll position is preserved;
        otherwise it defaults to the Structure column for row-based selections.
        ``preserve_scroll`` keeps the current viewport (column header clicks).
        ``scroll_pos`` is the viewport to restore when ``preserve_scroll`` is set.
        """
        frozen = scroll_pos if preserve_scroll else None

        def _apply() -> None:
            # This runs a tick later, by which point the window may be gone: a test has ended, or
            # the cycle collector has freed it. Touching the table then reaches freed C++ memory
            # and takes the process down instead of raising.
            if qobject_is_deleted(self._app) or qobject_is_deleted(self._app.table):
                return
            try:
                if anchor_rows and not preserve_scroll:
                    first = min(anchor_rows)
                    ncol = self._app._table_model.columnCount()
                    if anchor_col is not None:
                        target_col = max(0, min(anchor_col, ncol - 1))
                    else:
                        target_col = 1 if ncol > 1 else 0
                    view_model = self._app.table.model()
                    proxy = getattr(self._app, "_filter_proxy_model", None)
                    if proxy is not None and view_model is proxy:
                        pidx = proxy.mapFromSource(self._app._table_model.index(first, 0))
                        if not pidx.isValid():
                            return
                        idx = view_model.index(pidx.row(), target_col)
                    else:
                        idx = self._app._table_model.index(first, target_col)
                    sm = self._app.table.selectionModel()
                    if sm is not None and idx.isValid():
                        sm.setCurrentIndex(idx, QItemSelectionModel.NoUpdate)
                        self._app.table.scrollTo(idx, QAbstractItemView.EnsureVisible)
            finally:
                if frozen is not None:
                    self._restore_table_scroll_pos(frozen)
                if not preserve_scroll:
                    self._app.table.setFocus(Qt.OtherFocusReason)
                self._app.table.viewport().update()

        QTimer.singleShot(0, _apply)

    def _set_selection_status(self, message: str, *, pump: bool = False) -> None:
        self._app.status_label.setText(message)
        if pump:
            QApplication.processEvents(QEventLoop.ExcludeUserInputEvents)

    def _report_table_selection_status(
        self, n_selected: int, *, extra: str = "", pump: bool = True
    ) -> None:
        total = self._app._table_model.rowCount()
        if total <= 0:
            self._set_selection_status("No rows in table.", pump=pump)
            return
        msg = f"Selected {n_selected:,} of {total:,} row(s)."
        if extra:
            msg = f"{msg} {extra}"
        self._set_selection_status(msg, pump=pump)

    def _cancel_chunked_table_selection(self) -> None:
        self._table_selection_job_gen = int(getattr(self, "_table_selection_job_gen", 0)) + 1
        self._table_selection_ctx = None

    def _maybe_status_before_large_select(self) -> None:
        total = self._app._table_model.rowCount()
        if total >= load_config().table_selection_oid_override_min:
            self._set_selection_status(f"Selecting… (0/{total:,} rows)", pump=True)

    def _use_filter_proxy_for_table(self) -> bool:
        proxy = getattr(self._app, "_filter_proxy_model", None)
        view_model = self._app.table.model()
        return proxy is not None and view_model is proxy

    def _is_source_row_visible(self, source_row: int) -> bool:
        """Proxy-aware check for whether a source-model row index is currently shown."""
        if self._use_filter_proxy_for_table():
            proxy = self._app._filter_proxy_model
            return proxy.mapFromSource(self._app._table_model.index(source_row, 0)).isValid()
        return not self._app.table.isRowHidden(source_row)

    def _visible_oids_set(self) -> frozenset[int] | None:
        """OIDs currently shown by table filters. ``None`` means every row is visible."""
        if self._use_filter_proxy_for_table():
            proxy = self._app._filter_proxy_model
            oids = proxy.visible_oids()
            if oids is None:
                return None
            src_n = self._app._table_model.rowCount()
            if src_n > 0 and len(oids) >= src_n:
                return None
            return oids
        n = self._app._table_model.rowCount()
        hidden = [r for r in range(n) if self._app.table.isRowHidden(r)]
        if not hidden:
            return None
        return frozenset(
            int(self._app._table_model.row_oid(r))
            for r in range(n)
            if not self._app.table.isRowHidden(r)
        )

    def _invalidate_visible_source_rows_cache(self) -> None:
        """Drop cached visible source-row indices (call when filter visibility changes)."""
        self._app._visible_source_rows_cache = _VISIBLE_SOURCE_ROWS_UNSET

    def _visible_source_row_indices(self) -> list[int] | None:
        """Source-model row indices for rows currently shown in the table view.

        Returns ``None`` when every source row is visible (no list allocation).
        Results are cached until :meth:`_invalidate_visible_source_rows_cache` so
        multi-plot replot (including debounced Plotter rebuilds) does not rematerialize.
        """
        cache = self._app._visible_source_rows_cache
        if cache is not _VISIBLE_SOURCE_ROWS_UNSET:
            return cache  # type: ignore[return-value]
        oids = self._visible_oids_set()
        if oids is None:
            self._app._visible_source_rows_cache = None
            return None
        if self._use_filter_proxy_for_table():
            proxy = self._app._filter_proxy_model
            rows = proxy.visible_source_rows()
            if rows is not None:
                self._app._visible_source_rows_cache = rows
                return rows
        n = self._app._table_model.rowCount()
        out = [r for r in range(n) if int(self._app._table_model.row_oid(r)) in oids]
        self._app._visible_source_rows_cache = out
        return out

    def _iter_visible_source_row_indices(self):
        """Iterate visible source rows without building a full index list when possible."""
        indices = self._visible_source_row_indices()
        if indices is None:
            yield from range(self._app._table_model.rowCount())
        else:
            yield from indices

    def _repaint_table_selection_viewport(self) -> None:
        vp = self._app.table.viewport()
        if vp is not None:
            vp.update()

    def _sync_table_selection_highlight(self) -> None:
        """Paint row highlights from ``_selected_oids_override`` without a giant QItemSelection."""
        override = getattr(self._app, "_selected_oids_override", None)
        self._app._table_model.set_highlighted_oids(override)
        self._repaint_table_selection_viewport()

    def _schedule_plot_sync_after_programmatic_selection(self) -> None:
        """Sync plot highlights after search / analysis / other programmatic table selection."""
        schedule = getattr(self._app, "_schedule_sync_active_plots_from_table_selection", None)
        if callable(schedule):
            schedule()

    def _on_user_table_selection_changed(self, *_args) -> None:
        if getattr(self._app, "_in_programmatic_table_selection", False):
            return
        self._app._selected_oids_override = None
        self._sync_table_selection_highlight()
        self._schedule_plot_sync_after_programmatic_selection()
        sync_dock = getattr(self._app, "_sync_dock_complex_viewer", None)
        if callable(sync_dock):
            sync_dock()

    def select_table_rows(
        self,
        rows: list[int],
        *,
        clear_oid_override: bool = True,
        extra_status: str = "",
    ) -> int:
        """Replace the selection with the given source-model row indices (skips invalid indices)."""
        self._cancel_chunked_table_selection()
        return self._apply_table_row_selection(
            rows, clear_oid_override=clear_oid_override, extra_status=extra_status
        )

    def select_table_oids(
        self,
        oids: list[int] | set[int] | frozenset[int],
        *,
        clear_oid_override: bool = True,
        extra_status: str = "",
    ) -> int:
        """Select rows for the given OIDs; uses chunked selection when the set is large."""
        if not oids:
            self._report_table_selection_status(0, extra=extra_status)
            return 0
        source_rows: list[int] = []
        for oid in oids:
            try:
                row = self.logical_row_for_oid(int(oid))
            except (TypeError, ValueError):
                continue
            if row >= 0:
                source_rows.append(int(row))
        if not source_rows:
            self._report_table_selection_status(0, extra=extra_status)
            return 0
        return self.select_table_rows(
            source_rows,
            clear_oid_override=clear_oid_override,
            extra_status=extra_status,
        )

    def _source_rows_to_view_rows(self, source_rows: list[int]) -> list[int]:
        view_model = self._app.table.model()
        proxy = getattr(self._app, "_filter_proxy_model", None)
        use_proxy = proxy is not None and view_model is proxy
        if not use_proxy:
            return list(source_rows)
        view_rows: list[int] = []
        for src_r in source_rows:
            pidx = proxy.mapFromSource(self._app._table_model.index(src_r, 0))
            if pidx.isValid():
                view_rows.append(int(pidx.row()))
        return view_rows

    def _oids_for_source_rows(self, source_rows: list[int]) -> frozenset[int]:
        return oids_for_source_rows(source_rows, row_oid=self._app._table_model.row_oid)

    def _apply_qt_view_row_selection(
        self,
        source_rows: list[int],
        view_rows: list[int],
        *,
        clear_oid_override: bool,
        mode_flags=None,
    ) -> int:
        if clear_oid_override:
            self._app._selected_oids_override = None
        sm = self._app.table.selectionModel()
        view_model = self._app.table.model()
        if sm is None or view_model is None or not view_rows:
            return 0
        last_col = max(0, view_model.columnCount() - 1)
        flags = mode_flags or (QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows)
        prev_mode = self._app.table.selectionMode()
        prev_behavior = self._app.table.selectionBehavior()
        self._app.table.setSelectionMode(QAbstractItemView.MultiSelection)
        self._app.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._app._in_programmatic_table_selection = True
        try:
            if flags & QItemSelectionModel.Clear:
                sm.clearSelection()
            selection = item_selection_for_view_rows(view_model, view_rows, last_col=last_col)
            if not selection.isEmpty():
                sm.select(selection, flags)
        finally:
            self._app._in_programmatic_table_selection = False
        self._app.table.setSelectionMode(prev_mode)
        self._app.table.setSelectionBehavior(prev_behavior)
        self._sync_table_selection_highlight()
        self._refresh_table_selection_visual(source_rows)
        self._schedule_plot_sync_after_programmatic_selection()
        sync_dock = getattr(self._app, "_sync_dock_complex_viewer", None)
        if callable(sync_dock):
            sync_dock()
        return len(source_rows)

    def _finish_oid_override_selection(
        self,
        source_rows: list[int],
        oids: frozenset[int],
        *,
        clear_oid_override: bool,
        extra_status: str = "",
    ) -> int:
        if clear_oid_override:
            self._app._selected_oids_override = None
        sm = self._app.table.selectionModel()
        self._app._in_programmatic_table_selection = True
        try:
            if sm is not None:
                sm.clearSelection()
            self._app._selected_oids_override = oids
        finally:
            self._app._in_programmatic_table_selection = False
        anchor = [source_rows[0]] if source_rows else None
        self._sync_table_selection_highlight()
        self._refresh_table_selection_visual(anchor)
        n = len(oids)
        self._report_table_selection_status(n, extra=extra_status, pump=True)
        self._schedule_plot_sync_after_programmatic_selection()
        return n

    def _start_chunked_oid_selection(
        self,
        source_rows: list[int],
        *,
        clear_oid_override: bool,
        extra_status: str = "",
    ) -> int:
        """Logical selection for large row sets (tools use OIDs; table is not fully highlighted)."""
        if clear_oid_override:
            self._app._selected_oids_override = None
        total = len(source_rows)
        if total <= 0:
            self._report_table_selection_status(0)
            return 0
        self._cancel_chunked_table_selection()
        self._table_selection_job_gen = int(getattr(self, "_table_selection_job_gen", 0)) + 1
        gen = self._table_selection_job_gen
        self._table_selection_ctx = {
            "gen": gen,
            "phase": "oids",
            "source_rows": source_rows,
            "clear_oid_override": clear_oid_override,
            "extra_status": extra_status,
            "idx": 0,
            "oids": set(),
            "chunk": max(2000, load_config().table_selection_chunk_rows),
        }
        self._set_selection_status(f"Selecting… (0/{total:,} rows)", pump=True)
        QTimer.singleShot(0, self._table_selection_chunk_step)
        return total

    def _start_chunked_qt_selection(
        self,
        source_rows: list[int],
        view_rows: list[int],
        *,
        clear_oid_override: bool,
    ) -> int:
        """Apply Qt selection in chunks so the UI stays responsive."""
        if clear_oid_override:
            self._app._selected_oids_override = None
        view_model = self._app.table.model()
        if view_model is None:
            return 0
        last_col = max(0, view_model.columnCount() - 1)
        ranges = merge_sorted_row_indices(view_rows)
        total = len(source_rows)
        self._cancel_chunked_table_selection()
        self._table_selection_job_gen = int(getattr(self, "_table_selection_job_gen", 0)) + 1
        gen = self._table_selection_job_gen
        sm = self._app.table.selectionModel()
        prev_mode = self._app.table.selectionMode()
        prev_behavior = self._app.table.selectionBehavior()
        self._app.table.setSelectionMode(QAbstractItemView.MultiSelection)
        self._app.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        if sm is not None:
            sm.clearSelection()
        self._table_selection_ctx = {
            "gen": gen,
            "phase": "qt",
            "source_rows": source_rows,
            "view_model": view_model,
            "last_col": last_col,
            "ranges": ranges,
            "range_idx": 0,
            "ranges_per_tick": 80,
            "clear_oid_override": clear_oid_override,
            "prev_mode": prev_mode,
            "prev_behavior": prev_behavior,
        }
        self._set_selection_status(f"Selecting… (0/{total:,} rows)", pump=True)
        QTimer.singleShot(0, self._table_selection_chunk_step)
        return total

    def _table_selection_chunk_step(self) -> None:
        ctx = getattr(self, "_table_selection_ctx", None)
        if not ctx or ctx.get("gen") != getattr(self, "_table_selection_job_gen", -1):
            return
        phase = ctx.get("phase")
        if phase == "oids":
            self._table_selection_chunk_step_oids(ctx)
        elif phase == "qt":
            self._table_selection_chunk_step_qt(ctx)

    def _table_selection_chunk_step_oids(self, ctx: dict) -> None:
        rows: list[int] = ctx["source_rows"]
        total = len(rows)
        idx = int(ctx["idx"])
        chunk = int(ctx["chunk"])
        end = min(idx + chunk, total)
        oids: set[int] = ctx["oids"]
        for j in range(idx, end):
            try:
                oids.add(int(self._app._table_model.row_oid(rows[j])))
            except (IndexError, ValueError, TypeError):
                continue
        ctx["idx"] = end
        self._app._table_model.set_highlighted_oids(frozenset(oids))
        self._repaint_table_selection_viewport()
        self._set_selection_status(f"Selecting… ({end:,}/{total:,} rows)")
        if end < total:
            QTimer.singleShot(0, self._table_selection_chunk_step)
            return
        self._table_selection_ctx = None
        self._finish_oid_override_selection(
            rows,
            frozenset(oids),
            clear_oid_override=bool(ctx.get("clear_oid_override", True)),
            extra_status=str(ctx.get("extra_status") or ""),
        )

    def _table_selection_chunk_step_qt(self, ctx: dict) -> None:
        sm = self._app.table.selectionModel()
        view_model = ctx["view_model"]
        last_col = int(ctx["last_col"])
        ranges: list[tuple[int, int]] = ctx["ranges"]
        ri = int(ctx["range_idx"])
        per_tick = int(ctx["ranges_per_tick"])
        source_rows: list[int] = ctx["source_rows"]
        total = len(source_rows)
        end_ri = min(ri + per_tick, len(ranges))
        selection = QItemSelection()
        for k in range(ri, end_ri):
            lo, hi = ranges[k]
            top = view_model.index(lo, 0)
            bottom = view_model.index(hi, last_col)
            if top.isValid() and bottom.isValid():
                selection.select(top, bottom)
        self._app._in_programmatic_table_selection = True
        try:
            if sm is not None and not selection.isEmpty():
                flags = QItemSelectionModel.Select | QItemSelectionModel.Rows
                if ri == 0:
                    flags |= QItemSelectionModel.Clear
                sm.select(selection, flags)
        finally:
            self._app._in_programmatic_table_selection = False
        done_rows = sum(hi - lo + 1 for lo, hi in ranges[:end_ri])
        ctx["range_idx"] = end_ri
        self._set_selection_status(f"Selecting… ({min(done_rows, total):,}/{total:,} rows)")
        if end_ri < len(ranges):
            QTimer.singleShot(0, self._table_selection_chunk_step)
            return
        self._app.table.setSelectionMode(ctx["prev_mode"])
        self._app.table.setSelectionBehavior(ctx["prev_behavior"])
        self._table_selection_ctx = None
        self._sync_table_selection_highlight()
        self._refresh_table_selection_visual(source_rows)
        self._report_table_selection_status(len(source_rows), pump=True)
        self._schedule_plot_sync_after_programmatic_selection()

    def _apply_table_row_selection(
        self,
        rows: list[int],
        *,
        clear_oid_override: bool = True,
        extra_status: str = "",
    ) -> int:
        n_rows = self._app._table_model.rowCount()
        if n_rows <= 0:
            if clear_oid_override:
                self._app._selected_oids_override = None
            self._report_table_selection_status(0)
            return 0
        uniq = sorted({int(r) for r in rows if 0 <= int(r) < n_rows})
        if not uniq:
            if clear_oid_override:
                self.clear_table_selection()
            else:
                n_override = len(self._app._selected_oids_override or ())
                self._report_table_selection_status(n_override)
            return 0
        cfg = load_config()
        oid_min = cfg.table_selection_oid_override_min
        chunk_thresh = cfg.table_selection_chunk_rows
        if len(uniq) >= oid_min:
            extra = str(extra_status or "")
            if len(uniq) < n_rows:
                hint = "(tools use full selection; hidden rows included via logical selection)"
                extra = f"{extra} {hint}".strip() if extra else hint
            self._start_chunked_oid_selection(
                uniq, clear_oid_override=clear_oid_override, extra_status=extra
            )
            return len(uniq)
        view_rows = self._source_rows_to_view_rows(uniq)
        if not view_rows:
            if not clear_oid_override and self._app._selected_oids_override:
                n_override = len(self._app._selected_oids_override)
                self._report_table_selection_status(n_override)
                return n_override
            self._report_table_selection_status(0)
            return 0
        if len(uniq) >= chunk_thresh:
            self._start_chunked_qt_selection(uniq, view_rows, clear_oid_override=clear_oid_override)
            return len(uniq)
        return self._apply_qt_view_row_selection(
            uniq, view_rows, clear_oid_override=clear_oid_override
        )

    def _select_all_visible_rows(self) -> None:
        """Select every row currently visible in the table (respects active filters)."""
        self._maybe_status_before_large_select()
        vis = self._visible_source_row_indices()
        if vis is None:
            n_rows = self._app._table_model.rowCount()
            cfg = load_config()
            if n_rows >= cfg.table_selection_oid_override_min:
                self._start_chunked_oid_selection(list(range(n_rows)), clear_oid_override=True)
                return
            self.select_table_rows(list(range(n_rows)))
            return
        self.select_table_rows(vis)

    def _select_all_rows(self) -> None:
        """Select every visible table row (same as Select All on a column header)."""
        self._select_all_visible_rows()

    def _cancel_pending_plot_table_select(self) -> None:
        timer = getattr(self._app, "_plot_table_select_timer", None)
        if timer is not None:
            timer.stop()
        self._app._plot_table_select_pending = None

    def clear_table_selection(self) -> None:
        """Clear Qt, logical, and highlight selection, and sync open plots."""
        self._cancel_pending_plot_table_select()
        self._cancel_chunked_table_selection()
        self._app._selected_oids_override = None
        sm = self._app.table.selectionModel()
        self._app._in_programmatic_table_selection = True
        try:
            if sm is not None:
                sm.clearSelection()
        finally:
            self._app._in_programmatic_table_selection = False
        self._sync_table_selection_highlight()
        self._report_table_selection_status(0)
        self._schedule_plot_sync_after_programmatic_selection()
        sync_dock = getattr(self._app, "_sync_dock_complex_viewer", None)
        if callable(sync_dock):
            sync_dock()

    def invert_table_selection(self) -> None:
        """Select every table row that is not currently selected (full table, including filtered-out rows)."""
        n_rows = self._app._table_model.rowCount()
        if n_rows <= 0:
            self.clear_table_selection()
            return
        selected_rows = set(self._selected_logical_rows())
        inverted = [r for r in range(n_rows) if r not in selected_rows]
        if not inverted:
            self.clear_table_selection()
            return
        if len(inverted) >= load_config().table_selection_oid_override_min:
            self._maybe_status_before_large_select()
        self.select_table_rows(inverted)

    def _select_first_occurrence_per_distinct_value(self, col: int) -> None:
        """Select the first visible row for each distinct non-empty cell text in this column."""
        self._maybe_status_before_large_select()
        to_sel = first_rows_for_distinct_keys(
            self._iter_visible_source_row_indices(),
            key_for_row=lambda r: (self._app._table_model.cell_text(r, col) or "").strip(),
        )
        self.select_table_rows(to_sel)

    def _select_empty_cells_in_column(self, col: int) -> None:
        """Select visible rows where this column is empty or whitespace-only."""
        self._maybe_status_before_large_select()
        to_sel = rows_where(
            self._iter_visible_source_row_indices(),
            predicate=lambda r: not (self._app._table_model.cell_text(r, col) or "").strip(),
        )
        self.select_table_rows(to_sel)

    def _structure_column_row_is_empty(self, row: int) -> bool:
        """True when the row has no chemical structure (fast text/mol store check)."""
        try:
            oid = self._app._table_model.row_oid(row)
        except (IndexError, ValueError, TypeError):
            return True
        smi_h = self._canonical_smiles_header_for_updates()
        smiles_text = ""
        if smi_h and smi_h in self._app.headers:
            ci = self._app.headers.index(smi_h)
            smiles_text = (self._app._table_model.cell_text(row, ci) or "").strip()
        ov = getattr(self._app, "_structure_field_override", None)
        ov_s = str(ov).strip() if isinstance(ov, str) else ""

        def _probe():
            for h in self._ordered_headers_for_molecule_lookup():
                if smi_h and h == smi_h:
                    continue
                ci = self._app.headers.index(h)
                raw = (self._app._table_model.cell_text(row, ci) or "").strip()
                yield h, raw

        return structure_row_is_empty(
            mol_present=self._app.mols.get(oid) is not None,
            smiles_text=smiles_text,
            probe_cells=_probe(),
            override_header=ov_s,
            is_smiles_named=self._is_smiles_named_header,
            header_looks_structural=self._header_looks_structural,
            is_tool_generated=is_tool_generated_structure_header,
            looks_like_mol_block=looks_like_mol_block,
        )

    def _select_empty_structure_cells(self) -> None:
        self._maybe_status_before_large_select()
        to_sel = rows_where(
            self._iter_visible_source_row_indices(),
            predicate=self._structure_column_row_is_empty,
        )
        self.select_table_rows(to_sel)

    def _structure_distinct_key_for_row(
        self, row: int, *, smiles_key_cache: dict[str, str] | None = None
    ) -> str:
        """Canonical structure key for Select → first occurrence on the Structure column."""
        try:
            oid = self._app._table_model.row_oid(row)
        except (IndexError, ValueError, TypeError):
            return ""
        mol = self._app.mols.get(oid)
        if mol is not None:
            try:
                raw = mol_to_canonical_smiles(mol)
            except Exception:
                raw = ""
            if raw:
                return self._canonical_structure_key_cached(raw, smiles_key_cache)
            return ""
        try:
            smi_col = self._app.headers.index("SMILES")
        except ValueError:
            return ""
        raw = (self._app._table_model.cell_text(row, smi_col) or "").strip()
        if not raw:
            return ""
        return self._canonical_structure_key_cached(raw, smiles_key_cache)

    def _canonical_structure_key_cached(self, smiles: str, cache: dict[str, str] | None) -> str:
        return cached_string_key(
            smiles,
            cache,
            key_fn=self._app.canonical_structure_key_from_smiles,
        )

    def _select_first_occurrence_per_distinct_structure(self) -> None:
        self._maybe_status_before_large_select()
        smiles_key_cache: dict[str, str] = {}
        to_sel = first_rows_for_distinct_keys(
            self._iter_visible_source_row_indices(),
            key_for_row=lambda r: self._structure_distinct_key_for_row(
                r, smiles_key_cache=smiles_key_cache
            ),
        )
        self.select_table_rows(to_sel)

    def _selected_logical_rows(self) -> list[int]:
        """Distinct source-model row indices from the current selection (any column)."""
        override = getattr(self._app, "_selected_oids_override", None)
        if override:
            return logical_rows_for_oids(
                override,
                logical_row_for_oid=self._app._table_model.logical_row_for_oid,
            )
        sm = self._app.table.selectionModel()
        if sm is None:
            return []
        view_model = self._app.table.model()
        proxy = getattr(self._app, "_filter_proxy_model", None)
        use_proxy = proxy is not None and view_model is proxy
        # selectedRows() is O(rows); selectedIndexes() is O(rows × columns) and freezes wide tables.
        view_rows = sorted({ix.row() for ix in sm.selectedRows() if ix.isValid() and ix.row() >= 0})
        if not use_proxy:
            return view_rows
        source_rows: list[int] = []
        for vr in view_rows:
            sidx = proxy.mapToSource(view_model.index(vr, 0))
            if sidx.isValid():
                source_rows.append(int(sidx.row()))
        return sorted(set(source_rows))

    def _selected_row_count_fast(self) -> int:
        """Row count for scope labels — avoids materializing every logical row when possible."""
        override = getattr(self._app, "_selected_oids_override", None)
        if override is not None:
            return len(override)
        sm = self._app.table.selectionModel()
        if sm is None:
            return 0
        return len(sm.selectedRows())

    def _selected_oids_set(self) -> set[int]:
        return selected_oids_for_plot(self._app)

    def _selected_oids_for_delete(self) -> frozenset[int]:
        """OIDs to delete without scanning the full table for logical row indices."""
        override = getattr(self._app, "_selected_oids_override", None)
        if override:
            return frozenset(int(x) for x in override)
        return frozenset(self._selected_oids_set())

    def _oids_for_row_indices(self, rows: list[int]) -> frozenset[int]:
        return oids_from_id_hidden_cells(
            rows,
            cell_text_col0=lambda r: self._app._table_model.cell_text(r, 0),
        )

    def _clear_table_selection_after_delete(self) -> None:
        self._cancel_pending_plot_table_select()
        self._cancel_chunked_table_selection()
        self._app._selected_oids_override = None
        sm = self._app.table.selectionModel()
        self._app._in_programmatic_table_selection = True
        try:
            if sm is not None:
                sm.clearSelection()
        finally:
            self._app._in_programmatic_table_selection = False
        self._sync_table_selection_highlight()
        self._schedule_plot_sync_after_programmatic_selection()

    def _refresh_table_after_bulk_delete(self) -> None:
        self._app.calculate_global_bounds()
        self._app.apply_filters()

    def _all_oids_in_table_order(self) -> list[int]:
        """Every row OID top-to-bottom (only rows with a numeric hidden id)."""
        out: list[int] = []
        for r in range(self._app._table_model.rowCount()):
            t0 = self._app._table_model.cell_text(r, 0)
            if t0.isdigit():
                out.append(int(t0))
        return out
