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

"""Settings dialog for 2D structure depiction size."""

from __future__ import annotations

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from ...table.structure_depiction_layout import (
    DEFAULT_STRUCTURE_DEPICT_HEIGHT,
    DEFAULT_STRUCTURE_DEPICT_WIDTH,
    MAX_STRUCTURE_DEPICT_HEIGHT,
    MAX_STRUCTURE_DEPICT_WIDTH,
    MIN_STRUCTURE_DEPICT_HEIGHT,
    MIN_STRUCTURE_DEPICT_WIDTH,
)
from ..qt_widget_utils import make_window_minimizable


class StructureSettingsDialog(QDialog):
    """Pick 2D structure depiction width and height (px)."""

    size_previewed = pyqtSignal(int, int)

    def __init__(self, current_width: int, current_height: int, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("2D Render")
        self.setMinimumWidth(360)

        root = QVBoxLayout(self)
        root.addWidget(
            QLabel(
                "Control the pixel size of 2D structure drawings in the table, "
                "Render 2D, browsers, and other structure images. "
                "Accepting re-draws table structures at the new size."
            )
        )
        root.addWidget(QLabel(""))

        form = QFormLayout()
        self._width_spin = self._make_spin(
            current_width,
            DEFAULT_STRUCTURE_DEPICT_WIDTH,
            MIN_STRUCTURE_DEPICT_WIDTH,
            MAX_STRUCTURE_DEPICT_WIDTH,
        )
        self._height_spin = self._make_spin(
            current_height,
            DEFAULT_STRUCTURE_DEPICT_HEIGHT,
            MIN_STRUCTURE_DEPICT_HEIGHT,
            MAX_STRUCTURE_DEPICT_HEIGHT,
        )
        self._width_spin.valueChanged.connect(self._emit_preview)
        self._height_spin.valueChanged.connect(self._emit_preview)
        form.addRow("Image width:", self._width_spin)
        form.addRow("Image height:", self._height_spin)
        root.addLayout(form)

        btn_row = QHBoxLayout()
        reset_btn = QPushButton("Reset to Default")
        reset_btn.clicked.connect(self._reset_default)
        btn_row.addWidget(reset_btn)
        btn_row.addStretch()
        root.addLayout(btn_row)

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        root.addWidget(bb)

        make_window_minimizable(self)

    @staticmethod
    def _make_spin(current: int, default: int, minimum: int, maximum: int) -> QSpinBox:
        spin = QSpinBox()
        spin.setRange(minimum, maximum)
        spin.setSuffix(" px")
        spin.setSingleStep(10)
        spin.setValue(max(minimum, min(maximum, int(current or default))))
        return spin

    def _emit_preview(self) -> None:
        self.size_previewed.emit(self.selected_width(), self.selected_height())

    def _reset_default(self) -> None:
        self._width_spin.setValue(DEFAULT_STRUCTURE_DEPICT_WIDTH)
        self._height_spin.setValue(DEFAULT_STRUCTURE_DEPICT_HEIGHT)

    def selected_width(self) -> int:
        return int(self._width_spin.value())

    def selected_height(self) -> int:
        return int(self._height_spin.value())
