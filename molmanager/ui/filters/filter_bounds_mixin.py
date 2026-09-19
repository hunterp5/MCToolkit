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

"""Global numeric bounds scans for filter cards and plot axes."""

from __future__ import annotations

import time

from PySide6.QtCore import QTimer

from ...platform_support.config import load_config
from .cards import CategoryFilterCard, FilterCard, SubstructureFilterCard, TextFilterCard


class FilterBoundsMixin:
    """Numeric min/max refresh for filter sliders (sync or chunked)."""

    def calculate_global_bounds(self, *, on_complete=None) -> None:
        """Scan numeric columns and refresh filter/plot axis bounds."""
        self._bounds_on_complete = on_complete
        self._bounds_chunk_gen = int(getattr(self, "_bounds_chunk_gen", 0)) + 1
        self._bounds_chunk_active = False
        n = self._table_model.rowCount()
        cfg = load_config()
        if n >= int(cfg.bounds_async_min_rows):
            self._begin_chunked_global_bounds()
            return
        self._apply_global_bounds_sync()
        self._finish_bounds_calculation()

    def _finish_bounds_calculation(self) -> None:
        """Invoke optional ingest/deferred callback or update status when bounds are ready."""
        cb = getattr(self, "_bounds_on_complete", None)
        self._bounds_on_complete = None
        if cb is not None:
            QTimer.singleShot(0, cb)
            return
        if hasattr(self, "status_label") and not getattr(self, "_render2d_batch_active", False):
            cur = self.status_label.text()
            if cur.startswith("Preparing filters"):
                n = self._table_model.rowCount()
                from ..strings import STATUS_READY_RENDER_2D

                self.status_label.setText(STATUS_READY_RENDER_2D if n else "Ready.")

    def _set_bounds_prep_progress(self, message: str) -> None:
        """Show bounds-prep progress on the loading page during ingest."""
        if getattr(self, "_ingest_prep_before_reveal", False) and hasattr(self, "_loading_detail"):
            self._loading_detail.setText(message)
        if hasattr(self, "status_label") and not getattr(self, "_render2d_batch_active", False):
            self.status_label.setText(message.replace("\n", " — "))

    def _apply_global_bounds_sync(self) -> None:
        self.global_bounds = self._table_model.numeric_bounds_by_column()
        self._refresh_bounds_on_filter_cards()

    def _refresh_bounds_on_filter_cards(self) -> None:
        data_cols = self._filterable_data_column_names()
        struct_srcs = None
        get_srcs = getattr(self, "chemistry_tool_structure_sources", None)
        if callable(get_srcs):
            struct_srcs = get_srcs()
        for f in self.filters:
            if isinstance(f, FilterCard):
                f.update_prop_list(list(self.global_bounds.keys()))
            elif isinstance(f, (TextFilterCard, CategoryFilterCard)):
                f.update_prop_list(data_cols)
            elif isinstance(f, SubstructureFilterCard) and struct_srcs is not None:
                f.set_structure_sources(struct_srcs)
        refresh_plot_axes = getattr(self, "_refresh_active_plot_axis_columns", None)
        if callable(refresh_plot_axes):
            refresh_plot_axes()

    def _begin_chunked_global_bounds(self) -> None:
        headers = self._table_model.list_bounds_data_headers()
        if not headers:
            self._apply_global_bounds_sync()
            self._finish_bounds_calculation()
            return
        self._bounds_chunk_active = True
        self._bounds_chunk_headers = headers
        self._bounds_chunk_col_i = 0
        self._bounds_chunk_row_i = 0
        self._bounds_chunk_acc: dict[str, dict] = {}
        gen = int(self._bounds_chunk_gen)
        self._set_bounds_prep_progress(f"Preparing filters…\n(0/{len(headers)} columns)")
        QTimer.singleShot(0, lambda g=gen: self._bounds_chunk_step(g))

    def _bounds_chunk_step(self, gen: int) -> None:
        if gen != int(getattr(self, "_bounds_chunk_gen", -1)):
            return
        if not getattr(self, "_bounds_chunk_active", False):
            return
        cfg = load_config()
        row_budget = int(cfg.bounds_chunk_rows)
        deadline = time.monotonic() + max(0.005, int(cfg.ingest_gui_time_budget_ms) / 1000.0)
        headers = self._bounds_chunk_headers
        ci = int(self._bounds_chunk_col_i)
        n_rows = self._table_model.rowCount()
        processed = 0
        while ci < len(headers) and processed < row_budget and time.monotonic() < deadline:
            header = headers[ci]
            start = int(self._bounds_chunk_row_i)
            remain = row_budget - processed
            end = min(start + remain, n_rows)
            acc = self._bounds_chunk_acc.get(header)
            self._bounds_chunk_acc[header] = self._table_model.merge_numeric_bounds_chunk(
                header, start, end, acc
            )
            processed += end - start
            if end >= n_rows:
                if header in self._bounds_chunk_acc and self._bounds_chunk_acc[header] is None:
                    self._bounds_chunk_acc.pop(header, None)
                ci += 1
                self._bounds_chunk_row_i = 0
            else:
                self._bounds_chunk_row_i = end
        self._bounds_chunk_col_i = ci
        if ci < len(headers):
            self._set_bounds_prep_progress(f"Preparing filters…\n({ci}/{len(headers)} columns)")
            QTimer.singleShot(0, lambda g=gen: self._bounds_chunk_step(g))
            return
        self._bounds_chunk_active = False
        self._table_model.install_numeric_bounds_cache(self._bounds_chunk_acc)
        self.global_bounds = dict(self._bounds_chunk_acc)
        self._refresh_bounds_on_filter_cards()
        self._finish_bounds_calculation()

    def schedule_calculate_global_bounds(self, *, delay_ms: int | None = None) -> None:
        """Debounce full-table bounds scans after bulk load/ingest (keeps UI responsive)."""
        timer = getattr(self, "_bounds_recalc_timer", None)
        if timer is None:
            return
        cfg = load_config()
        ms = int(delay_ms if delay_ms is not None else cfg.filter_debounce_default_ms)
        timer.stop()
        timer.start(max(0, ms))
