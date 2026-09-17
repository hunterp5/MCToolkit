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
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with MolManager. If not, see <https://www.gnu.org/licenses/>.

"""Tab-separated clipboard grids for Excel-style table copy/paste."""

from __future__ import annotations

import csv
import io


def parse_tsv_grid(text: str) -> list[list[str]]:
    """Parse a clipboard string into a rectangular row-major grid."""
    raw = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    if raw.endswith("\n"):
        raw = raw[:-1]
    if not raw:
        return []
    rows = [list(row) for row in csv.reader(io.StringIO(raw), delimiter="\t")]
    width = max((len(row) for row in rows), default=0)
    for row in rows:
        while len(row) < width:
            row.append("")
    return rows


def format_tsv_grid(grid: list[list[str]]) -> str:
    """Serialize a rectangular grid to Excel-style TSV."""
    if not grid:
        return ""
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter="\t", lineterminator="\n", quoting=csv.QUOTE_MINIMAL)
    for row in grid:
        writer.writerow(row)
    return buf.getvalue().rstrip("\n")


def tsv_grid_is_block(grid: list[list[str]]) -> bool:
    """True when the grid spans more than one cell."""
    if not grid:
        return False
    return len(grid) > 1 or len(grid[0]) > 1
