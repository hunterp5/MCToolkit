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

"""Shared table column naming, inserts, and chemistry-tool writeback."""

from __future__ import annotations

from collections.abc import Callable

from PyQt5.QtCore import QTimer

from ..widgets import CategoryFilterCard, FilterCard, TextFilterCard


class ColumnWriteMixin:
    def _unique_table_column_names(self, bases: list[str]) -> list[str]:
        """Return column header names; append `` (n)`` when a name already exists in the table."""
        out: list[str] = []
        used = set(self.headers)
        for raw in bases:
            base = (raw or "").strip() or "Column"
            col = base
            if col in used:
                cnt = 1
                while f"{base} ({cnt})" in used:
                    cnt += 1
                col = f"{base} ({cnt})"
            out.append(col)
            used.add(col)
        return out

    def _ensure_columns(self, col_names: list[str]) -> None:
        """Ensure the table has these headers (adds columns to the right if needed)."""
        if not self.headers:
            self.headers = ["ID_HIDDEN", "Structure", "SMILES"]
            self._table_model.set_headers(list(self.headers))
            self.table.setColumnHidden(0, True)
        existing = {h: i for i, h in enumerate(self.headers)}
        to_add = [h for h in col_names if h not in existing]
        if to_add:
            col_at = len(self.headers)
            self.headers.extend(to_add)
            self._table_model.insert_columns_at(col_at, to_add, None)

    def _sync_global_bounds_for_headers(
        self, headers: list[str], *, refresh_filters: bool = False
    ) -> None:
        """Refresh slider min/max for specific columns without scanning the whole table."""
        if not headers:
            return
        self._table_model.refresh_numeric_bounds_for_headers(headers)
        cache = self._table_model._numeric_bounds_cache
        if cache is not None:
            for h in headers:
                if h in cache:
                    self.global_bounds[h] = cache[h]
                else:
                    self.global_bounds.pop(h, None)
        if refresh_filters:
            cols = self._filterable_data_column_names()
            for f in self.filters:
                if isinstance(f, FilterCard):
                    f.update_prop_list(list(self.global_bounds.keys()))
                elif isinstance(f, (TextFilterCard, CategoryFilterCard)):
                    f.update_prop_list(cols)
        self._refresh_active_plot_axis_columns()
        refresh_search = getattr(self, "_refresh_table_search_column_combos", None)
        if callable(refresh_search):
            refresh_search()

    def _calc_writeback_async_min_rows(self) -> int:
        from ...platform_support.config import load_config

        return max(500, int(load_config().table_selection_chunk_rows))

    def _calc_writeback_chunk_rows(self) -> int:
        from ...platform_support.config import load_config

        cfg = load_config()
        return max(250, min(int(cfg.ingest_gui_chunk_size), int(cfg.table_selection_chunk_rows)))

    def _apply_calc_bulk_rows(
        self, calc_h: list[str], bulk_rows: list[tuple[int, dict[str, str]]]
    ) -> None:
        if not bulk_rows:
            return
        if len(calc_h) == 1:
            hdr = calc_h[0]
            self._table_model.set_column_text_by_oids(
                hdr,
                [(oid, values[hdr]) for oid, values in bulk_rows],
            )
            return
        self._table_model.apply_columns_values_bulk(calc_h, bulk_rows)

    def _finalize_calc_writeback(
        self,
        calc_h: list[str],
        new_h: list[str],
        *,
        on_complete: Callable[[list[str]], None] | None = None,
    ) -> None:
        if self._table_model.rowCount() >= 5000:
            dirty = {h for h in calc_h if h in self._table_model._bounds_data_headers()}
            if dirty:
                self._table_model._mark_numeric_bounds_dirty(dirty)
            self.schedule_calculate_global_bounds()
        else:
            self._sync_global_bounds_for_headers(calc_h, refresh_filters=bool(new_h))
        for header_name in calc_h:
            self._table_model.apply_favorable_score_column_coloring(header_name)
        self.table.setSortingEnabled(False)
        try:
            self.table.setUpdatesEnabled(True)
        except Exception:
            pass
        self.status_label.setText(self._consume_partial_results_notice() or "Done.")
        if on_complete is not None:
            on_complete(list(calc_h))

    def _calc_write_step(self) -> None:
        ctx = getattr(self, "_calc_write_ctx", None)
        if not ctx or ctx.get("gen") != getattr(self, "_calc_write_gen", -1):
            return
        bulk_rows: list[tuple[int, dict[str, str]]] = ctx["bulk_rows"]
        calc_h: list[str] = ctx["calc_h"]
        idx = int(ctx["idx"])
        chunk = int(ctx["chunk"])
        n = len(bulk_rows)
        end = min(idx + chunk, n)
        batch = bulk_rows[idx:end]
        try:
            self.table.setUpdatesEnabled(False)
        except Exception:
            pass
        try:
            self._apply_calc_bulk_rows(calc_h, batch)
        finally:
            try:
                self.table.setUpdatesEnabled(True)
            except Exception:
                pass
        ctx["idx"] = end
        on_prog = getattr(self, "_on_tool_progress", None)
        if callable(on_prog):
            on_prog("Writing results…", end, n)
        else:
            self.status_label.setText(f"Writing results… ({end:,}/{n:,})")
        if end < n:
            QTimer.singleShot(0, self._calc_write_step)
            return
        self._calc_write_ctx = None
        finish = getattr(self, "_finish_tool_progress", None)
        if callable(finish):
            finish("Writing results", status_message=None)
        self._finalize_calc_writeback(
            calc_h,
            list(ctx.get("new_h") or []),
            on_complete=ctx.get("on_complete"),
        )

    def on_calc_finished(
        self,
        res,
        calc_h,
        *,
        finish_progress: bool = True,
        progress_label: str | None = None,
        on_complete: Callable[[list[str]], None] | None = None,
    ) -> list[str]:
        """Write tool results into the table, adding columns as needed.

        Colliding names are rewritten to ``Name (1)``, ``Name (2)``, … via
        :meth:`_unique_table_column_names`, except ``pKa`` and ``pI``: those
        Uni-pKa metadata columns are updated in place when they already exist.
        ``pI`` is only written when Predict pKa is run with isoelectric point enabled.
        Returns the final header list written. Large result sets are applied in
        GUI-budgeted chunks; ``on_complete`` runs after values (and coloring) land.
        """
        calc_h = [str(h) for h in (calc_h or [])]
        if not calc_h:
            if finish_progress:
                self._finish_tool_progress(progress_label, status_message=None)
            self.status_label.setText(self._consume_partial_results_notice() or "Done.")
            if on_complete is not None:
                on_complete([])
            return []

        shared = {"pKa", "pI"}
        to_unique = [h for h in calc_h if h not in shared]
        unique_h = self._unique_table_column_names(to_unique) if to_unique else []
        rename = {old: new for old, new in zip(to_unique, unique_h) if old != new}
        calc_h = [rename.get(h, h) for h in calc_h]
        if rename:
            remapped: list[tuple[int, dict]] = []
            for oid, row_d in res:
                row_d = row_d or {}
                remapped.append(
                    (
                        int(oid),
                        {rename.get(str(k), str(k)): v for k, v in row_d.items()},
                    )
                )
            res = remapped

        self.table.setSortingEnabled(False)
        try:
            self.table.setUpdatesEnabled(False)
        except Exception:
            pass
        h_map = {h: i for i, h in enumerate(self.headers)}
        new_h = [h for h in calc_h if h not in h_map]
        if new_h:
            col_at = len(self.headers)
            self.headers.extend(new_h)
            self._table_model.insert_columns_at(col_at, new_h, None)
        bulk_rows = [
            (int(oid), {h: str(row_d.get(h, "N/A")) for h in calc_h}) for oid, row_d in res
        ]
        async_min = self._calc_writeback_async_min_rows()
        if bulk_rows and len(bulk_rows) >= async_min:
            self._calc_write_gen = int(getattr(self, "_calc_write_gen", 0)) + 1
            begin = getattr(self, "_begin_tool_progress", None)
            if callable(begin):
                begin("Writing results", len(bulk_rows))
            self._calc_write_ctx = {
                "gen": self._calc_write_gen,
                "bulk_rows": bulk_rows,
                "calc_h": list(calc_h),
                "new_h": list(new_h),
                "idx": 0,
                "chunk": self._calc_writeback_chunk_rows(),
                "on_complete": on_complete,
            }
            try:
                self.table.setUpdatesEnabled(True)
            except Exception:
                pass
            QTimer.singleShot(0, self._calc_write_step)
            return list(calc_h)

        if finish_progress:
            self._finish_tool_progress(progress_label, status_message=None)
        try:
            self._apply_calc_bulk_rows(calc_h, bulk_rows)
            self._finalize_calc_writeback(calc_h, new_h, on_complete=on_complete)
        except Exception:
            try:
                self.table.setUpdatesEnabled(True)
            except Exception:
                pass
            raise
        return list(calc_h)
