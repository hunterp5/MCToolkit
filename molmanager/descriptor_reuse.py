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

"""Detect valid precomputed descriptor cells and fingerprint cache entries."""

from __future__ import annotations

from collections.abc import Callable, Iterable

_INVALID_CELLS = frozenset({"", "n/a", "na", "none", "-"})


def is_valid_descriptor_cell(value: str | None) -> bool:
    """True when a table cell holds a usable descriptor value."""
    if value is None:
        return False
    text = str(value).strip()
    if not text:
        return False
    return text.lower() not in _INVALID_CELLS


def column_complete_for_oids(
    column: str,
    oids: Iterable[int],
    *,
    headers: list[str],
    cell_text: Callable[[int, int], str],
    row_for_oid: Callable[[int], int],
) -> bool:
    """True when ``column`` exists and every OID in scope has a valid value."""
    if column not in headers:
        return False
    col_idx = headers.index(column)
    for oid in oids:
        row = row_for_oid(int(oid))
        if row < 0:
            return False
        if not is_valid_descriptor_cell(cell_text(row, col_idx)):
            return False
    return True
