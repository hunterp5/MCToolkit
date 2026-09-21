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

"""Tests for the shared chunked table writer."""

from __future__ import annotations

from mctoolkit.ui.chunked_table_write import ChunkedTableWriter, repaints_suspended


class FakeTable:
    """Records setUpdatesEnabled calls so repaint bracketing can be asserted."""

    def __init__(self, *, fail: bool = False) -> None:
        self.calls: list[bool] = []
        self._fail = fail

    def setUpdatesEnabled(self, enabled: bool) -> None:  # noqa: N802 - Qt name
        if self._fail:
            raise RuntimeError("wrapped C/C++ object has been deleted")
        self.calls.append(enabled)


def _collect(total: int, chunk: int, **kwargs) -> tuple[list[tuple[int, int, bool]], FakeTable]:
    slices: list[tuple[int, int, bool]] = []
    table = FakeTable()
    writer = ChunkedTableWriter(
        table=table,
        total=total,
        chunk=chunk,
        write_chunk=lambda start, end, last: slices.append((start, end, last)),
        **kwargs,
    )
    writer.run_now()
    return slices, table


def test_run_now_covers_the_range_in_half_open_slices():
    slices, _table = _collect(10, 4)
    assert slices == [(0, 4, False), (4, 8, False), (8, 10, True)]


def test_only_the_final_slice_is_flagged_last():
    slices, _table = _collect(9, 3)
    assert [last for _s, _e, last in slices] == [False, False, True]


def test_exact_multiple_does_not_emit_an_empty_trailing_slice():
    slices, _table = _collect(6, 3)
    assert slices == [(0, 3, False), (3, 6, True)]


def test_single_chunk_larger_than_total_is_one_last_slice():
    slices, _table = _collect(5, 100)
    assert slices == [(0, 5, True)]


def test_chunk_size_is_forced_to_at_least_one():
    slices, _table = _collect(3, 0)
    assert slices == [(0, 1, False), (1, 2, False), (2, 3, True)]


def test_repaints_are_suspended_and_restored_around_every_slice():
    _slices, table = _collect(10, 5)
    assert table.calls == [False, True, False, True]


def test_zero_total_skips_writing_but_still_reports_done():
    done: list[bool] = []
    writer = ChunkedTableWriter(
        table=FakeTable(),
        total=0,
        chunk=10,
        write_chunk=lambda start, end, last: done.append(False),
        on_done=lambda: done.append(True),
    )
    writer.run_now()
    assert done == [True]
    assert writer.stopped


def test_progress_reports_cumulative_counts():
    seen: list[tuple[int, int]] = []
    _collect(10, 4, on_progress=lambda done, total: seen.append((done, total)))
    assert seen == [(4, 10), (8, 10), (10, 10)]


def test_on_done_runs_once_after_the_last_slice():
    order: list[str] = []
    writer = ChunkedTableWriter(
        table=FakeTable(),
        total=4,
        chunk=2,
        write_chunk=lambda start, end, last: order.append(f"write{end}"),
        on_done=lambda: order.append("done"),
    )
    writer.run_now()
    assert order == ["write2", "write4", "done"]


def test_cancel_before_start_prevents_any_write():
    slices: list[int] = []
    writer = ChunkedTableWriter(
        table=FakeTable(),
        total=10,
        chunk=2,
        write_chunk=lambda start, end, last: slices.append(end),
        on_done=lambda: slices.append(-1),
    )
    writer.cancel()
    writer.run_now()
    assert slices == []


def test_should_continue_false_abandons_the_run_without_calling_on_done():
    slices: list[int] = []
    finished: list[bool] = []
    writer = ChunkedTableWriter(
        table=FakeTable(),
        total=10,
        chunk=2,
        write_chunk=lambda start, end, last: slices.append(end),
        on_done=lambda: finished.append(True),
        should_continue=lambda: len(slices) < 2,
    )
    writer.run_now()
    assert slices == [2, 4]
    assert finished == []


def test_written_tracks_progress_and_total_is_exposed():
    writer = ChunkedTableWriter(
        table=FakeTable(),
        total=7,
        chunk=3,
        write_chunk=lambda start, end, last: None,
    )
    assert writer.total == 7
    assert writer.written == 0
    writer.run_now()
    assert writer.written == 7


def test_repaints_suspended_tolerates_a_deleted_table():
    table = FakeTable(fail=True)
    with repaints_suspended(table):
        pass
    assert table.calls == []


def test_repaints_suspended_restores_even_when_the_body_raises():
    table = FakeTable()
    try:
        with repaints_suspended(table):
            raise ValueError("boom")
    except ValueError:
        pass
    assert table.calls == [False, True]


def test_repaints_suspended_accepts_no_table():
    with repaints_suspended(None):
        pass
