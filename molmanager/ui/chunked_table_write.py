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

"""Chunked, GUI-thread table writes that keep the window responsive.

Tools that add result columns must not block the event loop while filling a
large table. Every such tool used to carry its own copy of the same scheduling
loop -- a generation counter to discard superseded runs, an index cursor, a
``setUpdatesEnabled`` bracket, a zero-delay timer to yield between chunks, and
progress reporting. :class:`ChunkedTableWriter` owns that loop so callers only
supply the per-chunk write itself.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress

from PySide6.QtCore import QTimer

__all__ = ["ChunkedTableWriter", "repaints_suspended"]


@contextmanager
def repaints_suspended(table) -> Iterator[None]:
    """Suspend *table* repaints for the duration of the block.

    Tolerates a table whose underlying C++ widget has already been destroyed,
    which happens when a window closes while a write is still queued.
    """
    if table is None:
        yield
        return
    with suppress(RuntimeError):
        table.setUpdatesEnabled(False)
    try:
        yield
    finally:
        with suppress(RuntimeError):
            table.setUpdatesEnabled(True)


class ChunkedTableWriter:
    """Drive ``write_chunk`` over ``range(total)`` in event-loop-friendly slices.

    *write_chunk* is called as ``write_chunk(start, end, is_last)`` for each
    half-open ``[start, end)`` slice, with table repaints suspended. What the
    slice means is the caller's choice: table row ranges and indices into a list
    of pending updates are both in use.

    A writer runs at most once. Supersede an in-flight job by calling
    :meth:`cancel` on it before starting a new one; a chunk still queued on the
    event loop then becomes a no-op instead of writing stale results.

    Args:
        table: Table view whose repaints are suspended per chunk, or ``None``.
        total: Number of items to cover.
        chunk: Items per slice; forced to at least 1.
        write_chunk: Per-slice write, called as ``(start, end, is_last)``.
        on_progress: Optional ``(done, total)`` callback after each slice.
        on_done: Optional callback after the final slice completes.
        should_continue: Optional predicate checked before each slice; a false
            result abandons the run without calling *on_done*.
    """

    def __init__(
        self,
        *,
        table,
        total: int,
        chunk: int,
        write_chunk: Callable[[int, int, bool], None],
        on_progress: Callable[[int, int], None] | None = None,
        on_done: Callable[[], None] | None = None,
        should_continue: Callable[[], bool] | None = None,
    ) -> None:
        self._table = table
        self._total = max(0, int(total))
        self._chunk = max(1, int(chunk))
        self._write_chunk = write_chunk
        self._on_progress = on_progress
        self._on_done = on_done
        self._should_continue = should_continue
        self._index = 0
        self._stopped = False

    @property
    def total(self) -> int:
        return self._total

    @property
    def written(self) -> int:
        """Items covered so far."""
        return self._index

    @property
    def stopped(self) -> bool:
        """True once the writer has finished or been cancelled."""
        return self._stopped

    def cancel(self) -> None:
        """Abandon the run; any queued chunk becomes a no-op."""
        self._stopped = True

    def start(self) -> None:
        """Write the first chunk on the next event-loop pass, then continue."""
        if self._total <= 0:
            self._finish()
            return
        QTimer.singleShot(0, self._step)

    def run_now(self) -> None:
        """Write every chunk immediately, without yielding to the event loop.

        Used for tables small enough that chunking would only add latency.
        """
        if self._total <= 0:
            self._finish()
            return
        while not self._stopped:
            if not self._alive():
                return
            if self._advance():
                self._finish()
                return

    def _alive(self) -> bool:
        return self._should_continue is None or bool(self._should_continue())

    def _step(self) -> None:
        if self._stopped or not self._alive():
            return
        if self._advance():
            self._finish()
            return
        QTimer.singleShot(0, self._step)

    def _advance(self) -> bool:
        """Write the next slice; return True when it was the last one."""
        start = self._index
        end = min(start + self._chunk, self._total)
        is_last = end >= self._total
        with repaints_suspended(self._table):
            self._write_chunk(start, end, is_last)
        self._index = end
        if self._on_progress is not None:
            self._on_progress(end, self._total)
        return is_last

    def _finish(self) -> None:
        self._stopped = True
        if self._on_done is not None:
            self._on_done()
