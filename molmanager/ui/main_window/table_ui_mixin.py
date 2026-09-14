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

from __future__ import annotations

import logging

from PyQt5.QtCore import QEventLoop, QItemSelection, QItemSelectionModel, Qt, QTimer
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QDialog,
    QInputDialog,
    QMenu,
    QMessageBox,
)

from rdkit import Chem

from ...confs_codec import (
    demote_v1_cell_to_sidecar,
    resolve_blocks_b64_for_viewer,
    rehydrate_v1_confs_cell,
)
from ...config import load_config
from ...import_structure import header_looks_like_structure_text, is_tool_generated_structure_header
from ...exception_policy import log_swallowed_exception
from ...services.chemistry_columns import (
    canonical_smiles_header_for_updates,
    cell_texts_have_parseable_molecule,
    data_headers_confirmed_for_chemistry_tools,
    is_smiles_named_header,
    ordered_headers_for_molecule_lookup,
    skip_chemistry_tool_column_dropdown,
    should_skip_chemical_scan_column,
)
from ...services.table_scope import collect_scoped_pairs, resolve_structure_row_for_oid
from ...utils import (
    canonical_structure_key_from_smiles as canonical_structure_key_from_smiles_fn,
    looks_like_mol_block,
    mol_to_canonical_smiles,
    parse_molecule_from_cell_text,
    row_cells_from_mol,
    safe_mol_prop_string,
)
from ...column_log_transform import (
    column_can_apply_log10,
    column_can_apply_precision,
    transform_column_values_log10,
    transform_column_values_precision,
)
from ..table_selection import item_selection_for_view_rows, merge_sorted_row_indices
from ..compound_table_model import CompoundTableModel
from ..singleton_modeless_dialog import reuse_or_show_modeless_singleton
from ..strings import TOOL_RENDER_2D
from ..widgets import CategoryFilterCard, FilterCard, TextFilterCard

from ..filters import FilterPanelMixin
from .table_search_mixin import TableSearchMixin
from .table_undo_commands import (
    DeleteRowSnapshot,
    UndoCellTextChangeCommand,
    UndoDeleteColumnCommand,
    UndoDeleteRowsCommand,
    UndoDuplicateColumnCommand,
    UndoInsertRowCommand,
    UndoLogarithmicColumnCommand,
    UndoPasteCellCommand,
    UndoPrecisionColumnCommand,
)

logger = logging.getLogger(__name__)


class TableUIMixin(TableSearchMixin, FilterPanelMixin):
    def _open_column_color_dialog(self, col: int) -> None:
        if col < 2 or col >= len(self.headers):
            return
        header_name = self.headers[col]
        if self._table_model.is_pixmap_data_column(header_name):
            return
        from ..dialogs.column_color import ColumnColorDialog

        bounds = self._table_model.numeric_bounds_by_column().get(header_name, {})
        dlg = ColumnColorDialog(
            self,
            header_name=header_name,
            numeric_bounds=bounds,
            current_mode=self._table_model.column_color_mode(header_name),
            current_spec=self._table_model.column_color_rule_spec(header_name),
        )
        if dlg.exec_() != QDialog.Accepted:
            return
        cfg = dlg.result_config()
        mode = cfg.get("mode", "off")
        if mode == "numeric":
            self._table_model.set_column_color_numeric_gradient(
                header_name,
                min_value=float(cfg.get("min", 0.0)),
                max_value=float(cfg.get("max", 1.0)),
                low_color=cfg["low_color"],
                high_color=cfg["high_color"],
                alpha=int(cfg.get("alpha", 96)),
            )
            self.status_label.setText(f"Coloring applied: {header_name} (numeric gradient).")
            return
        if mode == "categorical":
            self._table_model.set_column_color_categorical(
                header_name,
                alpha=int(cfg.get("alpha", 88)),
            )
            self.status_label.setText(f"Coloring applied: {header_name} (categorical).")
            return
        if mode == "numeric3":
            self._table_model.set_column_color_three_point_gradient(
                header_name,
                min_value=float(cfg.get("min", 0.0)),
                mid_value=float(cfg.get("mid", 0.5)),
                max_value=float(cfg.get("max", 1.0)),
                low_color=cfg["low_color"],
                mid_color=cfg["mid_color"],
                high_color=cfg["high_color"],
                alpha=int(cfg.get("alpha", 96)),
            )
            self.status_label.setText(f"Coloring applied: {header_name} (3-color gradient).")
            return
        self._table_model.clear_column_coloring(header_name)
        self.status_label.setText(f"Coloring cleared: {header_name}.")

    def _apply_table_sort(self, logical_col: int, ascending: bool, sort_kind: str) -> None:
        """Apply sort on the model and record state for session save/restore."""
        order = Qt.AscendingOrder if ascending else Qt.DescendingOrder
        self.table.setSortingEnabled(False)
        self._table_model.sort(logical_col, order, sort_kind=sort_kind)
        self._session_sort = {"column": logical_col, "ascending": ascending, "mode": sort_kind}

    def _on_horizontal_header_section_clicked(self, logical_index: int) -> None:
        if logical_index < 0 or logical_index >= len(self.headers):
            return
        if self.headers[logical_index] == "ID_HIDDEN":
            return
        view_model = self.table.model()
        if view_model is not None and view_model.rowCount() > 0:
            self.table.setCurrentIndex(view_model.index(0, logical_index))
        mods = QApplication.keyboardModifiers()
        if mods & Qt.ShiftModifier:
            anchor = getattr(self, "_column_selection_anchor", None)
            if anchor is None or anchor < 0 or anchor >= len(self.headers):
                self._column_selection_anchor = logical_index
                self._select_columns([logical_index], anchor_col=logical_index)
            else:
                self._select_column_range(anchor, logical_index)
            return
        self._column_selection_anchor = logical_index
        self._select_columns([logical_index], anchor_col=logical_index)

    def _select_column(self, col: int) -> None:
        self._column_selection_anchor = col
        self._select_columns([col], anchor_col=col)

    def _select_column_range(self, anchor_col: int, end_col: int) -> None:
        """Select all visible columns from ``anchor_col`` to ``end_col`` (inclusive)."""
        hh = self.table.horizontalHeader()
        vis_a = hh.visualIndex(int(anchor_col))
        vis_b = hh.visualIndex(int(end_col))
        if vis_a < 0 or vis_b < 0:
            self._select_columns([end_col], anchor_col=end_col)
            return
        lo, hi = (vis_a, vis_b) if vis_a <= vis_b else (vis_b, vis_a)
        cols: list[int] = []
        for vis in range(lo, hi + 1):
            logical = hh.logicalIndex(vis)
            if logical < 0 or logical >= len(self.headers):
                continue
            if self.headers[logical] == "ID_HIDDEN":
                continue
            cols.append(logical)
        self._select_columns(cols, anchor_col=end_col)

    def _select_columns(self, cols: list[int], *, anchor_col: int | None = None) -> None:
        view_model = self.table.model()
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
            if c < 0 or c >= len(self.headers) or c in seen:
                continue
            if self.headers[c] == "ID_HIDDEN":
                continue
            seen.add(c)
            unique_cols.append(c)
        if not unique_cols:
            self._report_table_selection_status(0)
            return
        prev_behavior = self.table.selectionBehavior()
        self.table.setSelectionBehavior(QAbstractItemView.SelectColumns)
        sel = QItemSelection()
        for col in unique_cols:
            top = view_model.index(0, col)
            bottom = view_model.index(n - 1, col)
            sel.select(top, bottom)
        sm = self.table.selectionModel()
        if sm is not None:
            sm.select(sel, QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Columns)
        self.table.setSelectionBehavior(prev_behavior)
        focus_col = (
            int(anchor_col)
            if anchor_col is not None and int(anchor_col) in seen
            else unique_cols[-1]
        )
        self._refresh_table_selection_visual([0] if n > 0 else None, anchor_col=focus_col)
        n_cols = len(unique_cols)
        extra = f"{n_cols} column{'s' if n_cols != 1 else ''}."
        self._report_table_selection_status(n, extra=extra)

    def _refresh_table_selection_visual(
        self, anchor_rows: list[int] | None, anchor_col: int | None = None
    ) -> None:
        """
        Show selection highlight immediately after programmatic select.

        Deferred one event-loop tick so context-menu focus is released first; then
        anchor the current cell, scroll if needed, focus the table, and repaint.

        When ``anchor_col`` is given (e.g. column selection), the current cell and any
        auto-scroll target that column so the horizontal scroll position is preserved;
        otherwise it defaults to the Structure column for row-based selections.
        """

        def _apply() -> None:
            if anchor_rows:
                first = min(anchor_rows)
                ncol = self._table_model.columnCount()
                if anchor_col is not None:
                    target_col = max(0, min(anchor_col, ncol - 1))
                else:
                    target_col = 1 if ncol > 1 else 0
                view_model = self.table.model()
                proxy = getattr(self, "_filter_proxy_model", None)
                if proxy is not None and view_model is proxy:
                    pidx = proxy.mapFromSource(self._table_model.index(first, 0))
                    if not pidx.isValid():
                        return
                    idx = view_model.index(pidx.row(), target_col)
                else:
                    idx = self._table_model.index(first, target_col)
                sm = self.table.selectionModel()
                if sm is not None and idx.isValid():
                    sm.setCurrentIndex(idx, QItemSelectionModel.NoUpdate)
                    self.table.scrollTo(idx, QAbstractItemView.EnsureVisible)
            self.table.setFocus(Qt.OtherFocusReason)
            self.table.viewport().update()

        QTimer.singleShot(0, _apply)

    def _set_selection_status(self, message: str, *, pump: bool = False) -> None:
        self.status_label.setText(message)
        if pump:
            QApplication.processEvents(QEventLoop.ExcludeUserInputEvents)

    def _report_table_selection_status(
        self, n_selected: int, *, extra: str = "", pump: bool = True
    ) -> None:
        total = self._table_model.rowCount()
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
        total = self._table_model.rowCount()
        if total >= load_config().table_selection_oid_override_min:
            self._set_selection_status(f"Selecting… (0/{total:,} rows)", pump=True)

    def _use_filter_proxy_for_table(self) -> bool:
        proxy = getattr(self, "_filter_proxy_model", None)
        view_model = self.table.model()
        return proxy is not None and view_model is proxy

    def _is_source_row_visible(self, source_row: int) -> bool:
        """Proxy-aware check for whether a source-model row index is currently shown."""
        if self._use_filter_proxy_for_table():
            proxy = self._filter_proxy_model
            return proxy.mapFromSource(self._table_model.index(source_row, 0)).isValid()
        return not self.table.isRowHidden(source_row)

    def _visible_source_row_indices(self) -> list[int] | None:
        """Source-model row indices for rows currently shown in the table view.

        Returns ``None`` when every source row is visible (no list allocation).
        """
        if self._use_filter_proxy_for_table():
            proxy = self._filter_proxy_model
            src_n = self._table_model.rowCount()
            if proxy.rowCount() == src_n:
                return None
            out: list[int] = []
            for pr in range(proxy.rowCount()):
                pidx = proxy.index(pr, 0)
                sidx = proxy.mapToSource(pidx)
                if sidx.isValid():
                    out.append(int(sidx.row()))
            return out
        n = self._table_model.rowCount()
        for r in range(n):
            if self.table.isRowHidden(r):
                return [r for r in range(n) if not self.table.isRowHidden(r)]
        return None

    def _iter_visible_source_row_indices(self):
        """Iterate visible source rows without building a full index list when possible."""
        indices = self._visible_source_row_indices()
        if indices is None:
            yield from range(self._table_model.rowCount())
        else:
            yield from indices

    def _repaint_table_selection_viewport(self) -> None:
        vp = self.table.viewport()
        if vp is not None:
            vp.update()

    def _sync_table_selection_highlight(self) -> None:
        """Paint row highlights from ``_selected_oids_override`` without a giant QItemSelection."""
        override = getattr(self, "_selected_oids_override", None)
        self._table_model.set_highlighted_oids(override)
        self._repaint_table_selection_viewport()

    def _schedule_plot_sync_after_programmatic_selection(self) -> None:
        """Sync plot highlights after search / analysis / other programmatic table selection."""
        schedule = getattr(self, "_schedule_sync_active_plots_from_table_selection", None)
        if callable(schedule):
            schedule()

    def _on_user_table_selection_changed(self, *_args) -> None:
        if getattr(self, "_in_programmatic_table_selection", False):
            return
        self._selected_oids_override = None
        self._sync_table_selection_highlight()
        self._schedule_plot_sync_after_programmatic_selection()
        sync_dock = getattr(self, "_sync_dock_complex_viewer", None)
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
                row = self.get_row_by_id(int(oid))
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
        view_model = self.table.model()
        proxy = getattr(self, "_filter_proxy_model", None)
        use_proxy = proxy is not None and view_model is proxy
        if not use_proxy:
            return list(source_rows)
        view_rows: list[int] = []
        for src_r in source_rows:
            pidx = proxy.mapFromSource(self._table_model.index(src_r, 0))
            if pidx.isValid():
                view_rows.append(int(pidx.row()))
        return view_rows

    def _oids_for_source_rows(self, source_rows: list[int]) -> frozenset[int]:
        oids: set[int] = set()
        for r in source_rows:
            try:
                oids.add(int(self._table_model.row_oid(r)))
            except (IndexError, ValueError, TypeError):
                continue
        return frozenset(oids)

    def _apply_qt_view_row_selection(
        self,
        source_rows: list[int],
        view_rows: list[int],
        *,
        clear_oid_override: bool,
        mode_flags=None,
    ) -> int:
        if clear_oid_override:
            self._selected_oids_override = None
        sm = self.table.selectionModel()
        view_model = self.table.model()
        if sm is None or view_model is None or not view_rows:
            return 0
        last_col = max(0, view_model.columnCount() - 1)
        flags = mode_flags or (QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows)
        prev_mode = self.table.selectionMode()
        prev_behavior = self.table.selectionBehavior()
        self.table.setSelectionMode(QAbstractItemView.MultiSelection)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._in_programmatic_table_selection = True
        try:
            if flags & QItemSelectionModel.Clear:
                sm.clearSelection()
            selection = item_selection_for_view_rows(view_model, view_rows, last_col=last_col)
            if not selection.isEmpty():
                sm.select(selection, flags)
        finally:
            self._in_programmatic_table_selection = False
        self.table.setSelectionMode(prev_mode)
        self.table.setSelectionBehavior(prev_behavior)
        self._sync_table_selection_highlight()
        self._refresh_table_selection_visual(source_rows)
        self._schedule_plot_sync_after_programmatic_selection()
        sync_dock = getattr(self, "_sync_dock_complex_viewer", None)
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
            self._selected_oids_override = None
        sm = self.table.selectionModel()
        self._in_programmatic_table_selection = True
        try:
            if sm is not None:
                sm.clearSelection()
            self._selected_oids_override = oids
        finally:
            self._in_programmatic_table_selection = False
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
            self._selected_oids_override = None
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
            self._selected_oids_override = None
        view_model = self.table.model()
        if view_model is None:
            return 0
        last_col = max(0, view_model.columnCount() - 1)
        ranges = merge_sorted_row_indices(view_rows)
        total = len(source_rows)
        self._cancel_chunked_table_selection()
        self._table_selection_job_gen = int(getattr(self, "_table_selection_job_gen", 0)) + 1
        gen = self._table_selection_job_gen
        sm = self.table.selectionModel()
        prev_mode = self.table.selectionMode()
        prev_behavior = self.table.selectionBehavior()
        self.table.setSelectionMode(QAbstractItemView.MultiSelection)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
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
                oids.add(int(self._table_model.row_oid(rows[j])))
            except (IndexError, ValueError, TypeError):
                continue
        ctx["idx"] = end
        self._table_model.set_highlighted_oids(frozenset(oids))
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
        sm = self.table.selectionModel()
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
        self._in_programmatic_table_selection = True
        try:
            if sm is not None and not selection.isEmpty():
                flags = QItemSelectionModel.Select | QItemSelectionModel.Rows
                if ri == 0:
                    flags |= QItemSelectionModel.Clear
                sm.select(selection, flags)
        finally:
            self._in_programmatic_table_selection = False
        done_rows = sum(hi - lo + 1 for lo, hi in ranges[:end_ri])
        ctx["range_idx"] = end_ri
        self._set_selection_status(f"Selecting… ({min(done_rows, total):,}/{total:,} rows)")
        if end_ri < len(ranges):
            QTimer.singleShot(0, self._table_selection_chunk_step)
            return
        self.table.setSelectionMode(ctx["prev_mode"])
        self.table.setSelectionBehavior(ctx["prev_behavior"])
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
        n_rows = self._table_model.rowCount()
        if n_rows <= 0:
            if clear_oid_override:
                self._selected_oids_override = None
            self._report_table_selection_status(0)
            return 0
        uniq = sorted({int(r) for r in rows if 0 <= int(r) < n_rows})
        if not uniq:
            if clear_oid_override:
                self._selected_oids_override = None
            self._report_table_selection_status(0)
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
            if not clear_oid_override and self._selected_oids_override:
                n_override = len(self._selected_oids_override)
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
            n_rows = self._table_model.rowCount()
            cfg = load_config()
            if n_rows >= cfg.table_selection_oid_override_min:
                self._start_chunked_oid_selection(list(range(n_rows)))
                return
            self.select_table_rows(list(range(n_rows)))
            return
        self.select_table_rows(vis)

    def _select_all_rows(self) -> None:
        """Select every row in the table, including rows hidden by filters."""
        self._maybe_status_before_large_select()
        n_rows = self._table_model.rowCount()
        if n_rows <= 0:
            self._report_table_selection_status(0)
            return
        all_rows = list(range(n_rows))
        cfg = load_config()
        if n_rows >= cfg.table_selection_oid_override_min:
            self._start_chunked_oid_selection(
                all_rows,
                clear_oid_override=False,
                extra_status="(includes filtered-out rows)",
            )
            return
        self.select_table_rows(all_rows, clear_oid_override=False)
        self._selected_oids_override = frozenset(self._all_oids_in_table_order())
        self._report_table_selection_status(len(self._selected_oids_override))

    def clear_table_selection(self) -> None:
        """Clear Qt and logical (large) row selection."""
        self._cancel_chunked_table_selection()
        self._selected_oids_override = None
        sm = self.table.selectionModel()
        self._in_programmatic_table_selection = True
        try:
            if sm is not None:
                sm.clearSelection()
        finally:
            self._in_programmatic_table_selection = False
        self._sync_table_selection_highlight()
        self._report_table_selection_status(0)

    def invert_table_selection(self) -> None:
        """Select every table row that is not currently selected (full table, including filtered-out rows)."""
        n_rows = self._table_model.rowCount()
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
        seen: set[str] = set()
        to_sel: list[int] = []
        for r in self._iter_visible_source_row_indices():
            txt = (self._table_model.cell_text(r, col) or "").strip()
            if not txt:
                continue
            if txt in seen:
                continue
            seen.add(txt)
            to_sel.append(r)
        self.select_table_rows(to_sel)

    def _select_empty_cells_in_column(self, col: int) -> None:
        """Select visible rows where this column is empty or whitespace-only."""
        self._maybe_status_before_large_select()
        to_sel: list[int] = []
        for r in self._iter_visible_source_row_indices():
            if not (self._table_model.cell_text(r, col) or "").strip():
                to_sel.append(r)
        self.select_table_rows(to_sel)

    def _structure_column_row_is_empty(self, row: int) -> bool:
        """True when the row has no chemical structure (fast text/mol store check)."""
        try:
            oid = self._table_model.row_oid(row)
        except (IndexError, ValueError, TypeError):
            return True
        if self.mols.get(oid) is not None:
            return False
        smi_h = self._canonical_smiles_header_for_updates()
        if smi_h and smi_h in self.headers:
            ci = self.headers.index(smi_h)
            if (self._table_model.cell_text(row, ci) or "").strip():
                return False
        ov = getattr(self, "_structure_field_override", None)
        ov_s = str(ov).strip() if isinstance(ov, str) else ""
        for h in self._ordered_headers_for_molecule_lookup():
            if smi_h and h == smi_h:
                continue
            if is_tool_generated_structure_header(h) and h != ov_s:
                continue
            ci = self.headers.index(h)
            raw = (self._table_model.cell_text(row, ci) or "").strip()
            if not raw:
                continue
            if (
                (ov_s and h == ov_s)
                or self._is_smiles_named_header(h)
                or self._header_looks_structural(h)
            ):
                return False
            if looks_like_mol_block(raw):
                return False
        return True

    def _select_empty_structure_cells(self) -> None:
        self._maybe_status_before_large_select()
        to_sel: list[int] = []
        for r in self._iter_visible_source_row_indices():
            if self._structure_column_row_is_empty(r):
                to_sel.append(r)
        self.select_table_rows(to_sel)

    def _structure_distinct_key_for_row(
        self, row: int, *, smiles_key_cache: dict[str, str] | None = None
    ) -> str:
        """Canonical structure key for Select → first occurrence on the Structure column."""
        try:
            oid = self._table_model.row_oid(row)
        except (IndexError, ValueError, TypeError):
            return ""
        mol = self.mols.get(oid)
        if mol is not None:
            try:
                raw = Chem.MolToSmiles(mol)
            except Exception:
                raw = ""
            if raw:
                return self._canonical_structure_key_cached(raw, smiles_key_cache)
            return ""
        try:
            smi_col = self.headers.index("SMILES")
        except ValueError:
            return ""
        raw = (self._table_model.cell_text(row, smi_col) or "").strip()
        if not raw:
            return ""
        return self._canonical_structure_key_cached(raw, smiles_key_cache)

    def _canonical_structure_key_cached(self, smiles: str, cache: dict[str, str] | None) -> str:
        s = (smiles or "").strip()
        if not s:
            return ""
        if cache is not None and s in cache:
            return cache[s]
        key = self.canonical_structure_key_from_smiles(s) or s
        if cache is not None:
            cache[s] = key
        return key

    def _select_first_occurrence_per_distinct_structure(self) -> None:
        self._maybe_status_before_large_select()
        seen: set[str] = set()
        to_sel: list[int] = []
        smiles_key_cache: dict[str, str] = {}
        for r in self._iter_visible_source_row_indices():
            key = self._structure_distinct_key_for_row(r, smiles_key_cache=smiles_key_cache)
            if not key or key in seen:
                continue
            seen.add(key)
            to_sel.append(r)
        self.select_table_rows(to_sel)

    def _selected_logical_rows(self) -> list[int]:
        """Distinct source-model row indices from the current selection (any column)."""
        override = getattr(self, "_selected_oids_override", None)
        if override:
            rows: list[int] = []
            for oid in override:
                r = self._table_model.logical_row_for_oid(int(oid))
                if r >= 0:
                    rows.append(r)
            return sorted(set(rows))
        sm = self.table.selectionModel()
        if sm is None:
            return []
        view_model = self.table.model()
        proxy = getattr(self, "_filter_proxy_model", None)
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
        override = getattr(self, "_selected_oids_override", None)
        if override is not None:
            return len(override)
        sm = self.table.selectionModel()
        if sm is None:
            return 0
        return len(sm.selectedRows())

    def _selected_oids_set(self) -> set[int]:
        from ..plot_table_sync import selected_oids_for_plot

        return selected_oids_for_plot(self)

    def _selected_oids_for_delete(self) -> frozenset[int]:
        """OIDs to delete without scanning the full table for logical row indices."""
        override = getattr(self, "_selected_oids_override", None)
        if override:
            return frozenset(int(x) for x in override)
        return frozenset(self._selected_oids_set())

    def _oids_for_row_indices(self, rows: list[int]) -> frozenset[int]:
        oids: set[int] = set()
        for r in rows:
            try:
                t0 = self._table_model.cell_text(int(r), 0)
            except (IndexError, TypeError, ValueError):
                continue
            if t0.isdigit():
                oids.add(int(t0))
        return frozenset(oids)

    def _clear_table_selection_after_delete(self) -> None:
        self._cancel_chunked_table_selection()
        self._selected_oids_override = None
        sm = self.table.selectionModel()
        self._in_programmatic_table_selection = True
        try:
            if sm is not None:
                sm.clearSelection()
        finally:
            self._in_programmatic_table_selection = False
        self._sync_table_selection_highlight()

    def _refresh_table_after_bulk_delete(self) -> None:
        self.calculate_global_bounds()
        self.apply_filters()

    def _all_oids_in_table_order(self) -> list[int]:
        """Every row OID top-to-bottom (only rows with a numeric hidden id)."""
        out: list[int] = []
        for r in range(self._table_model.rowCount()):
            t0 = self._table_model.cell_text(r, 0)
            if t0.isdigit():
                out.append(int(t0))
        return out

    def _row_cells_dict(self, row: int) -> dict[str, str]:
        out: dict[str, str] = {}
        for name in self.headers[2:]:
            c = self.headers.index(name)
            out[name] = self._table_cell_text(row, c)
        return out

    def _on_column_moved(self, logicalIndex: int, oldVisualIndex: int, newVisualIndex: int) -> None:
        # Keep `ID_HIDDEN` (col 0) and `Structure` (col 1) fixed at visual positions 0 and 1.
        # Qt will still allow drops around them; we snap them back after the move.
        h = self.table.horizontalHeader()
        if self._table_model.columnCount() < 2:
            return
        if h.visualIndex(0) != 0:
            h.moveSection(h.visualIndex(0), 0)
        if h.visualIndex(1) != 1:
            h.moveSection(h.visualIndex(1), 1)

    def _visual_logical_columns(self) -> list[int]:
        """Logical column indices sorted by current visual order."""
        h = self.table.horizontalHeader()
        n = self._table_model.columnCount()
        cols = list(range(n))
        cols.sort(key=h.visualIndex)
        return cols

    def _table_cell_text(self, row: int, col: int) -> str:
        """Best-effort text for exporting (structure column has no text when shown as pixmap)."""
        if col == 1:
            return ""
        return (self._table_model.cell_text(row, col) or "").strip()

    @staticmethod
    def _header_looks_structural(name: str) -> bool:
        return header_looks_like_structure_text(name)

    def _skip_chemistry_tool_column_dropdown(self, h: str) -> bool:
        """Exclude non-molecular columns from chemistry-tool source dropdowns."""
        return skip_chemistry_tool_column_dropdown(h)

    def _column_has_parseable_molecule_sample(
        self,
        header_name: str,
        *,
        max_rows_scan: int = 500,
        max_nonempty_samples: int = 80,
    ) -> bool:
        """True if a sample of cells in this column parses as a molecule (SMILES, InChI, MolBlock, SMARTS, …)."""
        if header_name not in self.headers:
            return False

        def _iter_texts():
            n = min(self._table_model.rowCount(), max_rows_scan)
            for r in range(n):
                raw = self._table_model.backing_value_for_row_header(r, header_name)
                if not raw:
                    try:
                        ci = self.headers.index(header_name)
                    except ValueError:
                        continue
                    raw = (self._table_cell_text(r, ci) or "").strip()
                yield raw

        return cell_texts_have_parseable_molecule(
            _iter_texts(),
            max_nonempty_samples=max_nonempty_samples,
        )

    def _data_headers_confirmed_for_chemistry_tools(self) -> list[str]:
        """
        Data columns suitable as chemistry-tool sources: structural-looking names,
        optional ``_structure_field_override``, or at least one parseable cell in a bounded scan.
        """
        ov = getattr(self, "_structure_field_override", None)
        return data_headers_confirmed_for_chemistry_tools(
            self.headers,
            structure_field_override=ov if isinstance(ov, str) else None,
            column_has_parseable_sample=self._column_has_parseable_molecule_sample,
        )

    def _should_skip_chemical_scan_column(self, h: str) -> bool:
        return should_skip_chemical_scan_column(
            h,
            is_pixmap_column=self._table_model.is_pixmap_data_column,
        )

    def _ordered_headers_for_molecule_lookup(self) -> list[str]:
        """Column names to probe for parseable chemistry (likely names first, then all other data columns)."""
        ov = getattr(self, "_structure_field_override", None)
        return ordered_headers_for_molecule_lookup(
            self.headers,
            structure_field_override=ov if isinstance(ov, str) else None,
            is_pixmap_column=self._table_model.is_pixmap_data_column,
        )

    def _canonical_smiles_header_for_updates(self) -> str | None:
        """Column to store canonical SMILES after chemistry tools (prefer ``SMILES``)."""
        return canonical_smiles_header_for_updates(self.headers)

    def _is_smiles_named_header(self, h: str) -> bool:
        return is_smiles_named_header(h)

    def _fill_row_data_columns_from_mol(self, row_idx: int, mol: Chem.Mol | None) -> None:
        """Populate data columns (from col 2 onward) from RDKit mol properties — same source as RenderWorker props."""
        if not self.headers or row_idx < 0 or row_idx >= self._table_model.rowCount():
            return
        oid = self._table_model.row_oid(row_idx)
        values = self._row_cells_from_mol(mol)
        self._table_model.set_cell_text_batch(oid, values)

    def _row_cells_from_mol(self, mol: Chem.Mol | None) -> dict[str, str]:
        """Build row cell values for all data columns from one molecule."""
        return row_cells_from_mol(mol, self.headers[2:])

    def _mol_for_structure_row(self, row: int) -> Chem.Mol | None:
        """Best-effort RDKit mol: in-memory store, then any parseable chemistry in table columns."""
        if row < 0 or row >= self._table_model.rowCount():
            return None
        t0 = self._table_model.cell_text(row, 0)
        oid = int(t0) if t0.isdigit() else None
        if oid is not None:
            m = self.mols.get(oid)
            if m is not None:
                return self._apply_structure_field_override(m)
        ov = getattr(self, "_structure_field_override", None)
        ov_s = str(ov).strip() if isinstance(ov, str) else ""
        for h in self._ordered_headers_for_molecule_lookup():
            if is_tool_generated_structure_header(h) and h != ov_s:
                continue
            ci = self.headers.index(h)
            raw = (self._table_model.cell_text(row, ci) or "").strip()
            if not raw:
                raw = (self._table_model.backing_value_for_row_header(row, h) or "").strip()
            if not raw:
                continue
            priority = (
                (ov_s and h == ov_s)
                or self._is_smiles_named_header(h)
                or self._header_looks_structural(h)
            )
            if not priority and len(raw) > 20000 and not looks_like_mol_block(raw):
                continue
            m = self._mol_from_structure_text(raw)
            if m is not None:
                return self._apply_structure_field_override(m)
        return None

    def _column_eligible_for_table_chemistry_menu(self, row: int, col: int) -> bool:
        """Whether the table cell's column should offer structure tools / Copy as SMILES."""
        if col == CompoundTableModel.STRUCTURE_COL:
            return True
        if col <= 0 or col >= len(self.headers):
            return False
        h = self.headers[col]
        from ...som_prediction import is_som_map_header

        if is_som_map_header(h):
            return False
        if self._skip_chemistry_tool_column_dropdown(h):
            return False
        if self._header_looks_structural(h) or self._is_smiles_named_header(h):
            return True
        raw = self._structure_text_for_table_cell(row, col)
        if not raw or (len(raw) > 20000 and not looks_like_mol_block(raw)):
            return False
        return parse_molecule_from_cell_text(raw) is not None

    def _column_accepts_cell_paste(self, row: int, col: int) -> bool:
        """Whether Paste is allowed on this cell (text data, Structure, or pixmap chemistry)."""
        if col == CompoundTableModel.STRUCTURE_COL:
            return True
        if self._table_model.column_accepts_text_edit(col):
            return True
        if 0 <= col < len(self.headers) and self._table_model.is_pixmap_data_column(
            self.headers[col]
        ):
            return self._column_eligible_for_table_chemistry_menu(row, col)
        return False

    def _structure_text_for_table_cell(self, row: int, col: int) -> str:
        """Stored SMILES/molblock for a cell, including pixmap-only structure columns."""
        if col == CompoundTableModel.STRUCTURE_COL or col <= 0 or col >= len(self.headers):
            return ""
        h = self.headers[col]
        raw = (self._table_model.backing_value_for_row_header(row, h) or "").strip()
        if raw:
            return raw
        return (self._table_model.cell_text(row, col) or "").strip()

    def _mol_for_table_context_menu(self, row: int, col: int) -> Chem.Mol | None:
        """Molecule for context-menu actions from the clicked column (not a different field)."""
        if not self._column_eligible_for_table_chemistry_menu(row, col):
            return None
        if col == CompoundTableModel.STRUCTURE_COL:
            return self._mol_for_structure_row(row)
        raw = self._structure_text_for_table_cell(row, col)
        if not raw or (len(raw) > 20000 and not looks_like_mol_block(raw)):
            return None
        m = self._mol_from_structure_text(raw)
        return self._apply_structure_field_override(m) if m is not None else None

    def _mol_from_structure_text(self, raw: str) -> Chem.Mol | None:
        return parse_molecule_from_cell_text(raw)

    def chemistry_tool_structure_sources(self) -> list[str]:
        """Candidate values for a tool dialog's structure-source dropdown."""
        return ["Structure"] + self._data_headers_confirmed_for_chemistry_tools()

    def collect_scoped_table_mols(
        self,
        src: str,
        *,
        only_selected: bool = False,
        only_visible: bool = False,
    ) -> list[tuple[int, Chem.Mol]]:
        """
        Iterate the table and return ``(oid, mol)`` pairs in scope for a chemistry tool.

        ``src`` is ``"Structure"`` (use the row's structure column / cached mol) or a
        data-column header name (parse that column's cell or pixmap backing SMILES).
        Data-column parses are not written into ``self.mols``. Used by the pKa, protomer,
        cluster, and dimensionality-reduction dialogs.
        """
        allowed = self._selected_oids_set() if only_selected else None
        col = None if src == "Structure" else self.headers.index(src)
        visible_rows: set[int] | None = None
        if only_visible:
            vis = self._visible_source_row_indices()
            visible_rows = None if vis is None else set(vis)
        is_pixmap_src = src != "Structure" and self._table_model.is_pixmap_data_column(src)

        def _resolve(r: int, oid: int) -> Chem.Mol | None:
            if src == "Structure":
                return self.mols.get(oid) or self._mol_for_structure_row(r)
            if is_pixmap_src:
                raw = self._table_model.backing_value_for_row_header(r, src)
                mol = self._mol_from_structure_text(raw) if raw else None
                return mol
            raw = self._table_cell_text(r, col)
            if not raw:
                raw = self._table_model.backing_value_for_row_header(r, src)
            return self._mol_from_structure_text(raw) if raw else None

        return collect_scoped_pairs(
            self._table_model.rowCount(),
            row_oid=self._table_model.row_oid,
            resolve=_resolve,
            allowed_oids=allowed,
            visible_rows=visible_rows,
        )

    def collect_scoped_table_smiles(
        self,
        src: str,
        *,
        only_selected: bool = False,
        only_visible: bool = False,
        process_ui_every: int = 64,
    ) -> list[tuple[int, str]]:
        """
        Like :meth:`collect_scoped_table_mols` but returns ``(oid, SMILES text)`` without RDKit parsing.

        Periodically pumps the event loop so large tables stay responsive while gathering inputs.
        """
        from PyQt5.QtWidgets import QApplication

        allowed = self._selected_oids_set() if only_selected else None
        col = None if src == "Structure" else self.headers.index(src)
        visible_rows: set[int] | None = None
        if only_visible:
            vis = self._visible_source_row_indices()
            visible_rows = None if vis is None else set(vis)
        is_pixmap_src = src != "Structure" and self._table_model.is_pixmap_data_column(src)
        smiles_h = self._canonical_smiles_header_for_updates()
        every = int(process_ui_every)

        def _on_row(r: int) -> None:
            if every > 0 and r > 0 and r % every == 0:
                QApplication.processEvents()

        def _resolve(r: int, oid: int) -> str | None:
            raw = ""
            if src == "Structure":
                if smiles_h:
                    raw = (
                        self._table_model.backing_value_for_row_header(r, smiles_h) or ""
                    ).strip()
                    if not raw:
                        raw = (self._table_cell_text(r, self.headers.index(smiles_h)) or "").strip()
                if not raw:
                    mol = self.mols.get(oid)
                    if mol is None:
                        mol = self._mol_for_structure_row(r)
                    if mol is not None:
                        try:
                            raw = mol_to_canonical_smiles(mol)
                        except Exception:
                            raw = ""
            elif is_pixmap_src:
                raw = (self._table_model.backing_value_for_row_header(r, src) or "").strip()
            else:
                raw = (self._table_cell_text(r, col) or "").strip()
                if not raw:
                    raw = (self._table_model.backing_value_for_row_header(r, src) or "").strip()
            smi = raw.strip()
            return smi or None

        return collect_scoped_pairs(
            self._table_model.rowCount(),
            row_oid=self._table_model.row_oid,
            resolve=_resolve,
            allowed_oids=allowed,
            visible_rows=visible_rows,
            on_row=_on_row,
        )

    def _apply_structure_field_override(self, mol: Chem.Mol | None) -> Chem.Mol | None:
        field = getattr(self, "_structure_field_override", None)
        if not field or mol is None:
            return mol
        if is_tool_generated_structure_header(str(field)):
            return mol
        if not mol.HasProp(field):
            return mol
        raw = (safe_mol_prop_string(mol, field) or "").strip()
        nm = self._mol_from_structure_text(raw)
        return nm if nm is not None else mol

    def _on_external_db_dialog_destroyed(self):
        self._external_db_dialog = None

    def _on_pubchem_dialog_destroyed(self):
        self._pubchem_dialog = None

    def _on_chembl_dialog_destroyed(self):
        self._chembl_dialog = None

    def _on_patent_query_dialog_destroyed(self):
        self._patent_query_dialog = None

    def _on_smina_dock_dialog_destroyed(self):
        self._smina_dock_dialog = None

    def _on_easydock_dialog_destroyed(self):
        self._easydock_dialog = None

    def _on_pdbqt_generator_dialog_destroyed(self):
        self._pdbqt_generator_dialog = None

    def _on_pdb_fixer_dialog_destroyed(self):
        self._pdb_fixer_dialog = None

    def get_row_by_id(self, original_idx):
        return self._table_model.logical_row_for_oid(int(original_idx))

    def _resolve_structure_row_for_oid(self, oid: int) -> int:
        """Table row index for this molecule id (stable during a Render 2D batch)."""
        return resolve_structure_row_for_oid(
            oid,
            row_count=self._table_model.rowCount(),
            cell_text_col0=lambda r: self._table_model.cell_text(r, 0),
            logical_row_for_oid=self.get_row_by_id,
            render2d_row_by_oid=getattr(self, "_render2d_row_by_oid", None),
        )

    def _create_header_context_menu(self, col: int):
        """Column-header context menu. Dock results windows keep Sort and Select only."""
        if col < 0 or col >= len(self.headers):
            return None
        if self.headers[col] == "ID_HIDDEN":
            return None
        old_n = self.headers[col]
        menu = QMenu(self)
        menu.setToolTipsVisible(True)
        sel_act = menu.addAction(f"Select column '{old_n}'")
        sel_act.setObjectName("header_select_column")
        select_sub = menu.addMenu("Select")
        select_sub.setToolTipsVisible(True)
        select_all_visible_act = select_sub.addAction("Select All Visible")
        select_all_visible_act.setObjectName("header_select_all_visible")
        select_all_visible_act.setToolTip(
            "Select every row currently visible in the table (respects active filters)."
        )
        select_all_act = select_sub.addAction("Select All")
        select_all_act.setObjectName("header_select_all")
        select_all_act.setToolTip(
            "Select every row in the table, including rows hidden by filters."
        )
        select_sub.addSeparator()
        if self.headers[col] == "Structure":
            first_occ_act = select_sub.addAction("First Occurrence (per distinct structure)")
            first_occ_act.setToolTip(
                "For each distinct structure (canonical SMILES), select the first visible row where it appears."
            )
        else:
            first_occ_act = select_sub.addAction("First Occurrence (per distinct value)")
            first_occ_act.setToolTip(
                "For each non-empty cell text, select the first visible row where that value appears (top to bottom)."
            )
        first_occ_act.setObjectName("header_select_first_occurrence")
        empty_act = select_sub.addAction("Empty cells")
        empty_act.setObjectName("header_select_empty")
        if self.headers[col] == "Structure":
            empty_act.setToolTip(
                "Select visible rows with no chemical structure (no molecule in memory and no parseable SMILES or structure text)."
            )
        else:
            empty_act.setToolTip(
                "Select every visible row where this column is blank or whitespace-only."
            )
        if self._table_model.rowCount() > 0:
            sort_top = menu.addMenu("Sort")
            num_m = sort_top.addMenu("Numeric")
            sort_num_asc = num_m.addAction("Ascending")
            sort_num_asc.setObjectName("header_sort_num_asc")
            sort_num_desc = num_m.addAction("Descending")
            sort_num_desc.setObjectName("header_sort_num_desc")
            alp_m = sort_top.addMenu("Alphabetic")
            sort_alpha_asc = alp_m.addAction("Ascending")
            sort_alpha_asc.setObjectName("header_sort_alpha_asc")
            sort_alpha_desc = alp_m.addAction("Descending")
            sort_alpha_desc.setObjectName("header_sort_alpha_desc")
        if not getattr(self, "_dock_results_mode", False):
            menu.addSeparator()
            search_act = menu.addAction("Search")
            search_act.setObjectName("header_search")
            if col >= 2 and not self._table_model.is_pixmap_data_column(old_n):
                color_act = menu.addAction("Color")
                color_act.setObjectName("header_color")
            from ...mmp_analysis import is_mmp_result_header

            if is_mmp_result_header(old_n):
                ledger_act = menu.addAction("Transform Ledger")
                ledger_act.setObjectName("header_mmp_transform_ledger")
                ledger_act.setToolTip(
                    "Open the MMP Transform Ledger for this session's MMP results."
                )
            menu.addSeparator()
            if old_n == "Structure":
                dup_act = menu.addAction(f"Duplicate '{old_n}'")
                dup_act.setObjectName("header_duplicate")
                dup_act.setToolTip(
                    "Copy structures into a new chemistry column (SMILES and 2D images). "
                    "The copy can be renamed, deleted, and used as a tool source like Protonated."
                )
            else:
                ren_act = menu.addAction(f"Rename '{old_n}'")
                ren_act.setObjectName("header_rename")
                dup_act = menu.addAction(f"Duplicate '{old_n}'")
                dup_act.setObjectName("header_duplicate")
                del_act = menu.addAction(f"Delete '{old_n}'")
                del_act.setObjectName("header_delete")
            menu.addSeparator()
            log_act = menu.addAction("Logarithmic")
            log_act.setObjectName("header_logarithmic")
            log_act.setCheckable(True)
            log_act.setChecked(old_n in getattr(self, "_logarithmic_columns", set()))
            log_act.setEnabled(self._column_can_toggle_logarithmic(old_n))
            log_act.setToolTip(
                "Convert positive numeric values to log10. Click again to convert back. "
                "Disabled when the column has no positive numeric values, or any numeric "
                "value ≤ 0 (while not already logarithmic)."
            )
            prec_act = menu.addAction("Precision…")
            prec_act.setObjectName("header_precision")
            prec_act.setEnabled(self._column_can_apply_precision(old_n))
            prec_act.setToolTip(
                "Round numeric values in this column to a chosen number of decimal places. "
                "Disabled when the column has no numeric values."
            )
        return menu

    def show_header_menu(self, pos):
        col = self.table.horizontalHeader().logicalIndexAt(pos)
        menu = self._create_header_context_menu(col)
        if menu is None:
            return
        old_n = self.headers[col]
        action = menu.exec_(self.table.horizontalHeader().mapToGlobal(pos))
        if action is None:
            return
        name = action.objectName()
        if name == "header_select_column":
            self.table.setCurrentIndex(self._table_model.index(0, col))
            self._select_column(col)
        elif name == "header_sort_num_asc":
            self._apply_table_sort(col, True, "numeric")
        elif name == "header_sort_num_desc":
            self._apply_table_sort(col, False, "numeric")
        elif name == "header_sort_alpha_asc":
            self._apply_table_sort(col, True, "alphabetic")
        elif name == "header_sort_alpha_desc":
            self._apply_table_sort(col, False, "alphabetic")
        elif name == "header_search":
            self.open_table_search_with_column(col)
        elif name == "header_color":
            self._open_column_color_dialog(col)
        elif name == "header_mmp_transform_ledger":
            opener = getattr(self, "open_mmp_transform_ledger_for_last_run", None)
            if callable(opener):
                opener()
        elif name == "header_logarithmic":
            self._toggle_column_logarithmic(old_n)
        elif name == "header_precision":
            self._apply_column_precision(old_n)
        elif name == "header_select_all_visible":
            self._select_all_visible_rows()
        elif name == "header_select_all":
            self._select_all_rows()
        elif name == "header_select_first_occurrence":
            if self.headers[col] == "Structure":
                self._select_first_occurrence_per_distinct_structure()
            else:
                self._select_first_occurrence_per_distinct_value(col)
        elif name == "header_select_empty":
            if self.headers[col] == "Structure":
                self._select_empty_structure_cells()
            else:
                self._select_empty_cells_in_column(col)
        elif name == "header_delete":
            self._undo_stack.push(UndoDeleteColumnCommand(self, col))
        elif name == "header_rename":
            name_in, ok = QInputDialog.getText(self, "Rename", "New name:", text=old_n)
            if ok and name_in:
                self.headers[col] = name_in
                self._table_model.rename_header_at(col, name_in)
                logs = getattr(self, "_logarithmic_columns", None)
                if logs is not None and old_n in logs:
                    logs.discard(old_n)
                    logs.add(name_in)
                if old_n in self.global_bounds:
                    self.global_bounds[name_in] = self.global_bounds.pop(old_n)
                cols = self._filterable_data_column_names()
                for f in self.filters:
                    if isinstance(f, FilterCard):
                        f.update_prop_list(list(self.global_bounds.keys()), old_n, name_in)
                    elif isinstance(f, (TextFilterCard, CategoryFilterCard)):
                        f.update_prop_list(cols, old_n, name_in)
        elif name == "header_duplicate":
            self._undo_stack.push(UndoDuplicateColumnCommand(self, col, old_n))

    def _column_can_toggle_logarithmic(self, header_name: str) -> bool:
        if header_name in ("ID_HIDDEN", "Structure"):
            return False
        if self._table_model.is_pixmap_data_column(header_name):
            return False
        if header_name in getattr(self, "_logarithmic_columns", set()):
            return True
        texts = self._table_model.column_text_by_oid(header_name).values()
        return column_can_apply_log10(texts)

    def _toggle_column_logarithmic(self, header_name: str) -> None:
        if not self._column_can_toggle_logarithmic(header_name):
            return
        logs = getattr(self, "_logarithmic_columns", None)
        if logs is None:
            self._logarithmic_columns = set()
            logs = self._logarithmic_columns
        to_log = header_name not in logs
        current = self._table_model.column_text_by_oid(header_name)
        changed = transform_column_values_log10(current, to_log=to_log)
        if not changed and to_log:
            self.status_label.setText(
                f"Column '{header_name}' has no positive numeric values to convert."
            )
            return
        previous = {oid: current[oid] for oid in changed}
        self._undo_stack.push(
            UndoLogarithmicColumnCommand(
                self,
                header_name,
                to_log=to_log,
                changed_by_oid=changed,
                previous_by_oid=previous,
            )
        )

    def _column_can_apply_precision(self, header_name: str) -> bool:
        if header_name in ("ID_HIDDEN", "Structure"):
            return False
        if self._table_model.is_pixmap_data_column(header_name):
            return False
        texts = self._table_model.column_text_by_oid(header_name).values()
        return column_can_apply_precision(texts)

    def _apply_column_precision(self, header_name: str) -> None:
        if not self._column_can_apply_precision(header_name):
            return
        decimals, ok = QInputDialog.getInt(
            self,
            "Precision",
            f"Decimal places for '{header_name}':",
            2,
            0,
            12,
        )
        if not ok:
            return
        current = self._table_model.column_text_by_oid(header_name)
        changed = transform_column_values_precision(current, decimals=decimals)
        if not changed:
            self.status_label.setText(
                f"Column '{header_name}' already matches {decimals} decimal place(s)."
            )
            return
        previous = {oid: current[oid] for oid in changed}
        self._undo_stack.push(
            UndoPrecisionColumnCommand(
                self,
                header_name,
                decimals=decimals,
                changed_by_oid=changed,
                previous_by_oid=previous,
            )
        )

    def show_row_header_menu(self, pos):
        row = self.table.verticalHeader().logicalIndexAt(pos)
        if row < 0:
            return
        menu = QMenu(self)
        dup_act = menu.addAction("Duplicate Row")
        del_act = menu.addAction("Delete Row")
        action = menu.exec_(self.table.verticalHeader().mapToGlobal(pos))
        if action == dup_act:
            cmd = UndoInsertRowCommand(self, row)
            if cmd.is_valid():
                self._undo_stack.push(cmd)

        elif action == del_act:
            t0 = self._table_model.cell_text(row, 0)
            if t0.isdigit():
                self._confirm_and_push_delete_rows([row])

    def _copy_text_for_table_cell(self, row: int, col: int, oid: int | None) -> tuple[bool, str]:
        """Whether copy is meaningful, and the string to place on the clipboard."""
        if oid is None:
            return False, ""
        if col == 0:
            return True, str(oid)
        if col == CompoundTableModel.STRUCTURE_COL:
            if "SMILES" in self.headers:
                sci = self.headers.index("SMILES")
                t = (self._table_model.cell_text(row, sci) or "").strip()
                if t:
                    return True, t
            mol = self.mols.get(oid)
            if mol is not None:
                try:
                    return True, mol_to_canonical_smiles(mol)
                except Exception:
                    return False, ""
            return False, ""
        h = self.headers[col] if 0 <= col < len(self.headers) else ""
        if h and self._table_model.is_pixmap_data_column(h):
            t = (self._table_model.backing_value_for_row_header(row, h) or "").strip()
            return (True, t) if t else (False, "")
        if self._table_model.column_accepts_text_edit(col):
            return True, self._table_model.cell_text(row, col) or ""
        return False, ""

    def edit_copy(self) -> None:
        """Copy the current selection to the clipboard (tab-separated columns, newline-separated rows)."""
        sm = self.table.selectionModel()
        indexes = list(sm.selectedIndexes()) if sm is not None else []
        if not indexes:
            ix = self.table.currentIndex()
            if ix.isValid():
                indexes = [ix]
        if not indexes:
            self.status_label.setText("Copy: nothing selected.")
            return
        by_row: dict[int, list[int]] = {}
        for ix in indexes:
            if ix.isValid():
                by_row.setdefault(ix.row(), []).append(ix.column())
        lines: list[str] = []
        for r in sorted(by_row.keys()):
            col_list = sorted({c for c in by_row[r] if c != 0})
            if not col_list:
                continue
            parts: list[str] = []
            for c in col_list:
                t0 = self._table_model.cell_text(r, 0)
                oid = int(t0) if t0.isdigit() else None
                ok, txt = self._copy_text_for_table_cell(r, c, oid)
                parts.append(txt if ok else "")
            lines.append("\t".join(parts))
        text = "\n".join(lines)
        if not text.strip():
            self.status_label.setText("Copy: no copyable text in the selection.")
            return
        QApplication.clipboard().setText(text)
        self.status_label.setText("Copy: copied selection to clipboard.")

    def edit_paste(self) -> None:
        """Paste the clipboard into the current or primary selected cell."""
        ix = self.table.currentIndex()
        if not ix.isValid():
            sm = self.table.selectionModel()
            if sm is not None:
                for cand in sm.selectedIndexes():
                    if cand.isValid():
                        ix = cand
                        break
        if not ix.isValid():
            self.status_label.setText("Paste: select a cell first.")
            return
        row, col = ix.row(), ix.column()
        t0 = self._table_model.cell_text(row, 0)
        oid = int(t0) if t0.isdigit() else None
        if oid is None:
            self.status_label.setText("Paste: invalid row.")
            return
        clip = (QApplication.clipboard().text() or "").strip()
        if not clip:
            QMessageBox.information(self, "Paste", "Clipboard is empty.")
            return
        if not self._column_accepts_cell_paste(row, col):
            self.status_label.setText("Paste: this column cannot be edited.")
            return
        if col == CompoundTableModel.STRUCTURE_COL or (
            0 <= col < len(self.headers)
            and self._table_model.is_pixmap_data_column(self.headers[col])
        ):
            if self._mol_from_structure_text(clip) is None:
                QMessageBox.warning(
                    self,
                    "Paste",
                    "Could not interpret the clipboard as a structure (try SMILES, InChI, or a MolBlock).",
                )
                return
        self._undo_stack.push(UndoPasteCellCommand(self, row, col, oid, clip))

    def _cancel_chunked_table_delete(self) -> None:
        self._table_delete_job_gen = int(getattr(self, "_table_delete_job_gen", 0)) + 1
        self._table_delete_ctx = None

    def _confirm_and_push_delete_rows(
        self, rows: list[int] | None = None, *, oids: frozenset[int] | None = None
    ) -> None:
        """Confirm then push UndoDeleteRowsCommand (shared by Edit and row header menu)."""
        if oids is None:
            rows = sorted({int(r) for r in (rows or [])})
            if not rows:
                QMessageBox.information(self, "Delete Selection", "No rows selected.")
                return
            oids = self._oids_for_row_indices(rows)
        n = len(oids)
        if n <= 0:
            QMessageBox.information(self, "Delete Selection", "No rows selected.")
            return
        title = "Delete Row" if n == 1 else "Delete Selection"
        msg = (
            "Delete this row? This cannot be undone except with Edit → Undo."
            if n == 1
            else f"Delete {n:,} selected rows? This cannot be undone except with Edit → Undo."
        )
        reply = QMessageBox.question(
            self,
            title,
            msg,
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        if n >= load_config().table_delete_batch_min:
            self._start_chunked_delete_prepare(oids)
            return
        cmd = UndoDeleteRowsCommand(self, oids=oids)
        if cmd.snapshot_count() == 0:
            QMessageBox.information(self, "Delete Selection", "No valid rows to delete.")
            return
        self._undo_stack.push(cmd)

    def _start_chunked_delete_prepare(self, oids: frozenset[int]) -> None:
        """Build undo snapshots in chunks so the UI stays responsive before delete runs."""
        self._cancel_chunked_table_delete()
        self._table_delete_job_gen = int(getattr(self, "_table_delete_job_gen", 0)) + 1
        gen = self._table_delete_job_gen
        total = len(oids)
        light = total >= load_config().table_delete_batch_min
        self._table_delete_ctx = {
            "gen": gen,
            "oids": frozenset(int(x) for x in oids),
            "light": light,
            "snapshots": [],
            "row_idx": 0,
            "total_rows": self._table_model.rowCount(),
        }
        self._set_selection_status(f"Preparing delete… (0/{total:,} rows)", pump=True)
        QTimer.singleShot(0, self._table_delete_prepare_step)

    def _table_delete_prepare_step(self) -> None:
        ctx = getattr(self, "_table_delete_ctx", None)
        if not ctx or ctx.get("gen") != getattr(self, "_table_delete_job_gen", -1):
            return
        kill: frozenset[int] = ctx["oids"]
        light = bool(ctx["light"])
        data_headers = [h for h in self.headers[2:] if h != "Structure"]
        model = self._table_model
        rows = model._rows  # noqa: SLF001
        total_rows = len(rows)
        total_delete = len(kill)
        idx = int(ctx["row_idx"])
        chunk = max(2000, load_config().table_delete_chunk_rows)
        end = min(idx + chunk, total_rows)
        snapshots: list[DeleteRowSnapshot] = ctx["snapshots"]
        found_before = len(snapshots)
        for j in range(idx, end):
            row = rows[j]
            oid = int(row.oid)
            if oid not in kill:
                continue
            cells = {h: str(row.values.get(h, "") or "") for h in data_headers}
            if light:
                snapshots.append(DeleteRowSnapshot(orig_row=j, oid=oid, cells=cells, light=True))
            else:
                pm = self.mols.get(oid)
                mol_copy = Chem.Mol(pm) if pm is not None else None
                png = model.structure_png_bytes(oid)
                spm = None if png else model.structure_pixmap_copy(oid)
                extra = model.extra_column_pixmaps_copy(oid) if total_delete <= 1 else {}
                snapshots.append(
                    DeleteRowSnapshot(
                        orig_row=j,
                        oid=oid,
                        cells=cells,
                        mol_copy=mol_copy,
                        structure_pixmap=spm,
                        structure_png=png,
                        extra_pixmaps=extra,
                        light=False,
                    )
                )
        ctx["row_idx"] = end
        found = len(snapshots) - found_before
        done_delete = len(snapshots)
        self._set_selection_status(
            f"Preparing delete… ({done_delete:,}/{total_delete:,} rows, scanned {end:,}/{total_rows:,})"
        )
        if end < total_rows:
            QTimer.singleShot(0, self._table_delete_prepare_step)
            return
        self._table_delete_ctx = None
        if not snapshots:
            QMessageBox.information(self, "Delete Selection", "No valid rows to delete.")
            self._set_selection_status("Delete cancelled — no matching rows.", pump=True)
            return
        if found < total_delete:
            # Rows may have been removed while preparing; keep only snapshots we collected.
            pass
        cmd = UndoDeleteRowsCommand(self, snapshots=snapshots)
        self._undo_stack.push(cmd)

    def edit_delete_selection(self) -> None:
        """Remove every row that has at least one selected cell."""
        self._confirm_and_push_delete_rows(oids=self._selected_oids_for_delete())

    def clear_table_after_confirm(self) -> None:
        """Clear the entire table only after explicit user confirmation."""
        reply = QMessageBox.question(
            self,
            "Clear Table",
            "Remove all rows, columns, filters, and molecules from this session?\n\n"
            "This cannot be undone.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self.clear_all()
            mark = getattr(self, "_mark_session_dirty", None)
            if callable(mark):
                mark()
            self.status_label.setText("Table cleared.")

    def _paste_clipboard_into_table_cell(
        self,
        row: int,
        col: int,
        oid: int | None,
        *,
        clip_text: str | None = None,
        quiet: bool = False,
    ) -> bool:
        if oid is None:
            return False
        if clip_text is not None:
            text = clip_text.strip()
        else:
            text = (QApplication.clipboard().text() or "").strip()
        if not text:
            if not quiet:
                QMessageBox.information(self, "Paste", "Clipboard is empty.")
            return False
        if col == CompoundTableModel.STRUCTURE_COL:
            mol = self._mol_from_structure_text(text)
            if mol is None:
                if not quiet:
                    QMessageBox.warning(
                        self,
                        "Paste",
                        "Could not interpret the clipboard as a structure (try SMILES, InChI, or a MolBlock).",
                    )
                return False
            self.mols[oid] = mol
            if "SMILES" in self.headers:
                try:
                    self._table_model.set_cell_text(oid, "SMILES", mol_to_canonical_smiles(mol))
                except Exception:
                    pass
            self._table_model.set_structure_pixmap(oid, None)
            self.calculate_global_bounds()
            self.apply_filters()
            if not quiet:
                self.status_label.setText("Structure updated from clipboard.")
            return True
        h = self.headers[col] if 0 <= col < len(self.headers) else ""
        if h and self._table_model.is_pixmap_data_column(h):
            mol = self._mol_from_structure_text(text)
            if mol is None:
                if not quiet:
                    QMessageBox.warning(
                        self,
                        "Paste",
                        "Could not interpret the clipboard as a structure (try SMILES, InChI, or a MolBlock).",
                    )
                return False
            try:
                smi = mol_to_canonical_smiles(mol)
            except Exception:
                smi = text
            self._table_model.set_backing_text(oid, h, smi)
            self._table_model.set_column_pixmap(oid, h, None)
            self.calculate_global_bounds()
            self.apply_filters()
            if not quiet:
                self.status_label.setText("Structure updated from clipboard.")
            return True
        if not self._table_model.column_accepts_text_edit(col):
            return False
        h = self.headers[col]
        self._table_model.set_cell_text(oid, h, text)
        self.calculate_global_bounds()
        self.apply_filters()
        if not quiet:
            self.status_label.setText("Cell updated from clipboard.")
        return True

    def show_table_menu(self, pos):
        idx = self.table.indexAt(pos)
        if not idx.isValid():
            return
        row, col = idx.row(), idx.column()
        t0 = self._table_model.cell_text(row, 0)
        oid = int(t0) if t0.isdigit() else None
        som_map_col = False
        som_header = ""
        if 0 <= col < len(self.headers):
            from ...som_prediction import is_som_map_header

            som_header = self.headers[col]
            som_map_col = is_som_map_header(som_header)

        menu = QMenu(self)
        browse_act = export_act = None
        if som_map_col:
            browse_act = menu.addAction("Browse")
            browse_act.setEnabled(
                oid is not None and callable(getattr(self, "open_som_browser_for_oid", None))
            )
            export_act = menu.addAction("Export")
            has_map = False
            if oid is not None:
                pm = self._table_model.column_pixmap_copy(int(oid), som_header)
                has_map = pm is not None and not pm.isNull()
            export_act.setEnabled(has_map)
            menu.addSeparator()

        packed_confs_b64 = None
        if 0 <= col < len(self.headers):
            hdr = self.headers[col]
            raw_cell = self._table_model.backing_value_for_row_header(row, hdr)
            packed_confs_b64 = resolve_blocks_b64_for_viewer(
                raw_cell, hdr, oid, getattr(self, "_confs_blocks_sidecar", {})
            )

        chem_col = self._column_eligible_for_table_chemistry_menu(row, col)
        mol_ctx = self._mol_for_table_context_menu(row, col) if chem_col else None

        sketch_act = view_conformers_act = view3d_act = view2d_act = render2d_act = (
            copy_smiles_act
        ) = None
        structure_menu = False
        if chem_col and mol_ctx is not None:
            sketch_act = menu.addAction("Open in Sketcher…")
            structure_menu = True
        if packed_confs_b64 is not None:
            view_conformers_act = menu.addAction("View Conformers…")
            structure_menu = True
        if chem_col and mol_ctx is not None and packed_confs_b64 is None:
            view3d_act = menu.addAction("View in 3D…")
            structure_menu = True
        if chem_col and mol_ctx is not None:
            view2d_act = menu.addAction("View in 2D…")
            render2d_act = menu.addAction(TOOL_RENDER_2D)
            render2d_act.setEnabled(oid is not None)
        if structure_menu:
            menu.addSeparator()

        can_copy, copy_text = self._copy_text_for_table_cell(row, col, oid)
        copy_act = menu.addAction("Copy")
        copy_act.setEnabled(can_copy)

        copy_smiles_txt = ""
        if chem_col and mol_ctx is not None:
            try:
                copy_smiles_txt = mol_to_canonical_smiles(mol_ctx).strip()
            except Exception:
                copy_smiles_txt = ""
        copy_smiles_act = None
        if chem_col:
            copy_smiles_act = menu.addAction("Copy as SMILES")
            copy_smiles_act.setEnabled(bool(copy_smiles_txt))

        can_paste = oid is not None and self._column_accepts_cell_paste(row, col)
        paste_act = menu.addAction("Paste")
        paste_act.setEnabled(can_paste)

        text_editable = self._table_model.column_accepts_text_edit(col)
        edit_act = clear_act = None
        if text_editable:
            menu.addSeparator()
            edit_act = menu.addAction("Edit Value…")
            clear_act = menu.addAction("Clear Value")

        mmp_ledger_act = None
        if 0 <= col < len(self.headers):
            from ...mmp_analysis import is_mmp_result_header

            if is_mmp_result_header(self.headers[col]):
                menu.addSeparator()
                mmp_ledger_act = menu.addAction("Transform Ledger")
                mmp_ledger_act.setToolTip(
                    "Open the MMP Transform Ledger for this session's MMP results."
                )

        action = menu.exec_(self.table.viewport().mapToGlobal(pos))
        if browse_act is not None and action == browse_act and oid is not None:
            opener = getattr(self, "open_som_browser_for_oid", None)
            if callable(opener):
                opener(int(oid))
        elif export_act is not None and action == export_act and oid is not None:
            exporter = getattr(self, "export_som_map_for_oid", None)
            if callable(exporter):
                exporter(int(oid), som_header)
        elif action == sketch_act and mol_ctx is not None:
            self.open_sketcher(mol_ctx)
        elif (
            view_conformers_act is not None
            and action == view_conformers_act
            and packed_confs_b64 is not None
        ):
            confs_col = "confs"
            if 0 <= col < len(self.headers):
                hdr = self.headers[col]
                if hdr in ("confs", "superpose"):
                    confs_col = hdr
            self.open_packed_conformer_viewer(
                packed_confs_b64,
                title="View Conformers",
                export_parent_oid=oid,
                export_confs_column=confs_col,
                source_oid=oid,
            )
        elif view3d_act is not None and action == view3d_act and mol_ctx is not None:
            self.open_molecule_3d(mol_ctx, source_oid=oid)
        elif view2d_act is not None and action == view2d_act and mol_ctx is not None:
            self.open_molecule_2d(mol_ctx, source_oid=oid)
        elif render2d_act is not None and action == render2d_act and mol_ctx is not None:
            self.run_render_2d_for_table_row(row, col)
        elif copy_smiles_act is not None and action == copy_smiles_act and copy_smiles_txt:
            QApplication.clipboard().setText(copy_smiles_txt)
            self.status_label.setText("Copied canonical SMILES to clipboard.")
        elif action == copy_act and can_copy:
            QApplication.clipboard().setText(copy_text)
        elif action == paste_act and can_paste:
            clip = (QApplication.clipboard().text() or "").strip()
            if not clip:
                QMessageBox.information(self, "Paste", "Clipboard is empty.")
            elif col == CompoundTableModel.STRUCTURE_COL:
                if self._mol_from_structure_text(clip) is None:
                    QMessageBox.warning(
                        self,
                        "Paste",
                        "Could not interpret the clipboard as a structure (try SMILES, InChI, or a MolBlock).",
                    )
                else:
                    self._undo_stack.push(UndoPasteCellCommand(self, row, col, int(oid), clip))
            elif (
                0 <= col < len(self.headers)
                and self._table_model.is_pixmap_data_column(self.headers[col])
                and chem_col
            ):
                if self._mol_from_structure_text(clip) is None:
                    QMessageBox.warning(
                        self,
                        "Paste",
                        "Could not interpret the clipboard as a structure (try SMILES, InChI, or a MolBlock).",
                    )
                else:
                    self._undo_stack.push(UndoPasteCellCommand(self, row, col, int(oid), clip))
            elif self._table_model.column_accepts_text_edit(col):
                self._undo_stack.push(UndoPasteCellCommand(self, row, col, int(oid), clip))
        elif edit_act is not None and action == edit_act:
            old_t = self._table_model.cell_text(row, col) or ""
            txt, ok = QInputDialog.getText(self, "Edit value", "New value:", text=old_t)
            if ok and oid is not None:
                h = self.headers[col]
                if txt != old_t:
                    self._undo_stack.push(UndoCellTextChangeCommand(self, int(oid), h, old_t, txt))
        elif clear_act is not None and action == clear_act:
            if oid is not None:
                h = self.headers[col]
                old_t = self._table_model.cell_text(row, col) or ""
                if old_t != "":
                    self._undo_stack.push(UndoCellTextChangeCommand(self, int(oid), h, old_t, ""))
        elif mmp_ledger_act is not None and action == mmp_ledger_act:
            opener = getattr(self, "open_mmp_transform_ledger_for_last_run", None)
            if callable(opener):
                opener()

    def _selected_smiles_strings(self) -> list[str]:
        """SMILES for PubChem/ChEMBL: canonical SMILES from any resolvable chemistry in each selected row."""
        if not self.headers:
            return []
        items = self.table.selectionModel().selectedIndexes()
        if not items:
            return []
        rows = sorted({i.row() for i in items})
        out: list[str] = []
        seen: set[str] = set()
        for r in rows:
            mol = self._mol_for_structure_row(r)
            if mol is None:
                continue
            try:
                smi = mol_to_canonical_smiles(mol).strip()
            except Exception:
                smi = ""
            if smi and smi not in seen:
                out.append(smi)
                seen.add(smi)
        return out

    def canonical_structure_key_from_smiles(self, smiles: str) -> str | None:
        """Canonical isomeric SMILES key for duplicate detection; ``None`` if not parseable."""
        return canonical_structure_key_from_smiles_fn(smiles)

    def existing_canonical_structure_keys(self) -> set[str]:
        """Canonical SMILES keys already present in the primary SMILES column (for de-duplication)."""
        keys: set[str] = set()
        h = self._canonical_smiles_header_for_updates()
        if not h or h not in self.headers:
            return keys
        ci = self.headers.index(h)
        for r in range(self._table_model.rowCount()):
            raw = (self._table_model.cell_text(r, ci) or "").strip()
            k = self.canonical_structure_key_from_smiles(raw)
            if k:
                keys.add(k)
        return keys

    def clear_all(self):
        self._confs_blocks_sidecar = {}
        self._som_browse_records = []
        if getattr(self, "_undo_stack", None) is not None:
            self._undo_stack.clear()
        try:
            from ...fingerprint_cache import clear as clear_fingerprint_cache

            clear_fingerprint_cache()
        except Exception:
            log_swallowed_exception(logger, "fingerprint_cache.clear failed during clear_all")
        try:
            from ...microstate_cache import clear as clear_microstate_cache

            clear_microstate_cache()
        except Exception:
            log_swallowed_exception(logger, "microstate_cache.clear failed during clear_all")
        self._table_model.clear()
        if getattr(self, "_table_stack", None) is not None:
            self._table_stack.setCurrentIndex(1)
        self.zoomed_ids = set()
        for f in self.filters:
            f.deleteLater()
        self.filters, self.headers, self.mols, self.global_bounds = [], [], {}, {}
        self._logarithmic_columns = set()
        self.next_oid = 0
        self._structure_field_override = None
        self._export_prep = None
        self._export_busy = False
        self._render2d_queue = None
        self._pending_session_table_layout = None
        self._pending_session_workspace_layout = None
        self._pending_session_column_order = None
        self._restore_render2d_batch_environment()
        self._session_restore_ctx = None
        abort_csv = getattr(self, "_abort_csv_session_load", None)
        if callable(abort_csv):
            abort_csv()
        else:
            self._csv_session_ctx = None
        self._session_load_generation = int(getattr(self, "_session_load_generation", 0)) + 1
        self._invalidate_substructure_async_jobs()
        self._sqlite_rebuild_gen = int(getattr(self, "_sqlite_rebuild_gen", 0)) + 1
        self._sqlite_rebuild_pending_filters = False
        self._pending_batches = []
        self._processing_batches = False
        self._last_batch_received = False
        self._set_ingest_loading(False)
        self._ingest_sqlite_bulk_active = False
        self._ingest_sqlite_paused_dirty = False
        self._ingest_sqlite_bulk_headers = None
        if getattr(self, "_sqlite_store", None) is not None:
            try:
                self._sqlite_rebuild_in_progress = True
                self._sqlite_store.rebuild(["ID_HIDDEN", "Structure"], [])
                self._sqlite_store_dirty = False
            except Exception:
                log_swallowed_exception(logger, "sqlite_store.rebuild failed during clear_all")
            finally:
                self._sqlite_rebuild_in_progress = False
        self._structures_queued = 0
        self._import_progress_active = False
        self._import_render_done = 0
        self._import_render_goal = 0
        self._import_building_progress_shown = False
        self._clear_tool_progress()
        self._session_sort = None
        self._selected_oids_override = None

    def _migrate_legacy_confs_cells_to_sidecar(self) -> None:
        """Move embedded v1 conformer payloads out of ``confs`` / ``superpose`` cells into ``_confs_blocks_sidecar``."""
        sc = getattr(self, "_confs_blocks_sidecar", None)
        if sc is None:
            self._confs_blocks_sidecar = {}
            sc = self._confs_blocks_sidecar
        cols = [c for c in ("confs", "superpose") if c in self.headers]
        if not cols:
            return
        n = self._table_model.rowCount()
        for r in range(n):
            t0 = self._table_model.cell_text(r, 0)
            if not t0.isdigit():
                continue
            oid = int(t0)
            for col in cols:
                raw = self._table_model.backing_value_for_row_header(r, col)
                light, b64 = demote_v1_cell_to_sidecar(raw, col)
                if b64 is not None:
                    sc[(oid, col)] = b64
                    if light != raw:
                        self._table_model.set_cell_text(oid, col, light)

    def _confs_sidecar_discard_oids(self, oids: list[int]) -> None:
        sc = getattr(self, "_confs_blocks_sidecar", None)
        if not sc or not oids:
            return
        dead = {int(o) for o in oids}
        for k in list(sc.keys()):
            if k[0] in dead:
                del sc[k]

    def _confs_sidecar_copy_for_new_row(self, src_oid: int, dst_oid: int) -> None:
        sc = getattr(self, "_confs_blocks_sidecar", None)
        if not sc:
            return
        for col in ("confs", "superpose"):
            b = sc.get((int(src_oid), col))
            if b:
                sc[(int(dst_oid), col)] = b

    def _export_cell_text(self, row: int, col: int) -> str:
        """Cell text for export: rehydrate ``confs`` / ``superpose`` so files stay self-contained."""
        if col == 1:
            return ""
        h = self.headers[col] if 0 <= col < len(self.headers) else ""
        if h in ("confs", "superpose"):
            raw = self._table_model.backing_value_for_row_header(row, h)
            t0 = self._table_model.cell_text(row, 0)
            oid = int(t0) if t0.isdigit() else -1
            if oid >= 0:
                sc = getattr(self, "_confs_blocks_sidecar", {}) or {}
                return rehydrate_v1_confs_cell(raw, h, oid, sc)
        return (self._table_cell_text(row, col) or "").strip()

    def _on_selection_browser_dialog_destroyed(self, *_args) -> None:
        from ..qt_widget_utils import qobject_is_deleted

        if qobject_is_deleted(self):
            return
        try:
            sender = self.sender()
        except RuntimeError:
            return
        current = getattr(self, "_selection_browser_dialog", None)
        if sender is not None and current is not None and current is not sender:
            return
        self._selection_browser_dialog = None

    def open_selection_browser(self) -> None:
        """Open modeless dialog to walk selected rows with structure preview."""
        from ..selection_browser import SelectionBrowserDialog, SelectionBrowserWidget

        for w in self.iter_docked_plot_widgets():
            if isinstance(w, SelectionBrowserWidget):
                mgr = self._workspace()
                if mgr is not None:
                    pane = mgr.pane_for_widget(w)
                    if pane is not None:
                        mgr.set_preferred_pane(pane)
                self.show_docked_plot_panel()
                w.refresh_from_app(preserve_position=True)
                w.raise_()
                self.status_label.setText("Browser: focused in workspace pane.")
                return

        def _factory():
            return SelectionBrowserDialog(self)

        reuse_or_show_modeless_singleton(
            self,
            "_selection_browser_dialog",
            _factory,
            self._on_selection_browser_dialog_destroyed,
            on_reused_visible=lambda dlg: dlg.refresh_from_app(preserve_position=True),
        )
