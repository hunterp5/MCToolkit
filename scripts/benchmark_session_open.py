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

"""Measure GUI-thread stalls while opening a ``.cms`` session.

A high-frequency QTimer records the gap between successive fires. When the GUI
thread is blocked, the timer cannot fire, so a large gap is a direct measure of
a freeze exactly as the user perceives it.

Usage:
    python scripts/benchmark_session_open.py samples/bindingdb_10k.cms [--no-render]
"""

from __future__ import annotations

import argparse
import contextlib
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
    ap.add_argument(
        "--no-webengine",
        action="store_true",
        help="skip the QtWebEngine preload (Chromium can crash under offscreen Qt)",
    )
    ap.add_argument("--stall-ms", type=float, default=50.0)
    ap.add_argument("--max-s", type=float, default=180.0)
    args = ap.parse_args()

    if args.no_render:
        os.environ["MOLMANAGER_AUTO_RENDER_2D_MAX_ROWS"] = "0"

    # QtWebEngine must register with Qt before QApplication, exactly as molmanager.app does,
    # or docked-plot restore fails and the measurement misses its real cost.
    from molmanager.platform_support.qt_webengine_flags import configure_qtwebengine_quiet_logs

    if not args.no_webengine:
        configure_qtwebengine_quiet_logs()
        with contextlib.suppress(ImportError):
            import PySide6.QtWebEngineWidgets  # noqa: F401

    from molmanager.ui.main_window.chemistry_workspace_window import ChemistryWorkspaceWindow

    app = QApplication.instance() or QApplication(sys.argv)
    win = ChemistryWorkspaceWindow()

    cum: dict[str, float] = {}
    call_log: list[tuple[str, float]] = []

    def wrap(obj, name: str, label: str | None = None) -> None:
        orig = getattr(obj, name)
        key = label or name

        def wrapped(*a, **k):
            t0 = time.perf_counter()
            try:
                return orig(*a, **k)
            finally:
                dt = time.perf_counter() - t0
                cum[key] = cum.get(key, 0.0) + dt
                if dt * 1000.0 >= 30.0:
                    call_log.append((key, dt * 1000.0))

        setattr(obj, name, wrapped)

    marks: dict[str, float] = {}

    def mark(name: str) -> None:
        if name not in marks:
            marks[name] = time.perf_counter() - t_start

    for name, label in (
        ("_on_session_rows_parsed", "rows_parsed"),
        ("_reveal_table_after_session_prep", "reveal"),
    ):
        orig = getattr(win, name)

        def make(orig=orig, label=label):
            def wrapped(*a, **k):
                mark(label)
                return orig(*a, **k)

            return wrapped

        setattr(win, name, make())

    for name in (
        "apply_saved_session_from_file",
        "_apply_session_document",
        "_session_restore_apply_step",
        "_finalize_session_filters",
        "_finalize_session_workspace_and_plots",
        "_finalize_session_table_chrome",
        "_finalize_session_sidecars_and_reveal",
        "clear_all",
        "apply_filters",
        "_restore_docked_plots",
        "_restore_floating_plots",
        "_restore_protein_viewer",
        "_restore_pending_workspace_layout",
        "_restore_column_visual_order",
        "_restore_table_layout",
        "_restore_session_table_chrome",
        "_restore_pending_session_som_maps",
        "_migrate_legacy_confs_cells_to_sidecar",
        "_try_auto_render_all_structures_after_ingest",
        "_finish_deferred_session_workspace_restore",
        "_rerun_restored_table_search",
        "_discard_floating_plot_dialogs",
        "_discard_docked_plot_widgets",
        "_deferred_session_post_load_follow_up",
        "_reveal_table_after_session_prep",
    ):
        if hasattr(win, name):
            wrap(win, name)
    for name in ("append_rows_batch", "set_headers", "clear_rows", "sort"):
        if hasattr(win._table_model, name):
            wrap(win._table_model, name, f"model.{name}")

    import importlib

    for mod_path, fn_name in (
        ("molmanager.analysis.mmp_session", "restore_mmp_ledger_for_session"),
        ("molmanager.docking.pose_file_io", "restore_dock_results_for_session"),
        ("molmanager.ui.som_browser", "restore_som_maps_for_session"),
        ("molmanager.ionization.microstate_cache", "restore_ionization_sidecar"),
    ):
        try:
            mod = importlib.import_module(mod_path)
        except ImportError:
            continue
        if hasattr(mod, fn_name):
            wrap(mod, fn_name, f"{mod_path.rsplit('.', 1)[-1]}.{fn_name}")

    from molmanager.table import session_codec

    for name in ("loads_session_bytes", "expand_session_document"):
        orig = getattr(session_codec, name)

        def make_codec(orig=orig, key=f"codec.{name}"):
            def wrapped(*a, **k):
                t0 = time.perf_counter()
                try:
                    return orig(*a, **k)
                finally:
                    cum[key] = cum.get(key, 0.0) + (time.perf_counter() - t0)

            return wrapped

        setattr(session_codec, name, make_codec())
        # session_save/session_restore import these by name.
        for mod_name in (
            "molmanager.ui.session_save",
            "molmanager.ui.session_restore",
        ):
            mod = sys.modules.get(mod_name)
            if mod is not None and hasattr(mod, name):
                setattr(mod, name, getattr(session_codec, name))

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
            except (AttributeError, RuntimeError):
                phase = ""
            stalls.append((now - t_start, gap_ms, phase))

    detector = QTimer()
    detector.setInterval(8)
    detector.timeout.connect(tick)
    detector.start()

    state = {"render_started": False, "done": False, "t_done": 0.0}

    def watchdog() -> None:
        if state["done"]:
            return
        revealed = win._table_stack.currentIndex() == 1
        busy = bool(getattr(win, "_session_parse_busy", False))
        busy = busy or getattr(win, "_session_restore_ctx", None) is not None
        busy = busy or getattr(win, "_session_finalize_ctx", None) is not None
        busy = busy or bool(getattr(win, "_session_awaiting_ready", False))
        render_active = bool(getattr(win, "_render2d_batch_active", False))
        if render_active:
            state["render_started"] = True
        if args.no_render:
            finished = revealed and not busy
        else:
            finished = revealed and not busy and state["render_started"] and not render_active
        if finished:
            state["done"] = True
            state["t_done"] = time.perf_counter() - t_start
            QTimer.singleShot(300, app.quit)

    wd = QTimer()
    wd.setInterval(100)
    wd.timeout.connect(watchdog)
    wd.start()

    QTimer.singleShot(int(args.max_s * 1000), app.quit)
    QTimer.singleShot(0, lambda: win.apply_saved_session_from_file(args.path))

    app.exec()

    wall = state["t_done"] if state["done"] else (time.perf_counter() - t_start)
    big = [s for s in stalls if s[1] >= 100.0]
    total_stall = sum(s[1] for s in stalls) / 1000.0
    print("=" * 70)
    print(f"session         : {args.path}")
    print(f"rows            : {win._table_model.rowCount():,}")
    print(f"auto render     : {'off' if args.no_render else 'on'}")
    print(f"completed       : {state['done']}  wall={wall:.2f}s")
    print(f"stalls >= {args.stall_ms:.0f}ms : {len(stalls)}  (>=100ms: {len(big)})")
    print(f"total stall time: {total_stall:.2f}s")
    print(f"worst stall     : {max((s[1] for s in stalls), default=0.0):.1f}ms")
    print("top stalls (t_since_start_s, gap_ms, phase):")
    for t, gap, phase in sorted(stalls, key=lambda x: -x[1])[:12]:
        print(f"  t={t:6.2f}s  gap={gap:8.1f}ms  {phase[:58]}")
    print("phase marks (s since start):")
    for key in ("rows_parsed", "reveal"):
        if key in marks:
            print(f"  {marks[key]:7.2f}s  {key}")
    print("cumulative GUI time (ms):")
    for name, total in sorted(cum.items(), key=lambda x: -x[1]):
        print(f"  {total * 1000:9.1f}ms  {name}")


if __name__ == "__main__":
    main()
