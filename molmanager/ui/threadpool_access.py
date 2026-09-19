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

"""Resolve the app's QThreadPool (or global fallback) for background workers."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QRunnable, QThreadPool


def threadpool_for_app(app: Any) -> QThreadPool:
    """Return ``app.threadpool`` when present, else ``QThreadPool.globalInstance()``."""
    if app is None:
        return QThreadPool.globalInstance()
    pool = getattr(app, "threadpool", None)
    if pool is not None:
        return pool
    return QThreadPool.globalInstance()


def start_runnable_on_app_pool(app: Any, runnable: QRunnable) -> None:
    """``threadpool_for_app(app).start(runnable)``."""
    threadpool_for_app(app).start(runnable)
