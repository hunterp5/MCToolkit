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
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with mctoolkit.  If not, see <https://www.gnu.org/licenses/>.

"""Background rebuild of the SQLite table mirror."""

from __future__ import annotations

import logging

from PySide6.QtCore import QRunnable

from ..storage.sqlite_table_store import SqliteTableStore
from ..platform_support.tool_progress import ToolProgressState, report_tool_progress
from .signals import SqliteRebuildSignals

logger = logging.getLogger(__name__)

_WRITE_CHUNK = 2000


class SqliteRebuildWorker(QRunnable):
    """Build a fresh SQLite mirror off the UI thread.

    Prefer GUI chunk-writes into *db_path* followed by ``stream_finalize=True``
    (no full in-RAM *entries* list). Passing *entries* still streams inserts
    here for tests and small rebuilds.
    """

    def __init__(
        self,
        job_gen: int,
        headers: list[str],
        entries: list[tuple[int, dict[str, str]]] | None,
        db_path: str,
        signals: SqliteRebuildSignals,
        *,
        stream_finalize: bool = False,
        progress_state: ToolProgressState | None = None,
    ) -> None:
        super().__init__()
        self.job_gen = job_gen
        self.headers = headers
        self.entries = entries
        self.db_path = db_path
        self.signals = signals
        self.stream_finalize = bool(stream_finalize)
        self.progress_state = progress_state
        self._progress_throttle = [0, 0.0]

    def _emit_progress(self, message: str, done: int, total: int) -> None:
        report_tool_progress(
            message=message,
            done=int(done),
            total=max(1, int(total)),
            progress_state=self.progress_state,
            throttle=self._progress_throttle,
        )

    def run(self) -> None:
        try:
            store = SqliteTableStore(self.db_path)
            if self.stream_finalize:
                self._emit_progress("Indexing table…", 1, 1)
                store.finish_stream_rebuild()
            else:
                entries = list(self.entries or [])
                n = len(entries)
                store.start_stream_rebuild(self.headers)
                if n == 0:
                    self._emit_progress("Indexing table…", 1, 1)
                else:
                    for i in range(0, n, _WRITE_CHUNK):
                        chunk = entries[i : i + _WRITE_CHUNK]
                        store.append_stream_rows(chunk)
                        done = min(i + len(chunk), n)
                        self._emit_progress("Indexing table…", done, n)
                store.finish_stream_rebuild()
                self._emit_progress("Indexing table…", max(n, 1), max(n, 1))
            store.close()
            self.signals.finished.emit(self.job_gen, self.db_path)
        except Exception as e:
            logger.exception("SqliteRebuildWorker failed")
            self.signals.failed.emit(self.job_gen, str(e))
