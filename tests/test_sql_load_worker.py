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
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with MCToolkit. If not, see <https://www.gnu.org/licenses/>.

"""SQL load worker: off-GUI fetch + SMILES parse."""

from __future__ import annotations

import sqlite3
import threading

from PySide6.QtCore import QObject

from mctoolkit.platform_support.tool_progress import ToolProgressState
from mctoolkit.workers.sql_load_worker import SqlLoadParseResult, SqlLoadSignals, SqlLoadWorker


class _Collector(QObject):
    def __init__(self) -> None:
        super().__init__()
        self.results: list[object] = []
        self.chunks: list[object] = []
        self.errors: list[str] = []

    def on_finished(self, result: object) -> None:
        self.results.append(result)

    def on_chunk(self, result: object) -> None:
        self.chunks.append(result)

    def on_failed(self, msg: str) -> None:
        self.errors.append(msg)


def test_sql_load_worker_parses_smiles(tmp_path) -> None:
    db_path = tmp_path / "sample.sqlite"
    con = sqlite3.connect(str(db_path))
    try:
        cur = con.cursor()
        cur.execute("CREATE TABLE compounds (SMILES TEXT, Note TEXT)")
        cur.execute("INSERT INTO compounds VALUES ('CCO', 'ethanol')")
        cur.execute("INSERT INTO compounds VALUES ('not-a-smiles', 'bad')")
        cur.execute("INSERT INTO compounds VALUES ('CCN', 'ethylamine')")
        con.commit()
    finally:
        con.close()

    url = "sqlite:///" + str(db_path).replace("\\", "/")
    signals = SqlLoadSignals()
    collector = _Collector()
    signals.chunk.connect(collector.on_chunk)
    signals.finished.connect(collector.on_finished)
    signals.failed.connect(collector.on_failed)
    state = ToolProgressState()
    state.begin("SQL load", 3)
    worker = SqlLoadWorker(
        url=url,
        engine_kwargs={},
        sql="SELECT * FROM compounds",
        page_size=64,
        limit_eff=10,
        apply_limit=True,
        signals=signals,
        generation=1,
        progress_state=state,
    )
    worker.run()
    assert not collector.errors
    assert len(collector.chunks) >= 1
    assert len(collector.results) == 1
    prepared = [row for chunk in collector.chunks for row in chunk.prepared_rows]
    blobs = {}
    for chunk in collector.chunks:
        blobs.update(chunk.mol_blobs)
    assert len(prepared) == 3
    result = collector.results[0]
    assert isinstance(result, SqlLoadParseResult)
    assert result.next_oid == 3
    assert result.is_last
    assert not result.prepared_rows
    assert 0 in blobs
    assert 1 not in blobs
    assert 2 in blobs
    msg, done, total, active = state.snapshot()
    assert active
    assert done >= 3
    assert "SQL load" in msg
    state.end()


def test_sql_load_worker_emits_one_chunk_per_page(tmp_path) -> None:
    db_path = tmp_path / "paged.sqlite"
    con = sqlite3.connect(str(db_path))
    try:
        con.execute("CREATE TABLE compounds (SMILES TEXT)")
        con.executemany("INSERT INTO compounds VALUES (?)", [("CCO",), ("CCN",), ("CCC",)])
        con.commit()
    finally:
        con.close()

    url = "sqlite:///" + str(db_path).replace("\\", "/")
    signals = SqlLoadSignals()
    collector = _Collector()
    signals.chunk.connect(collector.on_chunk)
    signals.finished.connect(collector.on_finished)
    signals.failed.connect(collector.on_failed)
    SqlLoadWorker(
        url=url,
        engine_kwargs={},
        sql="SELECT * FROM compounds",
        page_size=1,
        limit_eff=10,
        apply_limit=True,
        signals=signals,
        generation=1,
    ).run()
    assert not collector.errors
    assert len(collector.chunks) == 3
    assert all(len(c.prepared_rows) == 1 for c in collector.chunks)
    assert collector.chunks[0].is_first
    assert collector.results[0].next_oid == 3
    assert max(len(c.prepared_rows) for c in collector.chunks) == 1


def test_sql_load_worker_cancelled_before_run() -> None:
    signals = SqlLoadSignals()
    collector = _Collector()
    signals.failed.connect(collector.on_failed)
    cancel = threading.Event()
    cancel.set()
    worker = SqlLoadWorker(
        url="sqlite:///:memory:",
        engine_kwargs={},
        sql="SELECT 1",
        page_size=64,
        limit_eff=0,
        apply_limit=False,
        signals=signals,
        generation=1,
        cancel_event=cancel,
    )
    worker.run()
    assert collector.errors == ["Cancelled."]
