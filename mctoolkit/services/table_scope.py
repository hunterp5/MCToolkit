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
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with MCToolkit.  If not, see <https://www.gnu.org/licenses/>.
"""Scoped table iteration helpers (no Qt)."""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")


def iter_scoped_row_oids(
    row_count: int,
    *,
    row_oid: Callable[[int], int],
    allowed_oids: set[int] | None = None,
    visible_rows: set[int] | None = None,
) -> list[int]:
    """Return source-row indices that pass optional selection / visibility filters."""
    out: list[int] = []
    for r in range(int(row_count)):
        if visible_rows is not None and r not in visible_rows:
            continue
        oid = int(row_oid(r))
        if allowed_oids is not None and oid not in allowed_oids:
            continue
        out.append(r)
    return out


def collect_scoped_pairs(
    row_count: int,
    *,
    row_oid: Callable[[int], int],
    resolve: Callable[[int, int], T | None],
    allowed_oids: set[int] | None = None,
    visible_rows: set[int] | None = None,
    on_row: Callable[[int], None] | None = None,
) -> list[tuple[int, T]]:
    """
    Walk table rows in scope and collect ``(oid, value)`` when ``resolve`` returns non-None.

    ``resolve(row, oid)`` performs structure/SMILES lookup. ``on_row`` is an optional
    progress hook (e.g. pump the Qt event loop every N rows).
    """
    out: list[tuple[int, T]] = []
    for r in range(int(row_count)):
        if on_row is not None:
            on_row(r)
        if visible_rows is not None and r not in visible_rows:
            continue
        oid = int(row_oid(r))
        if allowed_oids is not None and oid not in allowed_oids:
            continue
        value = resolve(r, oid)
        if value is not None:
            out.append((oid, value))
    return out


def resolve_structure_row_for_oid(
    oid: int,
    *,
    row_count: int,
    cell_text_col0: Callable[[int], str],
    logical_row_for_oid: Callable[[int], int],
    render2d_row_by_oid: dict[int, int] | None = None,
) -> int:
    """
    Prefer a batch Render-2D row map when still valid; otherwise fall back to oid lookup.

    Returns ``-1`` when the oid is not present (same convention as Qt model helpers that
    use ``logical_row_for_oid`` returning -1).
    """
    oid_i = int(oid)
    if render2d_row_by_oid and oid_i in render2d_row_by_oid:
        row = int(render2d_row_by_oid[oid_i])
        if 0 <= row < int(row_count):
            t0 = cell_text_col0(row)
            if t0.isdigit() and int(t0) == oid_i:
                return row
    return int(logical_row_for_oid(oid_i))
