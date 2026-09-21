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

"""TableCellReader helpers do not need Qt or the window."""

from __future__ import annotations

from mctoolkit.table.cell_reader import cell_or_backing


class _Reader:
    headers = ["ID_HIDDEN", "Structure", "SMILES", "Activity"]

    def cell_text(self, row: int, col: int) -> str:
        grid = {
            (0, 2): "CCO",
            (0, 3): "1.2",
            (1, 3): "displayed",
        }
        return grid.get((row, col), "")

    def logical_row_for_oid(self, oid: int) -> int:
        return oid


def test_cell_or_backing_prefers_backing() -> None:
    assert cell_or_backing(_Reader(), 0, "Activity", backing_value="stored") == "stored"


def test_cell_or_backing_falls_back_to_displayed() -> None:
    assert cell_or_backing(_Reader(), 1, "Activity") == "displayed"


def test_cell_or_backing_unknown_header() -> None:
    assert cell_or_backing(_Reader(), 0, "Missing") == ""
