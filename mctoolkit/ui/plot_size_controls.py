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

"""Shared min/max marker size controls for Plotly scatter tools."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDoubleSpinBox, QHBoxLayout, QLabel, QSizePolicy, QWidget

from ..plotting.plot_marker_color import (
    DEFAULT_MARKER_SIZE_MAX_PX,
    DEFAULT_MARKER_SIZE_MIN_PX,
    clamp_marker_size_bounds,
)

# Match Color by Min/Max footprint so labels and spins never overlap.
_SIZE_RANGE_CONTROLS_WIDTH = 220


class PlotSizeRangeControls(QWidget):
    """Min/max pixel sizes for Size by (inline on the size options row)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.setFixedWidth(_SIZE_RANGE_CONTROLS_WIDTH)

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)

        self._min_label = QLabel("Min:")
        self._min_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        row.addWidget(self._min_label)
        self.size_min = QDoubleSpinBox()
        self.size_min.setDecimals(1)
        self.size_min.setRange(1.0, 64.0)
        self.size_min.setSingleStep(1.0)
        self.size_min.setValue(DEFAULT_MARKER_SIZE_MIN_PX)
        self.size_min.setFixedWidth(72)
        self.size_min.setToolTip("Smallest marker size in pixels (maps to the low end of Size by).")
        row.addWidget(self.size_min)

        self._max_label = QLabel("Max:")
        self._max_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        row.addWidget(self._max_label)
        self.size_max = QDoubleSpinBox()
        self.size_max.setDecimals(1)
        self.size_max.setRange(1.0, 64.0)
        self.size_max.setSingleStep(1.0)
        self.size_max.setValue(DEFAULT_MARKER_SIZE_MAX_PX)
        self.size_max.setFixedWidth(72)
        self.size_max.setToolTip("Largest marker size in pixels (maps to the high end of Size by).")
        row.addWidget(self.size_max)

        self.set_enabled(False)

    def connect_changed(self, callback) -> None:
        """Call ``callback`` when the user edits min or max size."""
        self.size_min.valueChanged.connect(callback)
        self.size_max.valueChanged.connect(callback)

    def parse_bounds(self) -> tuple[float, float]:
        return clamp_marker_size_bounds(
            float(self.size_min.value()),
            float(self.size_max.value()),
        )

    def set_enabled(self, enabled: bool) -> None:
        for widget in (
            self._min_label,
            self.size_min,
            self._max_label,
            self.size_max,
        ):
            widget.setEnabled(enabled)
