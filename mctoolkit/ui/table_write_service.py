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

"""Chunked chemistry-tool column writeback and unique header naming."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from contextlib import suppress
from typing import Any, Protocol

from .chunked_table_write import ChunkedTableWriter


class ColumnWriteApi(Protocol):
    """Window forwards for naming and inserting result columns.

    Dialogs still call these on the facade. Declaring them here is what lets
    ``private_cross_module_access`` treat those calls as an admitted contract instead of
    undeclared reach, now that ``TableWriteService`` owns the bodies.
    """

    def _unique_table_column_names(self, bases: list[str]) -> list[str]: ...
    def _ensure_columns(self, col_names: list[str]) -> None: ...
    def _sync_global_bounds_for_headers(
        self, headers: list[str], *, refresh_filters: bool = False
    ) -> None: ...


class TableWriteHost(Protocol):
    """What column writeback needs from the window besides the table models.

    Filter-card and plot-axis refresh stay on the window: those widgets are built after
    this collaborator, so they cannot fit an 8-member contract here.
    """

    headers: list
    _table_model: Any
    table: Any
    status_label: Any
    global_bounds: dict
    progress: Any

    def _on_written_columns(
        self,
        headers: list[str],
        *,
        refresh_filters: bool = False,
        defer_bounds: bool = False,
    ) -> None: ...


class TableWriteService:
    """Owns ``on_calc_finished``, unique header names, and chunked result writeback."""

    def __init__(self, app: TableWriteHost) -> None:
        self._app = app
        self._calc_writer = None

    def _unique_table_column_names(self, bases: list[str]) -> list[str]:
        """Return column header names; append `` (n)`` when a name already exists in the table."""
        out: list[str] = []
        used = set(self._app.headers)
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
        app = self._app
        if not app.headers:
            app.headers = ["ID_HIDDEN", "Structure", "SMILES"]
            app._table_model.set_headers(list(app.headers))
            app.table.setColumnHidden(0, True)
        existing = {h: i for i, h in enumerate(app.headers)}
        to_add = [h for h in col_names if h not in existing]
        if to_add:
            col_at = len(app.headers)
            app.headers.extend(to_add)
            app._table_model.insert_columns_at(col_at, to_add, None)

    def _sync_global_bounds_for_headers(
        self, headers: list[str], *, refresh_filters: bool = False
    ) -> None:
        """Refresh slider min/max for specific columns without scanning the whole table."""
        if not headers:
            return
        app = self._app
        app._table_model.refresh_numeric_bounds_for_headers(headers)
        cache = app._table_model._numeric_bounds_cache
        if cache is not None:
            for h in headers:
                if h in cache:
                    app.global_bounds[h] = cache[h]
                else:
                    app.global_bounds.pop(h, None)
        app._on_written_columns(headers, refresh_filters=refresh_filters)

    def _calc_writeback_async_min_rows(self) -> int:
        from ..platform_support.config import load_config

        return max(500, int(load_config().table_selection_chunk_rows))

    def _calc_writeback_chunk_rows(self) -> int:
        from ..platform_support.config import load_config

        cfg = load_config()
        return max(250, min(int(cfg.ingest_gui_chunk_size), int(cfg.table_selection_chunk_rows)))

    def _apply_calc_bulk_rows(
        self, calc_h: list[str], bulk_rows: list[tuple[int, dict[str, str]]]
    ) -> None:
        if not bulk_rows:
            return
        model = self._app._table_model
        if len(calc_h) == 1:
            hdr = calc_h[0]
            model.set_column_text_by_oids(
                hdr,
                [(oid, values[hdr]) for oid, values in bulk_rows],
            )
            return
        model.apply_columns_values_bulk(calc_h, bulk_rows)

    def _finalize_calc_writeback(
        self,
        calc_h: list[str],
        new_h: list[str],
        *,
        on_complete: Callable[[list[str]], None] | None = None,
    ) -> None:
        app = self._app
        if app._table_model.rowCount() >= 5000:
            dirty = {h for h in calc_h if h in app._table_model._bounds_data_headers()}
            if dirty:
                app._table_model._mark_numeric_bounds_dirty(dirty)
            app._on_written_columns(calc_h, defer_bounds=True)
        else:
            self._sync_global_bounds_for_headers(calc_h, refresh_filters=bool(new_h))
        for header_name in calc_h:
            app._table_model.apply_favorable_score_column_coloring(header_name)
        app.table.setSortingEnabled(False)
        with suppress(RuntimeError):
            app.table.setUpdatesEnabled(True)
        app.status_label.setText(app.progress._consume_partial_results_notice() or "Done.")
        if on_complete is not None:
            on_complete(list(calc_h))

    def _start_calc_writeback(
        self,
        calc_h: list[str],
        new_h: list[str],
        bulk_rows: list[tuple[int, dict[str, str]]],
        *,
        on_complete: Callable[[list[str]], None] | None = None,
        write_job_id: str | None = None,
    ) -> None:
        """Apply result rows in GUI-budgeted chunks, yielding between each one."""
        app = self._app
        progress = app.progress

        def write_chunk(start: int, end: int, _is_last: bool) -> None:
            self._apply_calc_bulk_rows(calc_h, bulk_rows[start:end])

        def on_progress(done: int, total: int) -> None:
            on_prog = getattr(progress, "_on_tool_progress", None)
            if callable(on_prog):
                on_prog("Writing results…", done, total, job_id=write_job_id)
            else:
                app.status_label.setText(f"Writing results… ({done:,}/{total:,})")

        def on_done() -> None:
            self._calc_writer = None
            finish = getattr(progress, "_finish_tool_progress", None)
            if callable(finish):
                finish("Writing results", status_message=None, job_id=write_job_id)
            self._finalize_calc_writeback(calc_h, new_h, on_complete=on_complete)

        writer = self._calc_writer
        if writer is not None:
            writer.cancel()
        self._calc_writer = ChunkedTableWriter(
            table=app.table,
            total=len(bulk_rows),
            chunk=self._calc_writeback_chunk_rows(),
            write_chunk=write_chunk,
            on_progress=on_progress,
            on_done=on_done,
        )
        self._calc_writer.start()

    def on_calc_finished(
        self,
        res,
        calc_h,
        *,
        finish_progress: bool = True,
        progress_label: str | None = None,
        on_complete: Callable[[list[str]], None] | None = None,
        immediate: bool = False,
        job_id: str | None = None,
    ) -> list[str]:
        """Write tool results into the table, adding columns as needed.

        Colliding names are rewritten to ``Name (1)``, ``Name (2)``, … via
        :meth:`_unique_table_column_names`, except ``pKa`` and ``pI``: those
        Uni-pKa metadata columns are updated in place when they already exist.
        ``pI`` is only written when Predict pKa is run with isoelectric point enabled.
        Returns the final header list written. Large result sets are applied in
        GUI-budgeted chunks unless *immediate* is set (cheap in-memory table
        transforms such as Split/Join/Random). ``on_complete`` runs after values
        (and coloring) land.
        """
        app = self._app
        progress = app.progress
        calc_h = [str(h) for h in (calc_h or [])]
        if not calc_h:
            if finish_progress:
                progress._finish_tool_progress(
                    progress_label, status_message=None, job_id=job_id
                )
            app.status_label.setText(progress._consume_partial_results_notice() or "Done.")
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

        app.table.setSortingEnabled(False)
        with suppress(RuntimeError):
            app.table.setUpdatesEnabled(False)
        h_map = {h: i for i, h in enumerate(app.headers)}
        new_h = [h for h in calc_h if h not in h_map]
        if new_h:
            col_at = len(app.headers)
            app.headers.extend(new_h)
            app._table_model.insert_columns_at(col_at, new_h, None)
        bulk_rows = [
            (int(oid), {h: str(row_d.get(h, "N/A")) for h in calc_h}) for oid, row_d in res
        ]
        async_min = self._calc_writeback_async_min_rows()
        if not immediate and bulk_rows and len(bulk_rows) >= async_min:
            write_job_id = str(uuid.uuid4())[:8]
            begin = getattr(progress, "_begin_tool_progress", None)
            if callable(begin):
                begin("Writing results", len(bulk_rows), job_id=write_job_id)
            with suppress(RuntimeError):
                app.table.setUpdatesEnabled(True)
            self._start_calc_writeback(
                list(calc_h),
                list(new_h),
                bulk_rows,
                on_complete=on_complete,
                write_job_id=write_job_id,
            )
            return list(calc_h)

        if finish_progress:
            progress._finish_tool_progress(
                progress_label, status_message=None, job_id=job_id
            )
        try:
            self._apply_calc_bulk_rows(calc_h, bulk_rows)
            self._finalize_calc_writeback(calc_h, new_h, on_complete=on_complete)
        except Exception:
            with suppress(RuntimeError):
                app.table.setUpdatesEnabled(True)
            raise
        return list(calc_h)
