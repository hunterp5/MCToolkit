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

from __future__ import annotations

from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
    QColorDialog,
)


class ColumnColorDialog(QDialog):
    """Configure lightweight, column-level background coloring."""

    def __init__(
        self,
        parent=None,
        *,
        header_name: str,
        numeric_bounds: dict | None = None,
        current_mode: str = "",
        current_spec: dict | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Color Column — {header_name}")
        self.setMinimumWidth(420)

        bounds = dict(numeric_bounds or {})
        lo = float(bounds.get("min", 0.0))
        hi = float(bounds.get("max", 1.0))
        if hi < lo:
            lo, hi = hi, lo
        if hi == lo:
            hi = lo + 1.0

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(8)

        root.addWidget(QLabel(f"Column: {header_name}"))

        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("Mode:"))
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("Off", "off")
        self.mode_combo.addItem("Numeric gradient (low → high)", "numeric")
        self.mode_combo.addItem("Numeric 3-color (low → mid → high)", "numeric3")
        self.mode_combo.addItem("Categorical (distinct text values)", "categorical")
        mode_row.addWidget(self.mode_combo, 1)
        root.addLayout(mode_row)

        self.numeric_group = QGroupBox("Numeric coloring")
        nform = QFormLayout(self.numeric_group)
        self.min_spin = QDoubleSpinBox()
        self.min_spin.setRange(-1e12, 1e12)
        self.min_spin.setDecimals(6)
        self.min_spin.setValue(lo)
        self.max_spin = QDoubleSpinBox()
        self.max_spin.setRange(-1e12, 1e12)
        self.max_spin.setDecimals(6)
        self.max_spin.setValue(hi)
        nform.addRow("Minimum:", self.min_spin)
        self.mid_spin = QDoubleSpinBox()
        self.mid_spin.setRange(-1e12, 1e12)
        self.mid_spin.setDecimals(6)
        self.mid_spin.setValue((lo + hi) / 2.0)
        nform.addRow("Midpoint:", self.mid_spin)
        nform.addRow("Maximum:", self.max_spin)

        btns = QWidget()
        btn_lyt = QGridLayout(btns)
        btn_lyt.setContentsMargins(0, 0, 0, 0)
        btn_lyt.setHorizontalSpacing(8)
        btn_lyt.setVerticalSpacing(6)
        self.low_color = QColor(48, 119, 242)
        self.mid_color = QColor(245, 209, 84)
        self.high_color = QColor(236, 73, 73)
        self.low_btn = QPushButton("Low color")
        self.mid_btn = QPushButton("Mid color")
        self.high_btn = QPushButton("High color")
        self.low_btn.clicked.connect(lambda: self._pick_color("low"))
        self.mid_btn.clicked.connect(lambda: self._pick_color("mid"))
        self.high_btn.clicked.connect(lambda: self._pick_color("high"))
        btn_lyt.addWidget(self.low_btn, 0, 0)
        btn_lyt.addWidget(self.mid_btn, 0, 1)
        btn_lyt.addWidget(self.high_btn, 0, 2)
        nform.addRow(btns)

        self.numeric_alpha = QSpinBox()
        self.numeric_alpha.setRange(20, 255)
        self.numeric_alpha.setValue(96)
        nform.addRow("Opacity:", self.numeric_alpha)
        root.addWidget(self.numeric_group)

        self.cat_group = QGroupBox("Categorical")
        cform = QFormLayout(self.cat_group)
        self.categorical_alpha = QSpinBox()
        self.categorical_alpha.setRange(20, 255)
        self.categorical_alpha.setValue(88)
        cform.addRow("Opacity:", self.categorical_alpha)
        root.addWidget(self.cat_group)

        hint = QLabel(
            "Numeric mode maps values in range to a color gradient. "
            "Categorical mode assigns deterministic colors to distinct text values."
        )
        hint.setWordWrap(True)
        root.addWidget(hint)

        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        root.addWidget(box)

        spec = dict(current_spec or {})
        if "min" in spec:
            self.min_spin.setValue(float(spec.get("min", lo)))
        if "max" in spec:
            self.max_spin.setValue(float(spec.get("max", hi)))
        if "mid" in spec:
            self.mid_spin.setValue(float(spec.get("mid", (lo + hi) / 2.0)))
        if "low_rgb" in spec:
            self.low_color = QColor.fromRgb(int(spec["low_rgb"]))
        if "mid_rgb" in spec:
            self.mid_color = QColor.fromRgb(int(spec["mid_rgb"]))
        if "high_rgb" in spec:
            self.high_color = QColor.fromRgb(int(spec["high_rgb"]))
        if "alpha" in spec:
            self.numeric_alpha.setValue(int(spec["alpha"]))
            self.categorical_alpha.setValue(int(spec["alpha"]))

        start_mode = (
            "numeric3"
            if current_mode == "numeric3"
            else "numeric"
            if current_mode == "numeric"
            else "categorical"
            if current_mode == "categorical"
            else "off"
        )
        idx = self.mode_combo.findData(start_mode)
        self.mode_combo.setCurrentIndex(max(0, idx))
        self.mode_combo.currentIndexChanged.connect(self._refresh_mode_ui)
        self._refresh_mode_ui()
        self._refresh_color_buttons()

    def _refresh_mode_ui(self) -> None:
        mode = self.mode_combo.currentData() or "off"
        is_numeric = mode in {"numeric", "numeric3"}
        self.numeric_group.setEnabled(is_numeric)
        self.numeric_group.setVisible(is_numeric)
        self.mid_spin.setVisible(mode == "numeric3")
        lbl = self.numeric_group.layout().labelForField(self.mid_spin)
        if lbl is not None:
            lbl.setVisible(mode == "numeric3")
        self.mid_btn.setVisible(mode == "numeric3")
        self.cat_group.setEnabled(mode == "categorical")
        self.cat_group.setVisible(mode == "categorical")

    def _refresh_color_buttons(self) -> None:
        self.low_btn.setStyleSheet(f"background-color: {self.low_color.name()};")
        self.mid_btn.setStyleSheet(f"background-color: {self.mid_color.name()};")
        self.high_btn.setStyleSheet(f"background-color: {self.high_color.name()};")

    def _pick_color(self, which: str) -> None:
        base = (
            self.low_color
            if which == "low"
            else self.mid_color
            if which == "mid"
            else self.high_color
        )
        chosen = QColorDialog.getColor(base, self, "Choose color")
        if not chosen.isValid():
            return
        if which == "low":
            self.low_color = QColor(chosen)
        elif which == "mid":
            self.mid_color = QColor(chosen)
        else:
            self.high_color = QColor(chosen)
        self._refresh_color_buttons()

    def result_config(self) -> dict:
        mode = self.mode_combo.currentData() or "off"
        if mode == "numeric":
            lo = float(self.min_spin.value())
            hi = float(self.max_spin.value())
            if hi < lo:
                lo, hi = hi, lo
            return {
                "mode": "numeric",
                "min": lo,
                "max": hi,
                "low_color": QColor(self.low_color),
                "high_color": QColor(self.high_color),
                "alpha": int(self.numeric_alpha.value()),
            }
        if mode == "numeric3":
            lo = float(self.min_spin.value())
            mid = float(self.mid_spin.value())
            hi = float(self.max_spin.value())
            if hi < lo:
                lo, hi = hi, lo
            mid = max(lo, min(mid, hi))
            return {
                "mode": "numeric3",
                "min": lo,
                "mid": mid,
                "max": hi,
                "low_color": QColor(self.low_color),
                "mid_color": QColor(self.mid_color),
                "high_color": QColor(self.high_color),
                "alpha": int(self.numeric_alpha.value()),
            }
        if mode == "categorical":
            return {"mode": "categorical", "alpha": int(self.categorical_alpha.value())}
        return {"mode": "off"}
