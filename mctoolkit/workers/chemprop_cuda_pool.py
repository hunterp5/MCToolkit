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
# along with mctoolkit. If not, see <https://www.gnu.org/licenses/>.

"""Shared 1-worker Chemprop CUDA process pool (GNN-MTL + Predict ADME)."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Iterator
from concurrent.futures import FIRST_COMPLETED, BrokenExecutor, ProcessPoolExecutor, wait
from contextlib import contextmanager

from .process_pool_utils import (
    add_process_pool_shutdown_callback,
    register_process_pool,
    should_terminate_process_pool,
    shutdown_process_pool_executor,
)

logger = logging.getLogger(__name__)

_POOL_LOCK = threading.Lock()
_PERSISTENT_POOL: ProcessPoolExecutor | None = None
_PERSISTENT_POOL_REFS = 0
_SHUTDOWN_HOOK_REGISTERED = False


def _executor_is_usable(ex: ProcessPoolExecutor | None) -> bool:
    if ex is None:
        return False
    if getattr(ex, "_broken", False):
        return False
    shutdown_flag = getattr(ex, "_shutdown_thread", False)
    if shutdown_flag is True or isinstance(shutdown_flag, threading.Thread):
        return False
    if getattr(ex, "_shutdown", False) is True:
        return False
    return True


def _clear_persistent_pool_if_matches(ex: ProcessPoolExecutor) -> None:
    global _PERSISTENT_POOL, _PERSISTENT_POOL_REFS
    with _POOL_LOCK:
        if _PERSISTENT_POOL is ex:
            _PERSISTENT_POOL = None
            _PERSISTENT_POOL_REFS = 0


def _ensure_pool_shutdown_hook() -> None:
    global _SHUTDOWN_HOOK_REGISTERED
    if _SHUTDOWN_HOOK_REGISTERED:
        return
    add_process_pool_shutdown_callback(_clear_persistent_pool_if_matches)
    _SHUTDOWN_HOOK_REGISTERED = True


def discard_chemprop_process_pool() -> None:
    """Kill the cached Chemprop worker (timeout, tests, or a broken GPU child)."""
    global _PERSISTENT_POOL, _PERSISTENT_POOL_REFS
    with _POOL_LOCK:
        ex = _PERSISTENT_POOL
        _PERSISTENT_POOL = None
        _PERSISTENT_POOL_REFS = 0
    shutdown_process_pool_executor(ex, kill_workers=True)


def _acquire_persistent_pool() -> ProcessPoolExecutor:
    global _PERSISTENT_POOL, _PERSISTENT_POOL_REFS
    _ensure_pool_shutdown_hook()
    with _POOL_LOCK:
        ex = _PERSISTENT_POOL
        if _executor_is_usable(ex):
            _PERSISTENT_POOL_REFS += 1
            return ex
        stale = ex
        _PERSISTENT_POOL = None
        _PERSISTENT_POOL_REFS = 0
    if stale is not None:
        shutdown_process_pool_executor(stale, kill_workers=True)
    created = register_process_pool(ProcessPoolExecutor(max_workers=1))
    with _POOL_LOCK:
        _PERSISTENT_POOL = created
        _PERSISTENT_POOL_REFS = 1
    return created


def _release_persistent_pool(*, kill: bool) -> None:
    global _PERSISTENT_POOL, _PERSISTENT_POOL_REFS
    with _POOL_LOCK:
        _PERSISTENT_POOL_REFS = max(0, _PERSISTENT_POOL_REFS - 1)
        ex = _PERSISTENT_POOL
        if not kill and _executor_is_usable(ex):
            return
        _PERSISTENT_POOL = None
        _PERSISTENT_POOL_REFS = 0
    shutdown_process_pool_executor(ex, kill_workers=True)


@contextmanager
def chemprop_process_pool(
    *,
    cancel_event: threading.Event | None = None,
) -> Iterator[ProcessPoolExecutor]:
    """Yield a 1-worker Chemprop pool that stays loaded between GPU jobs."""
    ex = _acquire_persistent_pool()
    kill = False
    try:
        yield ex
    except BaseException:
        kill = True
        raise
    finally:
        if should_terminate_process_pool(cancel_event) or getattr(ex, "_broken", False):
            kill = True
        _release_persistent_pool(kill=kill)


def chunk_smiles(smiles: list[str], batch_size: int) -> list[list[str]]:
    if not smiles:
        return []
    bs = max(1, int(batch_size))
    return [smiles[i : i + bs] for i in range(0, len(smiles), bs)]


def run_chemprop_chunked(
    chunk_fn: Callable,
    smiles: list[str],
    batch_size: int,
    *,
    extra_args: tuple = (),
    cancel_event: threading.Event | None = None,
    progress_callback: Callable[[int, int], None] | None = None,
    fail_message: str = "Chemprop GPU worker failed.",
) -> list:
    """Run *chunk_fn* on SMILES batches in the shared CUDA child process."""
    chunks = chunk_smiles(smiles, batch_size)
    if not chunks:
        return []
    n_total = len(smiles)
    results_by_i: dict[int, list] = {}
    pool_failed = False
    with chemprop_process_pool(cancel_event=cancel_event) as ex:
        future_to_i = {
            ex.submit(chunk_fn, chunk, batch_size, *extra_args): i for i, chunk in enumerate(chunks)
        }
        pending = set(future_to_i)
        while pending:
            if should_terminate_process_pool(cancel_event):
                completed, pending = wait(pending, timeout=0)
                for fut in completed:
                    if fut.cancelled():
                        continue
                    idx = future_to_i[fut]
                    try:
                        results_by_i[idx] = fut.result()
                    except (RuntimeError, OSError, ValueError, BrokenExecutor):
                        logger.debug("Chemprop process-pool task failed", exc_info=True)
                for fut in pending:
                    fut.cancel()
                raise RuntimeError("cancelled")
            completed, pending = wait(pending, timeout=0.25, return_when=FIRST_COMPLETED)
            for fut in completed:
                if fut.cancelled():
                    continue
                idx = future_to_i[fut]
                try:
                    results_by_i[idx] = fut.result()
                except BrokenExecutor:
                    pool_failed = True
                    logger.warning("Chemprop process pool failed")
                    break
                if progress_callback is not None:
                    done = sum(len(chunks[j]) for j in results_by_i)
                    progress_callback(min(done, n_total), n_total)
            if pool_failed:
                for fut in pending:
                    fut.cancel()
                break
    if pool_failed or any(i not in results_by_i for i in range(len(chunks))):
        discard_chemprop_process_pool()
        if should_terminate_process_pool(cancel_event):
            raise RuntimeError("cancelled")
        raise RuntimeError(fail_message)
    out: list = []
    for i in range(len(chunks)):
        out.extend(results_by_i[i])
    return out
