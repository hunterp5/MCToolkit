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

"""Track short-lived threadpool work for the Processes dialog.

Jobs registered here appear in the Processes window. Passing a ``cancel`` callable
makes the job cancellable from that window (the callable should set the worker's
cancel event so it stops cooperatively and its result is discarded).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


def register_background_job(
    app: Any,
    job_id: str,
    title: str,
    *,
    cancel: Callable[[], None] | None = None,
) -> None:
    """Register a background job for the Processes window, optionally cancellable."""
    jobs = getattr(app, "_background_jobs", None)
    if jobs is None:
        jobs = {}
        app._background_jobs = jobs
    jobs[str(job_id)] = str(title or "Background job")
    cancels = getattr(app, "_background_job_cancels", None)
    if cancels is None:
        cancels = {}
        app._background_job_cancels = cancels
    if cancel is not None:
        cancels[str(job_id)] = cancel
    else:
        cancels.pop(str(job_id), None)
    hub = getattr(app, "background_activity", None)
    if hub is not None:
        hub.notify_changed()


def unregister_background_job(app: Any, job_id: str) -> None:
    jobs = getattr(app, "_background_jobs", None)
    if jobs:
        jobs.pop(str(job_id), None)
    cancels = getattr(app, "_background_job_cancels", None)
    if cancels:
        cancels.pop(str(job_id), None)
    state = getattr(app, "_tool_progress_state", None)
    end = getattr(state, "end", None)
    if callable(end):
        end(job_id=str(job_id))
    hub = getattr(app, "background_activity", None)
    if hub is not None:
        hub.notify_changed()


def background_job_is_cancellable(app: Any, job_id: str) -> bool:
    cancels = getattr(app, "_background_job_cancels", None)
    return bool(cancels and str(job_id) in cancels)


def cancel_background_job(app: Any, job_id: str) -> bool:
    """Invoke the registered cancel callable for a job. Returns True if one ran."""
    cancels = getattr(app, "_background_job_cancels", None)
    if not cancels:
        return False
    fn = cancels.get(str(job_id))
    if fn is None:
        return False
    try:
        fn()
    except Exception:
        return False
    return True
