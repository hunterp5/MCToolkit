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

"""Proxy model for scalable table visibility filtering."""

from __future__ import annotations

from PyQt5.QtCore import QSortFilterProxyModel


class FilterProxyModel(QSortFilterProxyModel):
    """Filter rows by source-model OID membership.

    ``invalidateFilter`` walks every source row; ``filterAcceptsRow`` uses a
    compact per-row accept bitmap built once in :meth:`set_visible_oids` so the
    walk is a byte check instead of OID + hash-set lookup per row.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._visible_oids: frozenset[int] | None = None
        self._row_accept: bytearray | None = None

    def visible_oids(self) -> frozenset[int] | None:
        """OIDs currently accepted by the filter. ``None`` means every row is visible."""
        return self._visible_oids

    def set_visible_oids(self, oids: frozenset[int] | None) -> bool:
        """Update visibility. Returns ``True`` when the accepted set changed."""
        new_oids = None if oids is None else frozenset(int(x) for x in oids)
        if new_oids == self._visible_oids:
            return False
        self._visible_oids = new_oids
        self._rebuild_row_accept()
        self.invalidateFilter()
        return True

    def _rebuild_row_accept(self) -> None:
        """Materialize source-row → accept flags for the current OID set."""
        if self._visible_oids is None:
            self._row_accept = None
            return
        src = self.sourceModel()
        if src is None:
            self._row_accept = None
            return
        n = int(src.rowCount())
        flags = bytearray(n)
        logical = getattr(src, "logical_row_for_oid", None)
        if callable(logical):
            for oid in self._visible_oids:
                r = int(logical(int(oid)))
                if 0 <= r < n:
                    flags[r] = 1
        else:
            row_oid = getattr(src, "row_oid", None)
            if not callable(row_oid):
                self._row_accept = None
                return
            visible = self._visible_oids
            for r in range(n):
                if int(row_oid(r)) in visible:
                    flags[r] = 1
        self._row_accept = flags

    def filterAcceptsRow(self, source_row: int, source_parent) -> bool:  # noqa: N802
        if self._visible_oids is None:
            return True
        flags = self._row_accept
        if flags is not None:
            if 0 <= source_row < len(flags):
                return flags[source_row] != 0
            # Source grew after the last bitmap build — fall back to OID membership.
        src = self.sourceModel()
        if src is None:
            return True
        try:
            oid = int(src.row_oid(source_row))
        except Exception:
            return False
        return oid in self._visible_oids
