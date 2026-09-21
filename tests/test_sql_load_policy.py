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

from __future__ import annotations

import pytest

from mctoolkit.services.sql_load_policy import (
    engine_kwargs_for_sql_load,
    make_sqlite_read_only_creator,
    sql_looks_destructive,
    sqlite_database_path_from_url,
)
from mctoolkit.services.table_scope import collect_scoped_pairs, resolve_structure_row_for_oid


@pytest.mark.parametrize(
    "sql,expect",
    [
        ("SELECT * FROM compounds", False),
        ("  select id, smiles from t where mw > 100", False),
        ("INSERT INTO t VALUES (1)", True),
        ("DELETE FROM t", True),
        ("DROP TABLE t", True),
        ("UPDATE t SET x=1", True),
        ("WITH x AS (SELECT 1) INSERT INTO t SELECT * FROM x", True),
        ("SELECT a INTO b FROM c", True),
        ("SELECT 1; DELETE FROM t", True),
        ("-- comment\nSELECT * FROM t", False),
        ("/* block */\nTRUNCATE TABLE t", True),
    ],
)
def test_sql_looks_destructive(sql: str, expect: bool) -> None:
    assert sql_looks_destructive(sql) is expect


def test_sqlite_database_path_from_url() -> None:
    assert sqlite_database_path_from_url("sqlite:///C:/data/mols.db") == "C:/data/mols.db"
    assert sqlite_database_path_from_url("sqlite:///:memory:") is None


def test_engine_kwargs_read_only_sqlite(tmp_path) -> None:
    import sqlite3

    db = tmp_path / "x.db"
    sqlite3.connect(str(db)).close()
    url = "sqlite:///" + str(db).replace("\\", "/")
    out_url, eng_kw = engine_kwargs_for_sql_load(
        url,
        read_only=True,
        sqlite_timeout_s=30.0,
        pg_connect_timeout=10,
    )
    assert out_url == "sqlite://"
    assert callable(eng_kw.get("creator"))
    # Creator must open the file.
    con = eng_kw["creator"]()
    con.close()


def test_make_sqlite_read_only_creator_blocks_writes(tmp_path) -> None:
    import sqlite3

    db = tmp_path / "ro.db"
    con = sqlite3.connect(str(db))
    con.execute("CREATE TABLE t (x INTEGER)")
    con.commit()
    con.close()

    creator = make_sqlite_read_only_creator(str(db), timeout_s=5.0)
    ro = creator()
    with pytest.raises(sqlite3.OperationalError):
        ro.execute("INSERT INTO t VALUES (1)")
    ro.close()


def test_collect_scoped_pairs_filters() -> None:
    oids = [10, 20, 30]
    values = {0: "a", 1: None, 2: "c"}

    got = collect_scoped_pairs(
        3,
        row_oid=lambda r: oids[r],
        resolve=lambda r, oid: values[r],
        allowed_oids={10, 30},
    )
    assert got == [(10, "a"), (30, "c")]


def test_resolve_structure_row_for_oid_prefers_valid_batch_map() -> None:
    row = resolve_structure_row_for_oid(
        7,
        row_count=3,
        cell_text_col0=lambda r: "7" if r == 1 else "0",
        logical_row_for_oid=lambda oid: 99,
        render2d_row_by_oid={7: 1},
    )
    assert row == 1


def test_resolve_structure_row_for_oid_falls_back() -> None:
    row = resolve_structure_row_for_oid(
        7,
        row_count=3,
        cell_text_col0=lambda r: "0",
        logical_row_for_oid=lambda oid: 2,
        render2d_row_by_oid={7: 1},
    )
    assert row == 2
