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

from __future__ import annotations

import threading

from mctoolkit.platform_support.tool_progress import (
    ToolProgressState,
    format_overlay_progress_text,
    format_tool_progress_text,
)


def test_format_tool_progress_text() -> None:
    assert format_tool_progress_text("Calculate descriptors", 120, 500) == (
        "Calculate descriptors — 120/500 (24%)"
    )
    assert format_tool_progress_text("", 1, 1) == "1/1 (100%)"
    assert format_tool_progress_text("Generate conformations…", 49, 50) == (
        "Generate conformations… — 49/50 (98%)"
    )
    assert format_tool_progress_text("Building table…", -1, -1) == "Building table…"
    assert format_tool_progress_text("Predict SOM: waiting on NERDD…", 0, -1) == (
        "Predict SOM: waiting on NERDD…"
    )


def test_format_overlay_progress_text() -> None:
    assert format_overlay_progress_text("Loading session…", 120, 500) == (
        "Loading session…\n120/500 (24%)"
    )
    assert format_overlay_progress_text("Render 2D", 4, 10) == "Render 2D\n4/10 (40%)"
    assert format_overlay_progress_text("Building table…", -1, -1) == "Building table…"
    assert format_overlay_progress_text("Loading session…", 1234, 10000) == (
        "Loading session…\n1,234/10,000 (12%)"
    )
    assert format_overlay_progress_text("Preparing filters…", 3, 12) == (
        "Preparing filters…\n3/12 (25%)"
    )
    assert format_overlay_progress_text("Decoding session…", 0, -1) == "Decoding session…"


def test_throttled_progress_should_emit() -> None:
    from mctoolkit.platform_support.tool_progress import throttled_progress_should_emit

    throttle = [0, 0.0]
    assert throttled_progress_should_emit(0, 100, throttle)
    assert not throttled_progress_should_emit(1, 100, throttle)
    assert throttled_progress_should_emit(5, 100, throttle)
    assert throttled_progress_should_emit(100, 100, throttle)
    unknown = [0, 0.0]
    assert throttled_progress_should_emit(0, -1, unknown)
    assert not throttled_progress_should_emit(0, -1, unknown)


def test_tool_progress_state_allows_indeterminate_total():
    state = ToolProgressState()
    state.begin("Predict SOM", 12)
    state.update("Predict SOM: waiting on NERDD…", 0, -1)
    msg, done, total, active = state.snapshot()
    assert active
    assert total == -1
    assert msg == "Predict SOM: waiting on NERDD…"
    assert done == 0
    state.end()


def test_tool_progress_state_threaded_updates():
    state = ToolProgressState()
    state.begin("Calculate descriptors", 100)
    errors: list[Exception] = []

    def worker() -> None:
        try:
            for i in range(1, 101):
                state.update("Calculate descriptors", i, 100)
        except Exception as exc:
            errors.append(exc)

    t = threading.Thread(target=worker)
    t.start()
    t.join()
    assert not errors
    msg, done, total, active = state.snapshot()
    assert active
    assert done == 100
    assert total == 100
    assert msg == "Calculate descriptors"
    state.end()
    assert state.snapshot()[3] is False


class _ProgressEmitter:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def emit(self, *args) -> None:
        self.calls.append(args)


class _ProgressSignals:
    def __init__(self) -> None:
        self.tool_progress = _ProgressEmitter()


def test_report_tool_progress_force_signal_bypasses_throttle():
    from mctoolkit.platform_support.tool_progress import report_tool_progress

    signals = _ProgressSignals()
    state = ToolProgressState()
    state.begin("Generate conformations…", 50)
    throttle = [49, 1e12]
    report_tool_progress(
        message="Generate conformations…",
        done=49,
        total=50,
        progress_state=state,
        signals=signals,
        throttle=throttle,
    )
    assert signals.tool_progress.calls == []
    report_tool_progress(
        message="Generate conformations…",
        done=50,
        total=50,
        progress_state=state,
        signals=signals,
        throttle=throttle,
        force_signal=True,
    )
    assert signals.tool_progress.calls[-1] == ("Generate conformations…", 50, 50)
    _, done, total, active = state.snapshot()
    assert active
    assert done == 50
    assert total == 50


def test_tool_progress_slots_are_independent():
    state = ToolProgressState()
    state.begin("Calculate descriptors", 100, job_id="desc")
    state.begin("Applying filters", 50, job_id="filter")
    state.update("Calculate descriptors", 20, 100, job_id="desc")
    state.update("Applying filters…", 10, 50, job_id="filter")
    desc = state.snapshot(job_id="desc")
    filt = state.snapshot(job_id="filter")
    assert desc[0] == "Calculate descriptors"
    assert desc[1] == 20
    assert desc[3] is True
    assert filt[0] == "Applying filters…"
    assert filt[1] == 10
    snaps = state.snapshots()
    assert set(snaps) == {"desc", "filter"}
    state.end(job_id="filter")
    assert state.snapshot(job_id="filter")[3] is False
    assert state.snapshot(job_id="desc")[3] is True
    assert state.any_active()


def test_bound_tool_progress_writes_named_slot():
    state = ToolProgressState()
    bound = state.bind("job-a")
    bound.begin("Export", 8)
    bound.update("Export", 3, 8)
    msg, done, total, active = state.snapshot(job_id="job-a")
    assert active
    assert msg == "Export"
    assert done == 3
    assert total == 8
    unnamed = state.snapshot(job_id="")
    assert unnamed[3] is False


def test_tool_progress_job_context_routes_updates():
    from mctoolkit.platform_support.tool_progress import tool_progress_job

    state = ToolProgressState()
    with tool_progress_job("queue-1"):
        state.begin("Generate conformations", 10)
        state.update("Generate conformations", 4, 10)
    msg, done, _total, active = state.snapshot(job_id="queue-1")
    assert active
    assert done == 4
    assert msg == "Generate conformations"
    assert state.snapshot(job_id="")[3] is False


def test_generation_progress_label_calls_out_last_molecule():
    from mctoolkit.workers.conformer_generation import generation_progress_label

    assert generation_progress_label(0, 50) == "Generate conformations…"
    assert generation_progress_label(49, 50) == "Generate conformations… last molecule"
    assert generation_progress_label(50, 50) == "Generate conformations…"
    assert generation_progress_label(1, 1) == "Generate conformations…"


def test_drain_completed_futures_keeps_pending_and_collects_done():
    from concurrent.futures import Future

    from mctoolkit.workers.conformer_generation import drain_completed_futures

    pending = Future()
    done = Future()
    done.set_result((1, None, "ok"))
    cancelled = Future()
    cancelled.cancel()
    results: list = []
    leftover, added = drain_completed_futures({pending, done, cancelled}, results)
    assert leftover == {pending}
    assert added == 1
    assert results == [(1, None, "ok")]
