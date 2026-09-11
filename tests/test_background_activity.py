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

"""Background activity hub (Processes dialog rows)."""

from __future__ import annotations

from types import SimpleNamespace

from molmanager.tool_progress import ToolProgressState
from molmanager.ui.background_activity import BackgroundActivityHub


class _FakeProcessQueue:
    def __init__(self, snap: dict) -> None:
        self._snap = snap

    def snapshot(self) -> dict:
        return self._snap


def test_processes_view_dedupes_render2d_when_on_queue(qapp) -> None:  # noqa: ARG001
    app = SimpleNamespace(
        process_queue=_FakeProcessQueue(
            {
                "running": {
                    "job_id": "abc123",
                    "title": "render 2D (100 rows)",
                    "status": "Running",
                    "cancellable": True,
                },
                "queued": [],
                "fast_running": [],
            }
        ),
        render2d_batch_active=lambda: True,
        _background_jobs={},
    )
    hub = BackgroundActivityHub(app, qapp)
    rows, metas = hub.processes_view_rows()
    assert len(rows) == 1
    assert rows[0] == ("Running", "abc123", "render 2D (100 rows)")
    assert metas[0]["kind"] == "pq_running"


def test_processes_view_shows_render2d_row_when_not_on_queue(qapp) -> None:  # noqa: ARG001
    app = SimpleNamespace(
        process_queue=_FakeProcessQueue({"running": None, "queued": [], "fast_running": []}),
        render2d_batch_active=lambda: True,
        _background_jobs={},
    )
    hub = BackgroundActivityHub(app, qapp)
    rows, metas = hub.processes_view_rows()
    assert len(rows) == 1
    assert rows[0][1] == "(render-2d)"
    assert metas[0]["kind"] == "render2d"


def test_processes_view_includes_tool_progress_on_running_job(qapp) -> None:  # noqa: ARG001
    state = ToolProgressState()
    state.begin("Calculate descriptors", 500)
    state.update("Calculate descriptors", 120, 500)
    app = SimpleNamespace(
        process_queue=_FakeProcessQueue(
            {
                "running": {
                    "job_id": "desc01",
                    "title": "Calculate descriptors",
                    "status": "Running",
                    "cancellable": True,
                },
                "queued": [{"job_id": "next", "title": "Export", "status": "Queued"}],
                "fast_running": [],
            }
        ),
        render2d_batch_active=lambda: False,
        _background_jobs={},
        _tool_progress_state=state,
    )
    hub = BackgroundActivityHub(app, qapp)
    _rows, metas = hub.processes_view_rows()
    assert "120/500" in metas[0]["progress"]
    assert "(24%)" in metas[0]["progress"]
    assert metas[1]["kind"] == "pq_queued"
    assert metas[1]["progress"] == ""


def test_try_cancel_pq_running_render2d_uses_batch_cancel(qapp) -> None:  # noqa: ARG001
    cancelled = {"ok": False}

    def cancel_render_2d_batch() -> bool:
        cancelled["ok"] = True
        return True

    app = SimpleNamespace(
        process_queue=_FakeProcessQueue({"running": {"job_id": "x"}}),
        cancel_render_2d_batch=cancel_render_2d_batch,
        render2d_batch_active=lambda: True,
    )
    hub = BackgroundActivityHub(app, qapp)

    dialog_info, status = hub.try_cancel_row({"kind": "pq_running", "job_id": "x"})
    assert dialog_info is None
    assert status == "Render 2D cancelled."
    assert cancelled["ok"]
