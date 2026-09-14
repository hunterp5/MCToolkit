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

"""Proxy model for scalable table visibility filtering."""

from __future__ import annotations

from PyQt5.QtCore import QSortFilterProxyModel


class FilterProxyModel(QSortFilterProxyModel):
    """Filter rows by source-model OID membership."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._visible_oids: frozenset[int] | None = None

    def visible_oids(self) -> frozenset[int] | None:
        """OIDs currently accepted by the filter. ``None`` means every row is visible."""
        return self._visible_oids

    def set_visible_oids(self, oids: frozenset[int] | None) -> None:
        new_oids = None if oids is None else frozenset(int(x) for x in oids)
        if new_oids == self._visible_oids:
            return
        self._visible_oids = new_oids
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row: int, source_parent) -> bool:  # noqa: N802
        if self._visible_oids is None:
            return True
        src = self.sourceModel()
        if src is None:
            return True
        try:
            oid = int(src.row_oid(source_row))
        except Exception:
            return False
        return oid in self._visible_oids
