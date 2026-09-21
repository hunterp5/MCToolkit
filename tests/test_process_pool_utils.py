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

"""Process pool shutdown helpers (app exit / cancel)."""

from __future__ import annotations

import threading
import time
from concurrent.futures import ProcessPoolExecutor

from mctoolkit.workers import process_pool_utils as ppu


def _sleep_worker(_: int) -> int:
    time.sleep(30)
    return 1


def test_shutdown_all_kills_registered_pool() -> None:
    ppu._SHUTDOWN.clear()
    ex = ppu.register_process_pool(ProcessPoolExecutor(max_workers=1))
    try:
        ex.submit(_sleep_worker, 0)
        time.sleep(0.3)
        ppu.shutdown_all_process_pools(kill_workers=True)
        processes = getattr(ex, "_processes", None) or {}
        assert not any(p is not None and p.is_alive() for p in processes.values())
    finally:
        ppu.shutdown_process_pool_executor(ex, kill_workers=True)


def test_should_terminate_on_cancel_or_shutdown() -> None:
    ppu._SHUTDOWN.clear()
    ev = threading.Event()
    assert not ppu.should_terminate_process_pool(ev)
    ev.set()
    assert ppu.should_terminate_process_pool(ev)
    ev.clear()
    ppu.signal_application_shutdown()
    assert ppu.should_terminate_process_pool(None)
    ppu._SHUTDOWN.clear()


def test_shutdown_callback_runs() -> None:
    seen: list[object] = []

    def _cb(ex) -> None:
        seen.append(ex)

    ppu.add_process_pool_shutdown_callback(_cb)
    try:
        ex = ppu.register_process_pool(ProcessPoolExecutor(max_workers=1))
        ppu.shutdown_process_pool_executor(ex, kill_workers=True)
        assert seen == [ex]
    finally:
        if _cb in ppu._SHUTDOWN_CALLBACKS:
            ppu._SHUTDOWN_CALLBACKS.remove(_cb)
