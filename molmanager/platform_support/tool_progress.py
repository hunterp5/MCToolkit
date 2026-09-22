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

"""Thread-safe tool progress for background workers (polled on the Qt GUI thread)."""

from __future__ import annotations

import contextvars
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator

# Empty key: legacy / status-bar slot used when a caller does not name a job.
_DEFAULT_JOB_ID = ""
_progress_job_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "molmanager_tool_progress_job_id",
    default=None,
)


@contextmanager
def tool_progress_job(job_id: str) -> Iterator[None]:
    """Bind ``ToolProgressState`` updates on this thread to *job_id*."""
    token = _progress_job_id.set(str(job_id))
    try:
        yield
    finally:
        _progress_job_id.reset(token)


def current_tool_progress_job_id() -> str | None:
    """Job id bound to this thread, if any."""
    bound = _progress_job_id.get()
    return str(bound) if bound else None


@dataclass
class _ProgressSlot:
    message: str = ""
    done: int = 0
    total: int = 1
    active: bool = False
    updated_at: float = 0.0


class BoundToolProgress:
    """Worker-facing view of one named slot on a shared ``ToolProgressState``."""

    def __init__(self, state: ToolProgressState, job_id: str) -> None:
        self._state = state
        self._job_id = str(job_id)

    def begin(self, message: str, total: int) -> str:
        return self._state.begin(message, total, job_id=self._job_id)

    def update(
        self,
        message: str,
        done: int,
        total: int | None = None,
        job_id: str | None = None,
    ) -> None:
        self._state.update(message, done, total, job_id=job_id or self._job_id)

    def end(self, job_id: str | None = None) -> None:
        self._state.end(job_id=job_id or self._job_id)

    def snapshot(self, job_id: str | None = None) -> tuple[str, int, int, bool]:
        return self._state.snapshot(job_id=job_id or self._job_id)

    def bind(self, job_id: str) -> BoundToolProgress:
        return self._state.bind(job_id)


class ToolProgressState:
    """
    Updated from worker threads; read from a QTimer on the main window.

    Avoids relying on ``pyqtSignal`` delivery while the GIL is held by descriptor work.
    Concurrent jobs write named slots so Log can show each row's own text.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._slots: dict[str, _ProgressSlot] = {}

    def bind(self, job_id: str) -> BoundToolProgress:
        """Return a proxy that always reads/writes *job_id*'s slot."""
        return BoundToolProgress(self, job_id)

    def _resolve_job_id(self, job_id: str | None) -> str:
        if job_id:
            return str(job_id)
        scoped = _progress_job_id.get()
        if scoped:
            return str(scoped)
        return _DEFAULT_JOB_ID

    def begin(self, message: str, total: int, job_id: str | None = None) -> str:
        key = self._resolve_job_id(job_id)
        with self._lock:
            self._slots[key] = _ProgressSlot(
                message=str(message or ""),
                done=0,
                total=max(1, int(total)),
                active=True,
                updated_at=time.monotonic(),
            )
        return key

    def update(
        self,
        message: str,
        done: int,
        total: int | None = None,
        job_id: str | None = None,
    ) -> None:
        key = self._resolve_job_id(job_id)
        with self._lock:
            slot = self._slots.get(key)
            if slot is None:
                slot = _ProgressSlot(active=True)
                self._slots[key] = slot
            slot.message = str(message or "")
            slot.done = max(0, int(done))
            if total is not None:
                tot = int(total)
                # Negative total is indeterminate (status text only, no 0%).
                slot.total = tot if tot < 0 else max(1, tot)
            slot.active = True
            slot.updated_at = time.monotonic()

    def end(self, job_id: str | None = None) -> None:
        key = self._resolve_job_id(job_id)
        with self._lock:
            slot = self._slots.get(key)
            if slot is not None:
                slot.active = False

    def snapshot(self, job_id: str | None = None) -> tuple[str, int, int, bool]:
        with self._lock:
            if job_id is not None:
                slot = self._slots.get(str(job_id))
                return self._tuple(slot)
            scoped = _progress_job_id.get()
            if scoped:
                slot = self._slots.get(str(scoped))
                if slot is not None:
                    return self._tuple(slot)
            default = self._slots.get(_DEFAULT_JOB_ID)
            if default is not None and default.active:
                return self._tuple(default)
            latest: _ProgressSlot | None = None
            latest_at = -1.0
            for slot in self._slots.values():
                if slot.active and slot.updated_at >= latest_at:
                    latest = slot
                    latest_at = slot.updated_at
            return self._tuple(latest)

    def preferred_snapshot(self, prefer_job_id: str | None = None) -> tuple[str, int, int, bool]:
        """Snapshot for the status bar: named job if active, else ``snapshot()``."""
        if prefer_job_id:
            with self._lock:
                slot = self._slots.get(str(prefer_job_id))
                if slot is not None and slot.active:
                    return self._tuple(slot)
        return self.snapshot()

    def snapshots(self) -> dict[str, tuple[str, int, int, bool]]:
        """Active slots keyed by job id (empty string is the unnamed slot)."""
        with self._lock:
            return {jid: self._tuple(slot) for jid, slot in self._slots.items() if slot.active}

    def any_active(self) -> bool:
        with self._lock:
            return any(slot.active for slot in self._slots.values())

    @staticmethod
    def _tuple(slot: _ProgressSlot | None) -> tuple[str, int, int, bool]:
        if slot is None:
            return ("", 0, 1, False)
        return (slot.message, slot.done, slot.total, slot.active)


def format_tool_progress_text(message: str, done: int, total: int) -> str:
    """Status-bar / Log text for a tool progress snapshot."""
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
    progress_state: ToolProgressState | BoundToolProgress | None = None,
    signals: Any = None,
    throttle: list | None = None,
    force_signal: bool = False,
    job_id: str | None = None,
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
            progress_state.update(msg, 0, -1, job_id=job_id)
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
        progress_state.update(msg, d, tot, job_id=job_id)
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
