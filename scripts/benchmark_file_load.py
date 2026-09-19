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

"""Measure GUI-thread stalls while loading a file into the table.

A high-frequency QTimer records the gap between successive fires. When the GUI
thread is blocked, the timer cannot fire, so a large gap is a direct measure of
a freeze exactly as the user perceives it.

Usage:
    python scripts/benchmark_file_load.py samples/binding_db_pubchem_25k.sdf [--no-render]
"""

from __future__ import annotations

import argparse
import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--no-render", action="store_true", help="skip auto 2D render")
    ap.add_argument("--stall-ms", type=float, default=50.0)
    ap.add_argument("--max-s", type=float, default=180.0)
    args = ap.parse_args()

    if args.no_render:
        os.environ["MOLMANAGER_AUTO_RENDER_2D_MAX_ROWS"] = "0"

    from molmanager.ui.main_window.chemistry_workspace_window import ChemistryWorkspaceWindow

    app = QApplication.instance() or QApplication(sys.argv)
    win = ChemistryWorkspaceWindow()

    # Use a private, fresh SQLite cache so runs are reproducible and never blocked by a stale
    # shared temp DB left by a previous load.
    import tempfile

    from molmanager.storage import SqliteTableStore

    fd, priv_db = tempfile.mkstemp(prefix="bench_molmanager_", suffix=".sqlite3")
    os.close(fd)
    os.unlink(priv_db)
    try:
        old_store = win._sqlite_store
        win._sqlite_store = SqliteTableStore(priv_db)
        old_store.close()
    except Exception:
        pass

    call_log: list[tuple[str, float]] = []

    def wrap(obj, name):
        orig = getattr(obj, name)

        def wrapped(*a, **k):
            t0 = time.perf_counter()
            try:
                return orig(*a, **k)
            finally:
                dt = (time.perf_counter() - t0) * 1000.0
                if dt >= 30.0:
                    call_log.append((name, dt))

        setattr(obj, name, wrapped)

    marks: dict[str, float] = {}

    def mark(name):
        if name not in marks:
            marks[name] = time.perf_counter() - t_start

    cum: dict[str, float] = {}

    def wrap_cum(obj, name):
        orig = getattr(obj, name)

        def wrapped(*a, **k):
            t0 = time.perf_counter()
            try:
                return orig(*a, **k)
            finally:
                cum[name] = cum.get(name, 0.0) + (time.perf_counter() - t0)

        setattr(obj, name, wrapped)

    for _nm, _mk in (
        ("_finalize_ingest_on_gui_thread", "gui_ingest_done"),
        ("_reveal_table_after_ingest_prep", "reveal"),
    ):
        _orig = getattr(win, _nm)

        def _mk_wrap(orig=_orig, mkname=_mk):
            def _w(*a, **k):
                mark(mkname)
                return orig(*a, **k)

            return _w

        setattr(win, _nm, _mk_wrap())

    for nm in (
        "_process_next_chunk",
        "_ingest_sqlite_begin_bulk",
        "_finalize_ingest_on_gui_thread",
        "_deferred_post_ingest_follow_up",
    ):
        wrap(win, nm)
    for nm in ("set_headers", "clear_rows", "end_silent_appends"):
        wrap(win._table_model, nm)
    for nm in (
        "_process_next_chunk",
        "_ingest_append_batch_items",
        "_ingest_sqlite_append_batch",
        "_ingest_sqlite_entries_from_rows",
    ):
        wrap_cum(win, nm)
    wrap_cum(win._table_model, "append_rows_batch")
    store = getattr(win, "_sqlite_store", None)
    if store is not None:
        for nm in ("begin_bulk_load", "append_bulk_rows", "finalize_bulk_load"):
            wrap(store, nm)

    stalls: list[tuple[float, float, str]] = []
    t_start = time.perf_counter()
    last = {"t": time.perf_counter()}

    def tick() -> None:
        now = time.perf_counter()
        gap_ms = (now - last["t"]) * 1000.0
        last["t"] = now
        if gap_ms >= args.stall_ms:
            phase = ""
            try:
                phase = win._loading_detail.text().replace("\n", " | ")
                if win._table_stack.currentIndex() == 1:
                    phase = win.status_label.text()
            except Exception:
                pass
            stalls.append((now - t_start, gap_ms, phase))

    detector = QTimer()
    detector.setInterval(8)
    detector.timeout.connect(tick)
    detector.start()

    state = {"render_started": False, "done": False, "t_done": 0.0}

    def watchdog() -> None:
        if state["done"]:
            return
        if getattr(win, "_last_batch_received", False):
            mark("worker_last_batch")
        ingest_active = bool(getattr(win, "_ingest_loading", False))
        revealed = win._table_stack.currentIndex() == 1
        render_active = bool(getattr(win, "_render2d_batch_active", False))
        if render_active:
            state["render_started"] = True
        pending = bool(getattr(win, "_pending_batches", None))
        if args.no_render:
            finished = revealed and not ingest_active and not pending
        else:
            finished = (
                revealed
                and not ingest_active
                and not pending
                and (state["render_started"] and not render_active)
            )
        if finished:
            state["done"] = True
            state["t_done"] = time.perf_counter() - t_start
            QTimer.singleShot(300, app.quit)

    wd = QTimer()
    wd.setInterval(150)
    wd.timeout.connect(watchdog)
    wd.start()

    QTimer.singleShot(int(args.max_s * 1000), app.quit)
    QTimer.singleShot(0, lambda: win.load_file(args.path))

    app.exec()

    wall = state["t_done"] if state["done"] else (time.perf_counter() - t_start)
    big = [s for s in stalls if s[1] >= 100.0]
    total_stall = sum(s[1] for s in stalls) / 1000.0
    print("=" * 70)
    print(f"file            : {args.path}")
    print(f"auto render     : {'off' if args.no_render else 'on'}")
    print(f"completed       : {state['done']}  wall={wall:.2f}s")
    print(f"stalls >= {args.stall_ms:.0f}ms : {len(stalls)}  (>=100ms: {len(big)})")
    print(f"total stall time: {total_stall:.2f}s")
    print("top stalls (t_since_start_s, gap_ms, phase):")
    for t, gap, phase in sorted(stalls, key=lambda x: -x[1])[:15]:
        print(f"  t={t:6.2f}s  gap={gap:8.1f}ms  {phase[:60]}")
    print("phase marks (s since start):")
    for k in ("worker_last_batch", "gui_ingest_done", "reveal"):
        if k in marks:
            print(f"  {marks[k]:7.2f}s  {k}")
    print("cumulative GUI time (s):")
    for name, total in sorted(cum.items(), key=lambda x: -x[1]):
        print(f"  {total:7.2f}s  {name}")
    print("slow calls >= 30ms (name, ms):")
    for name, dt in sorted(call_log, key=lambda x: -x[1])[:20]:
        print(f"  {dt:9.1f}ms  {name}")


if __name__ == "__main__":
    main()
