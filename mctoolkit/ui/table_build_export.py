# This file is part of MCToolkit.
# Copyright (C) 2026 Hunter Picard
#
# MCToolkit is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# MCToolkit is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with MCToolkit. If not, see <https://www.gnu.org/licenses/>.

from __future__ import annotations

import re
import threading
from contextlib import nullcontext
from typing import Any, Protocol

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QFileDialog, QMessageBox

from ..platform_support.config import load_config
from ..table.table_file_formats import TABLE_OPEN_FILTER, TABLE_SAVE_FILTER
from ..workers import ExportWorker, UniversalLoadWorker
from .strings import LOADING_DETAIL_APPEND, LOADING_DETAIL_READING_DISK


class TableBuildExportState(Protocol):
    """Export snapshot cursor and Open/Import structure-choice event."""

    _export_busy: bool
    _export_prep: dict | None
    _structure_choice_event: Any

    def _export_cell_text(self, row: int, col: int) -> str: ...
    def _visual_logical_columns(self) -> list: ...
    def _selected_oids_set(self) -> set: ...
    def logical_row_for_oid(self, oid: int) -> int: ...
    def clear_all(self) -> None: ...


class TableBuildExport:
    """Open/import file dialogs and snapshot export owned by TableBuildPipeline."""

    def open_file_dialog(self):
        path, _ = QFileDialog.getOpenFileName(self._app, "Open File", "", TABLE_OPEN_FILTER)
        if path:
            self.load_file(path)

    def open_import_file_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self._app, "Import Data", "", TABLE_OPEN_FILTER)
        if path:
            self.import_file(path)

    def load_file(self, path: str) -> None:
        self._app._ingest_append_mode = False
        self._app._structure_field_override = None
        self._app._session_mutation_paused = True
        self._app._pending_session_clean_on_ready = True
        self._app.clear_all()
        self._apply_table_only_layout_for_file_load()
        self._app._set_ingest_loading(True)
        self._app._structures_queued = 0
        self._app._import_building_progress_shown = False
        self._app._set_workspace_stack_index(0)
        self._app._loading_detail.setText(LOADING_DETAIL_READING_DISK)
        self._app.status_label.setText("Reading file…")
        self._ensure_structure_choice_event().set()
        batch_size = load_config().ingest_worker_batch_size
        self._app.process_queue.enqueue(
            f"Open file: {path}",
            lambda ev, p=path, s=self._app.signals, sce=self._app._structure_choice_event, bs=batch_size: (
                UniversalLoadWorker(
                    p, s, batch_size=bs, cancel_event=ev, structure_choice_event=sce
                )
            ),
        )

    def _apply_table_only_layout_for_file_load(self) -> None:
        """Give the table the full workspace when replacing the session from a file."""
        from .main_window.workspace_layout import LAYOUT_TABLE_ONLY

        mgr = getattr(self._app, "_workspace_layout", None)
        if mgr is None or mgr.layout_id == LAYOUT_TABLE_ONLY:
            return
        apply = getattr(self._app, "apply_workspace_layout", None)
        if callable(apply):
            apply(LAYOUT_TABLE_ONLY)

    def import_file(self, path: str) -> None:
        """Load molecules from disk and append them to the current table (merge columns as needed)."""
        self._app._pending_batches = []
        self._app._processing_batches = False
        self._app._last_batch_received = False
        self._app._structure_field_override = None
        self._app._ingest_append_mode = True
        self._app._pending_session_clean_on_ready = False
        mark = getattr(self._app, "_mark_session_dirty", None)
        if callable(mark):
            mark()
        self._app._set_ingest_loading(True)
        self._app._structures_queued = 0
        self._app._import_building_progress_shown = False
        self._app._set_workspace_stack_index(0)
        self._app._loading_detail.setText(LOADING_DETAIL_APPEND)
        self._app.status_label.setText("Importing…")
        self._ensure_structure_choice_event().set()
        batch_size = load_config().ingest_worker_batch_size
        self._app.process_queue.enqueue(
            f"Import data: {path}",
            lambda ev, p=path, s=self._app.signals, sce=self._app._structure_choice_event, bs=batch_size: (
                UniversalLoadWorker(
                    p, s, batch_size=bs, cancel_event=ev, structure_choice_event=sce
                )
            ),
        )

    def _ensure_structure_choice_event(self) -> threading.Event:
        ev = getattr(self._app, "_structure_choice_event", None)
        if ev is None:
            ev = threading.Event()
            ev.set()
            self._app._structure_choice_event = ev
        return ev

    def _merge_import_headers(self, incoming: list[str]) -> None:
        """Extend ``self.headers`` / the table model with columns from an appended file."""
        old_tail = list(self._app.headers[2:]) if len(self._app.headers) > 2 else []
        inc_tail = list(incoming[2:]) if len(incoming) > 2 else []
        seen = set(old_tail)
        merged_tail = list(old_tail)
        for h in inc_tail:
            if h not in seen:
                seen.add(h)
                merged_tail.append(h)
        self._app.table.setSortingEnabled(False)
        old_set = set(old_tail)
        for h in merged_tail:
            if h not in old_set:
                nc = self._app._table_model.columnCount()
                self._app._table_model.insert_column_at(nc, h, None)
                old_set.add(h)
        self._app.headers = ["ID_HIDDEN", "Structure"] + merged_tail

    def run_export(self, selected=False):
        if self._app._table_model.rowCount() == 0:
            return
        if getattr(self._app, "_export_busy", False):
            QMessageBox.warning(self._app, "Export", "An export is already in progress.")
            return
        vis_cols = self._app._visual_logical_columns()
        ordered_headers = [self._app.headers[i] for i in vis_cols if i < len(self._app.headers)]
        headers = ["ID_HIDDEN", "Structure"] + [
            h for h in ordered_headers if h not in ("ID_HIDDEN", "Structure")
        ]
        if selected:
            oids = sorted((int(o) for o in self._app._selected_oids_set()))
            if not oids:
                QMessageBox.information(
                    self._app,
                    "Export Selected",
                    "No rows are selected. Select one or more rows in the table first.",
                )
                return
            oids_list = oids
        else:
            oids_list = list(self._app._table_model.all_oids_in_order())
        path, sel_f = QFileDialog.getSaveFileName(self._app, "Export Data", "", TABLE_SAVE_FILTER)
        if path:
            ext = ""
            m = re.search("\\(([^)]+)\\)", sel_f or "")
            if m:
                tok = (m.group(1).split() or [""])[0]
                ext = tok.replace("*", "").strip()
            if not ext:
                ext = "." + path.split(".")[-1] if "." in path else ""
            if not ext:
                ext = ".sdf"
            if not path.lower().endswith(ext.lower()):
                path += ext
            h_map = {h: i for i, h in enumerate(self._app.headers)}
            chunk = max(256, int(load_config().ingest_gui_chunk_size))
            self._app._export_busy = True
            self._app._export_prep = {
                "path": path,
                "ext": ext,
                "headers": headers,
                "h_map": h_map,
                "oids": oids_list,
                "cells": {},
                "idx": 0,
                "chunk": chunk,
                "cols": [h for h in headers if h in self._app.headers],
            }
            self._app._on_tool_progress("Preparing export…", 0, max(len(oids_list), 1))
            QTimer.singleShot(0, self._export_snapshots_continue)

    def _export_snapshots_continue(self) -> None:
        prep = self._app._export_prep
        if not prep:
            return
        try:
            oids = prep["oids"]
            h_map = prep["h_map"]
            cols = prep["cols"]
            n = len(oids)
            chunk = prep["chunk"]
            start = prep["idx"]
            end = min(start + chunk, n)
            perf = getattr(self._app, "_perf", None)
            scope = perf.track if perf is not None else lambda *_args, **_kwargs: nullcontext()
            with scope("export.snapshot_chunk"):
                for j in range(start, end):
                    oid = oids[j]
                    r = self._app.logical_row_for_oid(oid)
                    if r != -1:
                        prep["cells"][oid] = {
                            h: self._app._export_cell_text(r, h_map[h]) for h in cols
                        }
                    else:
                        prep["cells"][oid] = {h: "" for h in cols}
            prep["idx"] = end
            self._app._on_tool_progress("Preparing export…", end, max(n, 1))
            if end < n:
                QTimer.singleShot(0, self._export_snapshots_continue)
                return
            path = prep["path"]
            ext = prep["ext"]
            cells = prep["cells"]
            headers = prep["headers"]
            oids_out = list(prep["oids"])
            mols = self._app.mols
            self._app._export_prep = None
            self._app.process_queue.enqueue(
                f"Export to {path}",
                lambda ev, p=path, e=ext, m=mols, h=headers, d=cells, o=oids_out, s=self._app.signals: (
                    ExportWorker(p, e, m, h, d, s, cancel_event=ev, oids=o)
                ),
            )
        except Exception as e:
            self._app._export_prep = None
            self._app._export_busy = False
            self._app._clear_tool_progress()
            QMessageBox.warning(self._app, "Export", str(e))
            self._app.status_label.setText("Ready")
