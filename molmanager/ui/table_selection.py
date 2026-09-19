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

"""Helpers for building Qt item selections from row indices (merged contiguous ranges)."""

from __future__ import annotations

from PySide6.QtCore import QItemSelection


def merge_sorted_row_indices(rows: list[int]) -> list[tuple[int, int]]:
    """Merge sorted unique row indices into inclusive ``(lo, hi)`` spans."""
    if not rows:
        return []
    uniq = sorted({int(r) for r in rows})
    spans: list[tuple[int, int]] = []
    lo = hi = uniq[0]
    for r in uniq[1:]:
        if r == hi + 1:
            hi = r
        else:
            spans.append((lo, hi))
            lo = hi = r
    spans.append((lo, hi))
    return spans


def item_selection_for_view_rows(
    view_model, view_rows: list[int], *, last_col: int
) -> QItemSelection:
    """Build a ``QItemSelection`` from proxy/view row indices using contiguous ranges."""
    selection = QItemSelection()
    for lo, hi in merge_sorted_row_indices(view_rows):
        top = view_model.index(lo, 0)
        bottom = view_model.index(hi, last_col)
        if top.isValid() and bottom.isValid():
            selection.select(top, bottom)
    return selection
