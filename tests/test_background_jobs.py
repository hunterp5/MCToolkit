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

"""Background job registry for Processes dialog."""

from __future__ import annotations

from types import SimpleNamespace

from mctoolkit.ui.background_jobs import register_background_job, unregister_background_job


def test_background_job_register_unregister() -> None:
    app = SimpleNamespace(_background_jobs={}, background_activity=SimpleNamespace(notify_calls=0))

    def notify() -> None:
        app.background_activity.notify_calls += 1

    app.background_activity.notify_changed = notify

    register_background_job(app, "job-a", "Test job")
    assert app._background_jobs == {"job-a": "Test job"}
    assert app.background_activity.notify_calls == 1

    unregister_background_job(app, "job-a")
    assert app._background_jobs == {}
    assert app.background_activity.notify_calls == 2
