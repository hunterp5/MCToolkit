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
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with MolManager. If not, see <https://www.gnu.org/licenses/>.

"""Reusable ProcessPoolExecutor for batch 2D structure rendering."""

from __future__ import annotations

import logging
import os
import threading
from concurrent.futures import ProcessPoolExecutor
from contextlib import suppress

from ..platform_support.config import load_config
from .process_pool_utils import (
    application_is_shutting_down,
    register_process_pool,
    shutdown_process_pool_executor,
    unregister_process_pool,
)

logger = logging.getLogger(__name__)

_LOCK = threading.Lock()
_POOL: ProcessPoolExecutor | None = None
_POOL_WORKERS = 0
_WARMING = False


def render2d_process_worker_count() -> int:
    """Child-process count for batch 2D rendering.

    PNG encoding is ~70% of each render and runs entirely in the children, so this scales past the
    physical core count on SMT machines.
    """
    cfg = load_config()
    configured = cfg.render2d_process_workers
    if configured:
        return max(1, int(configured))
    return max(2, min(12, (os.cpu_count() or 4) - 1))


def ensure_render2d_process_pool(
    *,
    max_workers: int | None = None,
) -> ProcessPoolExecutor | None:
    """Return a shared render pool, creating it if needed.

    Returns ``None`` when the application is shutting down.
    """
    global _POOL, _POOL_WORKERS, _WARMING
    if application_is_shutting_down():
        return None
    want = max(1, int(max_workers if max_workers is not None else render2d_process_worker_count()))
    with _LOCK:
        if _POOL is not None and _POOL_WORKERS == want:
            return _POOL
        if _POOL is not None:
            old = _POOL
            _POOL = None
            _POOL_WORKERS = 0
            with suppress(ValueError, RuntimeError):
                unregister_process_pool(old)
            try:
                shutdown_process_pool_executor(old, kill_workers=False)
            except (RuntimeError, OSError) as exc:
                logger.debug("prior render pool shutdown failed: %s", exc)
        _POOL = register_process_pool(ProcessPoolExecutor(max_workers=want))
        _POOL_WORKERS = want
        _WARMING = False
        return _POOL


def warm_render2d_process_pool() -> None:
    """Kick off pool creation early so spawn overlaps session decode/parse."""
    global _WARMING
    with _LOCK:
        if _POOL is not None or _WARMING or application_is_shutting_down():
            return
        _WARMING = True
    try:
        ensure_render2d_process_pool()
    finally:
        with _LOCK:
            _WARMING = False


def release_render2d_process_pool(*, kill_workers: bool = False) -> None:
    """Shut down the shared render pool (app exit or cancel-all)."""
    global _POOL, _POOL_WORKERS
    with _LOCK:
        ex = _POOL
        _POOL = None
        _POOL_WORKERS = 0
    if ex is not None:
        with suppress(ValueError, RuntimeError):
            unregister_process_pool(ex)
        shutdown_process_pool_executor(ex, kill_workers=kill_workers)
