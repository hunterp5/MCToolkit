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

"""Read displayed table cells without taking the rest of the window.

Dialogs and services used to walk rows through ``app._table_cell_text``. That private
name is what kept row-reading logic in ``ui/``. :class:`TableCellReader` is the public
contract the window implements; callers type against this instead of ``AppKernel``.
"""

from __future__ import annotations

from typing import Protocol


class TableCellReader(Protocol):
    """Displayed cell text plus enough identity to resolve a row.

    The window implements this. Domain and dialog code must not reach
    ``app._table_cell_text``.
    """

    headers: list

    def cell_text(self, row: int, col: int) -> str: ...
    def logical_row_for_oid(self, oid: int) -> int: ...


def cell_or_backing(
    reader: TableCellReader,
    row: int,
    header: str,
    *,
    backing_value: str = "",
) -> str:
    """Prefer a stored backing string, then the displayed cell for *header*."""
    if backing_value:
        return backing_value
    try:
        col = reader.headers.index(header)
    except ValueError:
        return ""
    return reader.cell_text(row, col) or ""
