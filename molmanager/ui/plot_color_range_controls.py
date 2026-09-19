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

"""Shared min/max color range controls for Plotly scatter tools."""

from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QSizePolicy, QWidget

from ..plotting.plot_marker_color import parse_color_range_bounds

# Min:/Max: labels + two 72px edits + spacing; keep Fixed so parent layouts cannot crush them.
_COLOR_RANGE_CONTROLS_WIDTH = 220


class PlotColorRangeControls(QWidget):
    """Min/max edits for numeric Color by columns (inline on the color options row)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.setFixedWidth(_COLOR_RANGE_CONTROLS_WIDTH)

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)

        self._min_label = QLabel("Min:")
        self._min_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        row.addWidget(self._min_label)
        self.color_min = QLineEdit()
        self.color_min.setPlaceholderText("auto")
        self.color_min.setFixedWidth(72)
        self.color_min.setToolTip(
            "Minimum value mapped to the low end of the spectrum (empty = data min)."
        )
        row.addWidget(self.color_min)

        self._max_label = QLabel("Max:")
        self._max_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        row.addWidget(self._max_label)
        self.color_max = QLineEdit()
        self.color_max.setPlaceholderText("auto")
        self.color_max.setFixedWidth(72)
        self.color_max.setToolTip(
            "Maximum value mapped to the high end of the spectrum (empty = data max)."
        )
        row.addWidget(self.color_max)

        self.set_enabled(False)

    def connect_changed(self, callback) -> None:
        """Call ``callback`` when the user edits min or max."""
        self.color_min.editingFinished.connect(callback)
        self.color_max.editingFinished.connect(callback)

    def parse_bounds(self) -> tuple[float | None, float | None]:
        return parse_color_range_bounds(self.color_min.text(), self.color_max.text())

    def set_enabled(self, enabled: bool) -> None:
        for widget in (
            self._min_label,
            self.color_min,
            self._max_label,
            self.color_max,
        ):
            widget.setEnabled(enabled)
