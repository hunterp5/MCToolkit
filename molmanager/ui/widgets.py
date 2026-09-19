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

"""Small reusable widgets; filter cards live in :mod:`molmanager.ui.filters.cards`."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QTableWidgetItem

from ..chem.molecule_conversion import safe_float

from .filters.cards import (
    CategoryFilterCard,
    FilterCard,
    SubstructureFilterCard,
    TextFilterCard,
    style_filter_card_remove_button,
)

__all__ = [
    "CategoryFilterCard",
    "FilterCard",
    "NumericTableWidgetItem",
    "SubstructureFilterCard",
    "TextFilterCard",
    "style_filter_card_remove_button",
]


class NumericTableWidgetItem(QTableWidgetItem):
    def __lt__(self, other):
        val = safe_float(self.data(Qt.EditRole))
        other_val = safe_float(other.data(Qt.EditRole))
        if val is None:
            return True
        if other_val is None:
            return False
        return val < other_val
