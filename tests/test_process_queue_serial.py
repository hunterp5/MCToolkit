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

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from mctoolkit.ui.process_queue import ProcessQueueManager


def test_process_queue_blocked_while_render2d_batch(qapp):  # noqa: ARG001
    app = SimpleNamespace()
    app.render2d_batch_active = MagicMock(return_value=True)
    pq = ProcessQueueManager(qapp)
    pq._app = app
    pq.enqueue("Calculate descriptors", lambda ev: MagicMock())
    assert pq.has_pending_jobs()
    pq._maybe_start_next()
    assert pq.has_pending_jobs()
    assert not pq.has_running_job()

    app.render2d_batch_active = MagicMock(return_value=False)
    pq.schedule_resume()
    assert pq.has_running_job() or not pq.has_pending_jobs()
