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
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with MCToolkit.  If not, see <https://www.gnu.org/licenses/>.

"""Background activity hub (Processes dialog rows)."""

from __future__ import annotations

from types import SimpleNamespace

from mctoolkit.platform_support.tool_progress import ToolProgressState
from mctoolkit.ui.background_activity import BackgroundActivityHub


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


def test_processes_view_keeps_tool_progress_on_serial_job_when_render2d_overlays(
    qapp,
) -> None:  # noqa: ARG001
    state = ToolProgressState()
    state.begin("CONFORGE conformations", 10)
    state.update("CONFORGE conformations", 3, 10)
    app = SimpleNamespace(
        process_queue=_FakeProcessQueue(
            {
                "running": {
                    "job_id": "cfg01",
                    "title": "CONFORGE conformations (10 structures)",
                    "status": "Running",
                    "cancellable": True,
                },
                "queued": [],
                "fast_running": [],
            }
        ),
        render2d_batch_active=lambda: True,
        _background_jobs={},
        _tool_progress_state=state,
    )
    hub = BackgroundActivityHub(app, qapp)
    rows, metas = hub.processes_view_rows()
    assert rows[0][1] == "(render-2d)"
    assert metas[0]["kind"] == "render2d"
    assert metas[0]["progress"] == ""
    assert metas[1]["kind"] == "pq_running"
    assert "CONFORGE" in metas[1]["progress"]
    assert "3/10" in metas[1]["progress"]


def test_try_cancel_pq_running_render2d_uses_batch_cancel(qapp) -> None:  # noqa: ARG001
    cancelled = {"ok": False}

    def cancel_render_2d_batch() -> bool:
        cancelled["ok"] = True
        return True

    app = SimpleNamespace(
        process_queue=_FakeProcessQueue(
            {"running": {"job_id": "x", "title": "render 2D (12 rows)"}}
        ),
        cancel_render_2d_batch=cancel_render_2d_batch,
        render2d_batch_active=lambda: True,
    )
    hub = BackgroundActivityHub(app, qapp)

    dialog_info, status = hub.try_cancel_row({"kind": "pq_running", "job_id": "x"})
    assert dialog_info is None
    assert status == "Render 2D cancelled."
    assert cancelled["ok"]


def test_try_cancel_pq_running_leaves_overlay_render2d_alone(qapp) -> None:  # noqa: ARG001
    cancelled = {"render": False, "queue": False}

    class _Queue(_FakeProcessQueue):
        def cancel_running(self) -> bool:
            cancelled["queue"] = True
            return True

    def cancel_render_2d_batch() -> bool:
        cancelled["render"] = True
        return True

    app = SimpleNamespace(
        process_queue=_Queue(
            {
                "running": {
                    "job_id": "cfg01",
                    "title": "CONFORGE conformations (10 structures)",
                }
            }
        ),
        cancel_render_2d_batch=cancel_render_2d_batch,
        render2d_batch_active=lambda: True,
    )
    hub = BackgroundActivityHub(app, qapp)
    dialog_info, status = hub.try_cancel_row({"kind": "pq_running", "job_id": "cfg01"})
    assert dialog_info is None
    assert status == "Cancelling…"
    assert cancelled["queue"] is True
    assert cancelled["render"] is False


def test_try_cancel_background_job(qapp) -> None:  # noqa: ARG001
    from mctoolkit.ui.background_jobs import register_background_job

    cancelled = {"n": 0}

    def _cancel() -> None:
        cancelled["n"] += 1

    app = SimpleNamespace(
        process_queue=_FakeProcessQueue({"running": None, "queued": [], "fast_running": []}),
        render2d_batch_active=lambda: False,
        _background_jobs={},
        background_activity=None,
    )
    hub = BackgroundActivityHub(app, qapp)
    app.background_activity = hub
    register_background_job(app, "filter-1", "Applying filters", cancel=_cancel)
    rows, metas = hub.processes_view_rows()
    assert any(m.get("kind") == "background" and m.get("cancellable") for m in metas)
    dialog_info, status = hub.try_cancel_row({"kind": "background", "job_id": "filter-1"})
    assert dialog_info is None
    assert status == "Cancelling…"
    assert cancelled["n"] == 1


def test_try_cancel_background_job_without_cancel_callable(qapp) -> None:  # noqa: ARG001
    from mctoolkit.ui.background_jobs import register_background_job

    app = SimpleNamespace(
        process_queue=_FakeProcessQueue({"running": None, "queued": [], "fast_running": []}),
        render2d_batch_active=lambda: False,
        _background_jobs={},
        background_activity=None,
    )
    hub = BackgroundActivityHub(app, qapp)
    app.background_activity = hub
    register_background_job(app, "sqlite-1", "Indexing table")
    dialog_info, status = hub.try_cancel_row({"kind": "background", "job_id": "sqlite-1"})
    assert dialog_info is not None
    assert status is None
    assert "cannot be cancelled" in dialog_info[1].lower()
