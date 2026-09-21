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

"""Chunked SQLite row export from CompoundTableModel."""

from __future__ import annotations

from mctoolkit.ui.compound_table_model import CompoundTableModel


def test_export_rows_for_sqlite_slice() -> None:
    model = CompoundTableModel(["ID_HIDDEN", "Structure", "SMILES", "MW"])
    model.append_rows_batch(
        [
            (0, {"SMILES": "CCO", "MW": "46"}),
            (1, {"SMILES": "CC", "MW": "30"}),
            (2, {"SMILES": "C", "MW": "16"}),
        ]
    )
    part = model.export_rows_for_sqlite_slice(["SMILES", "MW"], 1, 3)
    assert part == [(1, {"SMILES": "CC", "MW": "30"}), (2, {"SMILES": "C", "MW": "16"})]
    full = model.export_rows_for_sqlite(["SMILES"])
    assert len(full) == 3
