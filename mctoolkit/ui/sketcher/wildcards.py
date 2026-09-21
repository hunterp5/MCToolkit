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

"""Wildcard atom helpers and element-picker dialog."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..qt_widget_utils import make_window_minimizable
from ...chem.sketch_symbols import DEFAULT_WILDCARD_ELEMENTS, WILDCARD_ELEMENT_CHOICES
from ...chem.sketch_wildcards import (
    _is_wildcard_node,
    _normalize_wildcard_elements,
    _wildcard_query_smarts,
    _wildcard_symbol_to_smarts_token,
)

__all__ = [
    "WildcardElementsDialog",
    "_is_wildcard_node",
    "_normalize_wildcard_elements",
    "_wildcard_query_smarts",
    "_wildcard_symbol_to_smarts_token",
]


class WildcardElementsDialog(QDialog):
    """Pick which elements a wildcard atom may match (SMARTS ``[#6,#7]``, …)."""

    def __init__(self, initial: list[str] | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Wildcard elements")
        self.resize(360, 480)
        ly = QVBoxLayout(self)
        ly.addWidget(
            QLabel(
                "Select one or more elements this wildcard may represent.\n"
                "The sketch exports as SMARTS (e.g. [#6,#7]) for that position."
            )
        )
        self._checks: dict[str, QCheckBox] = {}
        sel = set(initial or DEFAULT_WILDCARD_ELEMENTS)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setMaximumHeight(340)
        inner = QWidget()
        grid = QGridLayout(inner)
        for i, sym in enumerate(WILDCARD_ELEMENT_CHOICES):
            cb = QCheckBox(sym)
            cb.setChecked(sym in sel)
            self._checks[sym] = cb
            grid.addWidget(cb, i // 2, i % 2)
        scroll.setWidget(inner)
        ly.addWidget(scroll)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        ly.addWidget(bb)
        make_window_minimizable(self)

    def selected_elements(self) -> list[str]:
        return [s for s in WILDCARD_ELEMENT_CHOICES if self._checks[s].isChecked()]
