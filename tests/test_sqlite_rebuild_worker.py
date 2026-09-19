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

"""SqliteRebuildWorker (background SQLite mirror rebuild)."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThreadPool

from molmanager.storage import SqliteTableStore
from molmanager.workers import SqliteRebuildSignals, SqliteRebuildWorker


def test_sqlite_rebuild_worker_builds_queryable_db(qapp, tmp_path):  # noqa: ARG001
    sig = SqliteRebuildSignals()
    results: list[tuple[int, str]] = []

    sig.finished.connect(lambda gen, path: results.append((gen, path)))
    db_path = str(tmp_path / "mirror.sqlite3")
    headers = ["ID_HIDDEN", "Structure", "SMILES", "Score"]
    entries = [
        (1, {"SMILES": "CCO", "Score": "1.0"}),
        (2, {"SMILES": "CCN", "Score": "9.0"}),
    ]
    pool = QThreadPool()
    pool.start(SqliteRebuildWorker(3, headers, entries, db_path, sig))
    assert pool.waitForDone(60_000)
    qapp.processEvents()
    assert results and results[0][0] == 3
    store = SqliteTableStore(Path(results[0][1]))
    try:
        assert store.count() == 2
        assert store.count(where_sql='CAST("Score" AS REAL) >= ?', args=(5.0,)) == 1
    finally:
        store.close()


def test_sqlite_rebuild_worker_reports_write_progress(qapp, tmp_path):  # noqa: ARG001
    from molmanager.platform_support.tool_progress import ToolProgressState

    sig = SqliteRebuildSignals()
    results: list[tuple[int, str]] = []
    sig.finished.connect(lambda gen, path: results.append((gen, path)))
    db_path = str(tmp_path / "mirror_prog.sqlite3")
    headers = ["ID_HIDDEN", "Structure", "SMILES"]
    entries = [(i, {"SMILES": "C"}) for i in range(5)]
    state = ToolProgressState()
    state.begin("Indexing table", 5)
    pool = QThreadPool()
    pool.start(
        SqliteRebuildWorker(
            1,
            headers,
            entries,
            db_path,
            sig,
            progress_state=state,
        )
    )
    assert pool.waitForDone(60_000)
    qapp.processEvents()
    assert results
    msg, done, total, active = state.snapshot()
    assert active
    assert done >= 5
    assert "Indexing" in msg
    state.end()
    store = SqliteTableStore(Path(results[0][1]))
    try:
        assert store.count() == 5
    finally:
        store.close()


def test_schedule_sqlite_rebuild_writes_off_gui(qapp, tmp_path):  # noqa: ARG001
    """GUI exports cell text; worker writes/indexes the mirror."""
    import time

    from PySide6.QtWidgets import QApplication

    from molmanager.ui.main_window import ChemistryWorkspaceWindow

    w = ChemistryWorkspaceWindow()
    w.headers = ["ID_HIDDEN", "Structure", "SMILES", "Note"]
    w._table_model.set_headers(list(w.headers))
    w._table_model.append_rows_batch(
        [
            (0, {"SMILES": "CCO", "Note": "a"}),
            (1, {"SMILES": "CCN", "Note": "b"}),
            (2, {"SMILES": "CCC", "Note": "c"}),
        ]
    )
    w.next_oid = 3
    w._sqlite_store_dirty = True
    w._schedule_sqlite_rebuild()
    deadline = time.monotonic() + 30.0
    while time.monotonic() < deadline:
        QApplication.processEvents()
        if not w._sqlite_rebuild_in_progress and getattr(w, "_sqlite_export_ctx", None) is None:
            break
        time.sleep(0.01)
    assert not w._sqlite_rebuild_in_progress
    assert w._sqlite_store is not None
    assert w._sqlite_store.count() == 3
    w.close()
