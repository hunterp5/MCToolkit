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

"""Dialog to choose which filter type to add to the filter panel."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
)

FILTER_TYPE_CHOICES: tuple[tuple[str, str, str], ...] = (
    ("substructure", "Substructure", "Match a SMARTS pattern against a structure source."),
    ("slider", "Slider", "Numeric range filter on a column."),
    ("text", "Text", "Text contains / equals filter on a column."),
    ("category", "Category", "Multi-select category filter on a column."),
)


class AddFilterDialog(QDialog):
    """Pick a filter type to add to the filter panel."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add Filter")
        self.setModal(True)
        self.setMinimumWidth(320)
        self._chosen: str | None = None

        root = QVBoxLayout(self)
        tip = QLabel("Choose a filter type to add:")
        tip.setWordWrap(True)
        root.addWidget(tip)

        self._list = QListWidget()
        self._list.setMinimumHeight(140)
        for kind, label, tip_text in FILTER_TYPE_CHOICES:
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, kind)
            item.setToolTip(tip_text)
            self._list.addItem(item)
        self._list.setCurrentRow(0)
        self._list.itemDoubleClicked.connect(self._accept_current)
        root.addWidget(self._list)

        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        box.accepted.connect(self._accept_current)
        box.rejected.connect(self.reject)
        root.addWidget(box)

    def selected_kind(self) -> str | None:
        return self._chosen

    def _accept_current(self, *_args) -> None:
        item = self._list.currentItem()
        if item is None:
            return
        self._chosen = str(item.data(Qt.UserRole) or "")
        if not self._chosen:
            return
        self.accept()
