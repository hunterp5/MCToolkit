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

from __future__ import annotations

from molmanager.storage import SqliteTableStore


def test_sqlite_table_store_distinct_values():
    from molmanager.storage.sqlite_table_store import SqliteTableStore

    store = SqliteTableStore()
    store.rebuild(
        ["ID_HIDDEN", "Structure", "MW"],
        [(1, {"MW": "100"}), (2, {"MW": "200"}), (3, {"MW": "100"})],
    )
    vals = store.distinct_values("MW", limit=10)
    assert vals == ["100", "200"]


def test_sqlite_table_store_incremental_bulk_load():
    store = SqliteTableStore()
    try:
        headers = ["ID_HIDDEN", "Structure", "SMILES", "Name", "Score"]
        store.begin_bulk_load(headers)
        assert store.bulk_loading
        store.append_bulk_rows(
            [
                (1, {"SMILES": "CCO", "Name": "alpha", "Score": "3.2"}),
                (2, {"SMILES": "CCN", "Name": "beta", "Score": "7.1"}),
            ]
        )
        store.append_bulk_rows([(3, {"SMILES": "CCC", "Name": "alphabet", "Score": "9.9"})])
        store.finalize_bulk_load()
        assert not store.bulk_loading
        assert store.count() == 3
        assert store.count(where_sql='CAST("Score" AS REAL) >= ?', args=(7.0,)) == 2
        page = store.fetch_page(
            limit=10,
            where_sql='LOWER("Name") LIKE ?',
            args=("%alpha%",),
            sort_by="Score",
            ascending=False,
        )
        assert [oid for oid, _ in page] == [3, 1]
    finally:
        store.close()


def test_sqlite_table_store_rebuild_and_filter_page():
    store = SqliteTableStore()
    try:
        rows = [
            (1, {"SMILES": "CCO", "Name": "alpha", "Score": "3.2"}),
            (2, {"SMILES": "CCN", "Name": "beta", "Score": "7.1"}),
            (3, {"SMILES": "CCC", "Name": "alphabet", "Score": "9.9"}),
        ]
        store.rebuild(["ID_HIDDEN", "Structure", "SMILES", "Name", "Score"], rows)
        assert store.count() == 3
        assert store.count(where_sql='CAST("Score" AS REAL) >= ?', args=(7.0,)) == 2
        page = store.fetch_page(
            limit=10,
            where_sql='LOWER("Name") LIKE ?',
            args=("%alpha%",),
            sort_by="Score",
            ascending=False,
        )
        assert [oid for oid, _ in page] == [3, 1]
    finally:
        store.close()


def test_sqlite_table_store_fetch_oids_keyset_and_reopen_headers(tmp_path):
    path = tmp_path / "oids.sqlite3"
    store = SqliteTableStore(path)
    try:
        headers = ["ID_HIDDEN", "Structure", "SMILES", "Name"]
        store.rebuild(
            headers,
            [
                (1, {"SMILES": "C", "Name": "a"}),
                (2, {"SMILES": "CC", "Name": "b"}),
                (3, {"SMILES": "CCC", "Name": "c"}),
            ],
        )
        first = store.fetch_oids(limit=2)
        assert first == [1, 2]
        rest = store.fetch_oids(after_oid=first[-1], limit=2)
        assert rest == [3]
        named = store.fetch_oids(where_sql='"Name" = ?', args=("b",), limit=10)
        assert named == [2]
    finally:
        store.close()
    reopened = SqliteTableStore(path)
    try:
        assert "SMILES" in reopened.headers
        assert reopened.count() == 3
    finally:
        reopened.close()
