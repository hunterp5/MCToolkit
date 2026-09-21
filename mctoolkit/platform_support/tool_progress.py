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

"""Thread-safe tool progress for background workers (polled on the Qt GUI thread)."""

from __future__ import annotations

import threading
import time
from typing import Any


class ToolProgressState:
    """
    Updated from worker threads; read from a QTimer on the main window.

    Avoids relying on ``Signal`` delivery while the GIL is held by descriptor work.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._message = ""
        self._done = 0
        self._total = 1
        self._active = False

    def begin(self, message: str, total: int) -> None:
        with self._lock:
            self._message = str(message or "")
            self._done = 0
            self._total = max(1, int(total))
            self._active = True

    def update(self, message: str, done: int, total: int | None = None) -> None:
        with self._lock:
            self._message = str(message or "")
            self._done = max(0, int(done))
            if total is not None:
                tot = int(total)
                # Negative total is indeterminate (status text only, no 0%).
                self._total = tot if tot < 0 else max(1, tot)

    def end(self) -> None:
        with self._lock:
            self._active = False

    def snapshot(self) -> tuple[str, int, int, bool]:
        with self._lock:
            return (self._message, self._done, self._total, self._active)


def format_tool_progress_text(message: str, done: int, total: int) -> str:
    """Status-bar / Processes text for a tool progress snapshot."""
    if total < 0:
        return str(message or "")
    dv = min(max(int(done), 0), int(total))
    tot = int(total)
    pct = int(100 * dv / tot) if tot > 0 else 100
    msg = str(message or "")
    if msg:
        return f"{msg} — {dv}/{tot} ({pct}%)"
    return f"{dv}/{tot} ({pct}%)"


def report_tool_progress(
    *,
    message: str,
    done: int,
    total: int,
    progress_state: ToolProgressState | None = None,
    signals: Any = None,
    throttle: list | None = None,
    force_signal: bool = False,
) -> None:
    """
    Update polled status (``ToolProgressState``) and optionally emit ``tool_progress``.

    Workers should call this (or pass ``progress_state`` into helpers that do) so the
    bottom-left status bar stays current even when the GIL blocks Qt signal delivery.
    """
    msg = str(message or "")
    tot_in = int(total)
    if tot_in < 0:
        if progress_state is not None:
            progress_state.update(msg, 0, -1)
        if signals is None:
            return
        emit = True if force_signal or throttle is None else False
        if not emit and throttle is not None:
            now = time.monotonic()
            last_d, last_t = int(throttle[0]), float(throttle[1])
            if (now - last_t) >= 0.25:
                throttle[0] = last_d
                throttle[1] = now
                emit = True
        if emit:
            try:
                signals.tool_progress.emit(msg, 0, -1)
            except Exception:
                pass
        return
    tot = max(1, tot_in)
    d = min(max(int(done), 0), tot)
    if progress_state is not None:
        progress_state.update(msg, d, tot)
    if signals is None:
        return
    emit = force_signal
    if not emit and throttle is not None:
        now = time.monotonic()
        last_d, last_t = int(throttle[0]), float(throttle[1])
        step = max(1, tot // 20)
        if d == 0 or d >= tot or d - last_d >= step or (now - last_t) >= 0.25:
            throttle[0] = d
            throttle[1] = now
            emit = True
    elif not emit:
        emit = True
    if emit:
        try:
            signals.tool_progress.emit(msg, d, tot)
        except Exception:
            pass
