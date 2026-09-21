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
# along with mctoolkit.  If not, see <https://www.gnu.org/licenses/>.

"""Render 2D can start while another serial tool (e.g. CONFORGE) is running."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from mctoolkit.ui.table_build_render import TableBuildRender


class _QueueHost(TableBuildRender):
    def __init__(self, *, running_title: str | None) -> None:
        self._app = self
        self._render2d_batch_active = False
        self.process_queue = MagicMock()
        self._begin_calls: list[tuple] = []
        if running_title:
            self.process_queue.has_running_job.return_value = True
            self.process_queue.snapshot.return_value = {
                "running": {"title": running_title},
                "queued": [],
            }
        else:
            self.process_queue.has_running_job.return_value = False
            self.process_queue.snapshot.return_value = {"running": None, "queued": []}

    def _begin_render2d_batch_impl(self, *args, **kwargs) -> None:
        self._begin_calls.append((args, kwargs))


def test_render2d_shares_ui_with_conforge_job() -> None:
    host = _QueueHost(running_title="CONFORGE conformations (10 structures)")
    assert host._render2d_shares_ui_with_queue_job() is True


def test_render2d_does_not_share_ui_when_queue_idle() -> None:
    host = _QueueHost(running_title=None)
    assert host._render2d_shares_ui_with_queue_job() is False


def test_render2d_does_not_share_ui_when_render_is_the_queue_job() -> None:
    host = _QueueHost(running_title="render 2D (100 rows)")
    assert host._render2d_shares_ui_with_queue_job() is False


def test_start_render2d_runs_off_queue_while_conforge_is_running() -> None:
    host = _QueueHost(running_title="CONFORGE conformations (4 structures)")
    renders = [(1, None, 100, 80)]
    host._start_render_2d_batch(renders, {1: 0}, "Structure")
    assert host._begin_calls
    assert host.process_queue.enqueue.call_count == 0
    args, kwargs = host._begin_calls[0]
    assert args[0] is renders
    assert kwargs.get("column_pixmap_mode") is True


def test_start_render2d_enqueues_when_queue_is_idle() -> None:
    host = _QueueHost(running_title=None)
    host._start_render_2d_batch([(1, None, 100, 80)], {1: 0}, "Structure")
    assert host._begin_calls == []
    host.process_queue.enqueue.assert_called_once()
    title, _factory = host.process_queue.enqueue.call_args.args
    assert title == "render 2D (1 rows)"


def test_run_render_2d_structures_allows_dialog_while_conforge_runs(qapp, monkeypatch) -> None:  # noqa: ARG001
    shown = {"n": 0}

    class _Dlg:
        def __init__(self, *_a, **_k) -> None:
            self.accepted = SimpleNamespace(connect=lambda *_a, **_k: None)

        def setAttribute(self, *_a, **_k) -> None:
            return None

        def show(self) -> None:
            shown["n"] += 1

    host = _QueueHost(running_title="CONFORGE conformations (10 structures)")
    host.headers = ["id", "Structure"]
    host._table_model = SimpleNamespace(rowCount=lambda: 2)
    host._selected_logical_rows = lambda: []
    host._prepare_tool_dialog = lambda *_a, **_k: None
    host.chemistry_tool_structure_sources = lambda: ["Structure"]
    import mctoolkit.ui.dialogs as dialogs_pkg

    monkeypatch.setattr(dialogs_pkg, "Render2DStructureDialog", _Dlg, raising=False)
    host.run_render_2d_structures()
    assert shown["n"] == 1
