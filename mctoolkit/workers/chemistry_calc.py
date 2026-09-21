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

"""QRunnable adapter for the custom calculator job."""

from __future__ import annotations

import logging
import threading

from PySide6.QtCore import QObject, QRunnable, Signal

from ..platform_support.exception_policy import log_swallowed_exception
from ..table.custom_calc_job import describe_custom_calc_error, evaluate_custom_calc_rows

logger = logging.getLogger(__name__)

__all__ = ["CustomCalcWorker", "describe_custom_calc_error"]


class CalcSignals(QObject):
    progress = Signal(str, int, int)
    finished = Signal(list)
    cancelled = Signal()
    error = Signal(str)


class CustomCalcWorker(QRunnable):
    def __init__(
        self,
        row_data,
        expression,
        signals,
        progress_signals=None,
        *,
        cancel_event=None,
        progress_state=None,
    ):
        super().__init__()
        self.row_data = row_data
        self.expression = expression
        self.signals = signals
        self.progress_signals = progress_signals
        self.progress_state = progress_state
        self.cancel_event = cancel_event if cancel_event is not None else threading.Event()
        self._stop_requested = False
        self._cancel_emitted = False

    def request_stop(self):
        self._stop_requested = True
        self.cancel_event.set()

    def run(self):
        def on_progress(message: str, done: int, total: int) -> None:
            from ..platform_support.tool_progress import report_tool_progress

            try:
                report_tool_progress(
                    message=message,
                    done=done,
                    total=max(1, int(total)),
                    progress_state=self.progress_state,
                    signals=self.progress_signals or self.signals,
                )
            except RuntimeError:
                log_swallowed_exception(logger, "CustomCalcWorker progress emit failed")

        try:
            results, cancelled = evaluate_custom_calc_rows(
                self.row_data,
                self.expression,
                cancel_event=self.cancel_event,
                on_progress=on_progress,
            )
            if cancelled:
                if not self._cancel_emitted:
                    self._cancel_emitted = True
                    self.signals.cancelled.emit()
                return
            self.signals.finished.emit(results)
        except Exception as exc:
            logger.exception("CustomCalcWorker failed")
            self.signals.error.emit(str(exc))
