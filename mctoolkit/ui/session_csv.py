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

"""Legacy CSV session load path."""

from __future__ import annotations

import logging
import sys

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QMessageBox

from ..platform_support.tool_progress import format_overlay_progress_text
from ..storage import load_mols_from_parse_result
from ..workers.session_rows_parse import (
    CsvSessionParseResult,
    CsvSessionParseWorker,
    SessionRowsParseSignals,
)
from .strings import LOADING_DETAIL_SESSION
from .threadpool_access import start_runnable_on_app_pool

logger = logging.getLogger(__name__)


class SessionCsv:
    def _abort_csv_session_load(self) -> None:
        """Cancel an in-progress legacy session CSV load."""
        self._app._session_parse_busy = False
        self._app._csv_session_ctx = None

    def load_session_csv(self, path: str) -> None:
        """Load a session CSV exported by `_write_session_csv`.

        File I/O and SMILES parsing run off the GUI thread; table appends stay
        chunked on the GUI thread (same pattern as ``.mct`` restore).
        """
        self._app._session_mutation_paused = True
        self._app._pending_session_clean_on_ready = True
        self._app.clear_all()
        self._app._set_ingest_loading(True)
        self._app._set_workspace_stack_index(0)
        self._app._loading_detail.setText(LOADING_DETAIL_SESSION)
        self._app.status_label.setText("Loading session…")
        try:
            self._app.table.setUpdatesEnabled(False)
        except Exception:
            pass

        self._app._session_load_generation = (
            int(getattr(self._app, "_session_load_generation", 0)) + 1
        )
        gen = self._app._session_load_generation
        self._app._session_parse_busy = True
        self._app._loading_detail.setText("Parsing structures…")
        self._app.status_label.setText("Loading session… (parsing CSV)")
        signals = SessionRowsParseSignals(self._app)

        def _on_parsed(result, g=gen) -> None:
            self._on_csv_session_parsed(result, g)

        def _on_failed(message, g=gen) -> None:
            self._on_csv_session_parse_failed(message, g)

        worker = CsvSessionParseWorker(path, signals, gen)
        if "pytest" in sys.modules:
            conn = Qt.DirectConnection
            signals.finished.connect(_on_parsed, type=conn)
            signals.failed.connect(_on_failed, type=conn)
            self._bind_session_worker_progress(signals, conn, generation=gen)
            worker.run()
            self._drain_pending_session_load()
        else:
            conn = Qt.QueuedConnection
            signals.finished.connect(_on_parsed, type=conn)
            signals.failed.connect(_on_failed, type=conn)
            self._bind_session_worker_progress(signals, conn, generation=gen)
            start_runnable_on_app_pool(self._app, worker)

    def _on_csv_session_parse_failed(self, message: str, generation: int) -> None:
        if generation != getattr(self._app, "_session_load_generation", 0):
            return
        self._app._session_parse_busy = False
        self._app._csv_session_ctx = None
        self._app._session_awaiting_ready = False
        self._app._session_waiting_for_render = False
        self._app._session_mutation_paused = False
        self._app._pending_session_clean_on_ready = False
        self._session_reveal_workspace_atomic()
        QMessageBox.warning(self._app, "Open Session", message or "Session CSV parse failed.")

    def _on_csv_session_parsed(self, result: object, generation: int) -> None:
        if generation != getattr(self._app, "_session_load_generation", 0):
            return
        self._app._session_parse_busy = False
        if not isinstance(result, CsvSessionParseResult):
            self._on_csv_session_parse_failed("Invalid session CSV parse result.", generation)
            return
        cols = list(result.columns or [])
        if "SMILES" not in cols:
            cols = ["SMILES"] + cols
        self._app.headers = ["ID_HIDDEN", "Structure"] + cols
        self._app.table.setSortingEnabled(False)
        self._app._table_model.clear_rows()
        self._app._table_model.set_headers(list(self._app.headers))
        self._app.table.setColumnHidden(0, True)
        load_mols_from_parse_result(self._app, result)
        self._app._clear_filter_target_smiles_cache()
        self._app.global_bounds = {}
        self._app.next_oid = int(result.next_oid)
        prepared = list(result.prepared_rows or [])
        if not prepared:
            self._finalize_session_csv_load()
            return
        chunk = self._session_gui_chunk_size()
        self._app._csv_session_ctx = {
            "gen": generation,
            "prepared_rows": prepared,
            "idx": 0,
            "chunk": chunk,
            "loaded": 0,
        }
        n = len(prepared)
        text = format_overlay_progress_text("Loading session…", 0, n)
        self._app.status_label.setText(text)
        self._app._loading_detail.setText(text)
        QTimer.singleShot(0, self._load_session_csv_step)

    def _load_session_csv_step(self) -> None:
        ctx = getattr(self._app, "_csv_session_ctx", None)
        if not ctx or ctx.get("gen") != getattr(self._app, "_session_load_generation", 0):
            try:
                self._app.table.setUpdatesEnabled(True)
            except Exception:
                pass
            return
        prepared = ctx["prepared_rows"]
        i = int(ctx["idx"])
        chunk = int(ctx["chunk"])
        n = len(prepared)
        end = min(i + chunk, n)
        batch = prepared[i:end]
        if batch:
            self._app._table_model.append_rows_batch(batch)
        ctx["idx"] = end
        ctx["loaded"] = end
        text = format_overlay_progress_text("Loading session…", end, n)
        self._app.status_label.setText(text)
        self._app._loading_detail.setText(text)
        if end < n:
            QTimer.singleShot(0, self._load_session_csv_step)
            return
        self._app._csv_session_ctx = None
        self._app._loading_detail.setText(f"Session loaded ({n:,} row(s)).\nPreparing table…")
        self._finalize_session_csv_load()

    def _finalize_session_csv_load(self) -> None:
        self._app.table.setSortingEnabled(False)
        rows_n = self._app._table_model.rowCount()
        if getattr(self._app, "_sqlite_store", None) is not None:
            self._app._sqlite_store_dirty = True
            schedule = getattr(self._app, "_schedule_sqlite_rebuild", None)
            if callable(schedule) and rows_n > 0:
                schedule()
        self._app._session_hold_workspace_surfaces = True
        self._app._session_awaiting_ready = True
        self._app._session_waiting_for_render = False
        self._app._session_plot_wait_deadline = None
        detail = getattr(self._app, "_loading_detail", None)
        if detail is not None:
            try:
                detail.setText("Preparing filters…")
            except RuntimeError:
                pass
        self._app.calculate_global_bounds(on_complete=self._deferred_session_post_load_follow_up)
