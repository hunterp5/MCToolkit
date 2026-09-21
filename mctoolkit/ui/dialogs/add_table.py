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

"""Data → Table → Add Row / Add Column count dialogs."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
)

MAX_ADD_ROWS = 10_000
MAX_ADD_COLUMNS = 200


class AddTableRowsDialog(QDialog):
    """How many empty rows to append."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add Row")
        self.setMinimumWidth(280)
        root = QVBoxLayout(self)
        form = QFormLayout()
        self.count_sb = QSpinBox()
        self.count_sb.setRange(1, MAX_ADD_ROWS)
        self.count_sb.setValue(1)
        self.count_sb.setToolTip("Number of empty rows to append at the bottom of the table.")
        form.addRow("Rows:", self.count_sb)
        root.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def row_count(self) -> int:
        return int(self.count_sb.value())


class AddTableColumnsDialog(QDialog):
    """Name and how many empty columns to append."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add Column")
        self.setMinimumWidth(320)
        root = QVBoxLayout(self)
        form = QFormLayout()
        self.name_edit = QLineEdit("Column")
        self.name_edit.setToolTip(
            "Base name. Extra columns get a numeric suffix when the name exists."
        )
        form.addRow("Name:", self.name_edit)
        self.count_sb = QSpinBox()
        self.count_sb.setRange(1, MAX_ADD_COLUMNS)
        self.count_sb.setValue(1)
        self.count_sb.setToolTip("Number of empty columns to append on the right.")
        form.addRow("Columns:", self.count_sb)
        root.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        self.name_edit.selectAll()

    def column_name(self) -> str:
        return self.name_edit.text()

    def column_count(self) -> int:
        return int(self.count_sb.value())
