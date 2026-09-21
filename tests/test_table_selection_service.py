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

"""Tests for table selection helpers (no Qt)."""

from __future__ import annotations

from mctoolkit.services.table_selection import (
    cached_string_key,
    collect_canonical_keys_from_column,
    first_rows_for_distinct_keys,
    logical_rows_for_oids,
    oids_for_source_rows,
    oids_from_id_hidden_cells,
    rows_where,
    structure_row_is_empty,
)


def test_oids_for_source_rows() -> None:
    assert oids_for_source_rows([0, 2, 9], row_oid=lambda r: r * 10) == frozenset({0, 20, 90})
    assert oids_for_source_rows([], row_oid=lambda r: r) == frozenset()


def test_oids_from_id_hidden_cells() -> None:
    cells = {0: "1", 1: "x", 2: "3"}
    assert oids_from_id_hidden_cells(
        [0, 1, 2],
        cell_text_col0=lambda r: cells[r],
    ) == frozenset({1, 3})


def test_logical_rows_for_oids() -> None:
    mapping = {10: 0, 20: 2, 30: -1}
    assert logical_rows_for_oids(
        [20, 10, 30, 20],
        logical_row_for_oid=lambda oid: mapping.get(oid, -1),
    ) == [0, 2]


def test_first_rows_for_distinct_keys() -> None:
    keys = {0: "a", 1: "", 2: "a", 3: "b"}
    assert first_rows_for_distinct_keys(
        [0, 1, 2, 3],
        key_for_row=lambda r: keys[r],
    ) == [0, 3]


def test_rows_where() -> None:
    assert rows_where(range(5), predicate=lambda r: r % 2 == 0) == [0, 2, 4]


def test_cached_string_key() -> None:
    calls: list[str] = []

    def key_fn(s: str) -> str:
        calls.append(s)
        return s.upper()

    cache: dict[str, str] = {}
    assert cached_string_key("ab", cache, key_fn=key_fn) == "AB"
    assert cached_string_key("ab", cache, key_fn=key_fn) == "AB"
    assert calls == ["ab"]


def test_collect_canonical_keys_from_column() -> None:
    texts = ["CCO", "", "c1ccccc1", "bad"]
    keys = collect_canonical_keys_from_column(
        len(texts),
        cell_text=lambda r: texts[r],
        key_fn=lambda s: s if s in {"CCO", "c1ccccc1"} else None,
    )
    assert keys == {"CCO", "c1ccccc1"}


def test_structure_row_is_empty() -> None:
    assert (
        structure_row_is_empty(
            mol_present=True,
            smiles_text="",
            probe_cells=[],
            is_smiles_named=lambda _h: False,
            header_looks_structural=lambda _h: False,
            is_tool_generated=lambda _h: False,
            looks_like_mol_block=lambda _t: False,
        )
        is False
    )
    assert (
        structure_row_is_empty(
            mol_present=False,
            smiles_text="CCO",
            probe_cells=[],
            is_smiles_named=lambda _h: False,
            header_looks_structural=lambda _h: False,
            is_tool_generated=lambda _h: False,
            looks_like_mol_block=lambda _t: False,
        )
        is False
    )
    assert (
        structure_row_is_empty(
            mol_present=False,
            smiles_text="",
            probe_cells=[("Note", "hello")],
            is_smiles_named=lambda _h: False,
            header_looks_structural=lambda _h: False,
            is_tool_generated=lambda _h: False,
            looks_like_mol_block=lambda _t: False,
        )
        is True
    )
    assert (
        structure_row_is_empty(
            mol_present=False,
            smiles_text="",
            probe_cells=[("SMILES", "CCO")],
            is_smiles_named=lambda h: h == "SMILES",
            header_looks_structural=lambda _h: False,
            is_tool_generated=lambda _h: False,
            looks_like_mol_block=lambda _t: False,
        )
        is False
    )
