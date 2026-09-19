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

"""Numeric range filter card."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLineEdit,
    QSizePolicy,
)

from .card_chrome import (
    _FC_GAP,
    _FC_SLIDER_H,
    _FILTER_CARD_MIN_HEIGHT_RANGE,
    _FilterCardDragMixin,
    _FilterCardEnableInvertMixin,
    _fc_card_layout,
    _fc_configure_column_combo,
    _fc_install_card_shell,
    _fc_mini_label,
)
from .range_slider import RangeSlider


class FilterCard(_FilterCardDragMixin, _FilterCardEnableInvertMixin, QFrame):
    changed = Signal()
    removed = Signal(object)

    def __init__(self, props, app, initial_property: str | None = None):
        super().__init__()
        self.app, self.scale = app, 100
        _fc_install_card_shell(self, _FILTER_CARD_MIN_HEIGHT_RANGE)
        l = _fc_card_layout(self)
        self._fc_add_title_row(l, "Slider")
        self.cb = QComboBox()
        _fc_configure_column_combo(self.cb)
        self.cb.addItems(props)
        if initial_property and self.cb.findText(initial_property) >= 0:
            self.cb.setCurrentText(initial_property)
        self.cb.currentTextChanged.connect(self.refresh_limits)
        self._fc_init_enable_invert("Show rows outside the min/max range.")
        self._fc_add_header_toolbar(l)
        l.addWidget(self.cb)

        bounds_lyt = QHBoxLayout()
        bounds_lyt.setSpacing(_FC_GAP)
        bounds_lyt.addWidget(_fc_mini_label("Min"))
        self.min_edit = QLineEdit()
        self.min_edit.setMinimumWidth(40)
        self.min_edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.min_edit.editingFinished.connect(self.sync_from_text)
        bounds_lyt.addWidget(self.min_edit, 1)
        bounds_lyt.addWidget(_fc_mini_label("Max"))
        self.max_edit = QLineEdit()
        self.max_edit.setMinimumWidth(40)
        self.max_edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.max_edit.editingFinished.connect(self.sync_from_text)
        bounds_lyt.addWidget(self.max_edit, 1)
        l.addLayout(bounds_lyt)

        self.range_slider = RangeSlider(self)
        self.range_slider.setFixedHeight(_FC_SLIDER_H)
        self.range_slider.rangeChanged.connect(self._sync_slider_edits)
        self.range_slider.sliderReleased.connect(self._commit_slider_filter)
        l.addWidget(self.range_slider)
        self.refresh_limits()

    def update_prop_list(self, new_props, old_n=None, new_n=None):
        self.cb.blockSignals(True)
        current = self.cb.currentText()
        self.cb.clear()
        self.cb.addItems(new_props)
        if old_n and current == old_n:
            if new_n:
                self.cb.setCurrentText(new_n)
                self.cb.blockSignals(False)
                self.refresh_limits()
                return False
            self.cb.blockSignals(False)
            return True
        self.cb.setCurrentText(current)
        self.cb.blockSignals(False)
        return False

    def refresh_limits(self):
        prop = self.cb.currentText()
        if not prop:
            return
        self.blockSignals(True)
        b_meta = self.app.global_bounds.get(prop, {"min": 0, "max": 100, "is_int": False})
        b_min, b_max = b_meta["min"], b_meta["max"]
        self.scale = 1 if b_meta["is_int"] else 100
        lo = int(b_min * self.scale)
        hi = int(b_max * self.scale)
        self.range_slider.blockSignals(True)
        self.range_slider.setRange(lo, hi)
        self.range_slider.setValues(lo, hi)
        self.range_slider.blockSignals(False)
        fmt = "{:.0f}" if b_meta["is_int"] else "{:.2f}"
        self.min_edit.setText(fmt.format(b_min))
        self.max_edit.setText(fmt.format(b_max))
        self.blockSignals(False)
        self.changed.emit()

    def _sync_slider_edits(self, *_args) -> None:
        """Update min/max text while dragging without re-filtering the table."""
        vmin = self.range_slider.lowerValue()
        vmax = self.range_slider.upperValue()
        fmt = "{:.0f}" if self.scale == 1 else "{:.2f}"
        self.min_edit.setText(fmt.format(vmin / self.scale))
        self.max_edit.setText(fmt.format(vmax / self.scale))

    def _commit_slider_filter(self) -> None:
        self._sync_slider_edits()
        self.changed.emit()

    def sync_from_slider(self, which: str | None = None):
        del which
        self._sync_slider_edits()
        self.changed.emit()

    def sync_from_text(self):
        try:
            v_min, v_max = float(self.min_edit.text()), float(self.max_edit.text())
            if v_min > v_max:
                v_min = v_max
            self.range_slider.blockSignals(True)
            self.range_slider.setValues(int(v_min * self.scale), int(v_max * self.scale))
            self.range_slider.blockSignals(False)
            self._sync_slider_edits()
            self.changed.emit()
        except Exception:
            self.sync_from_slider(None)

    def get_cfg(self):
        return {
            "column": self.cb.currentText(),
            "min": self.range_slider.lowerValue() / self.scale,
            "max": self.range_slider.upperValue() / self.scale,
            "enabled": self._filter_enabled_on,
            "inverted": self._invert_on,
        }

    def restore_state(self, prop: str, min_val: float, max_val: float) -> None:
        self.blockSignals(True)
        if self.cb.findText(prop) >= 0:
            self.cb.setCurrentText(prop)
        b_meta = self.app.global_bounds.get(prop, {"min": 0, "max": 100, "is_int": False})
        self.scale = 1 if b_meta["is_int"] else 100
        lo, hi = float(b_meta["min"]), float(b_meta["max"])
        self.range_slider.blockSignals(True)
        self.range_slider.setRange(int(lo * self.scale), int(hi * self.scale))
        lo_v = max(min(min_val, max_val), lo)
        hi_v = min(max(max_val, min_val), hi)
        self.range_slider.setValues(int(lo_v * self.scale), int(hi_v * self.scale))
        self.range_slider.blockSignals(False)
        fmt = "{:.0f}" if self.scale == 1 else "{:.2f}"
        self.min_edit.setText(fmt.format(self.range_slider.lowerValue() / self.scale))
        self.max_edit.setText(fmt.format(self.range_slider.upperValue() / self.scale))
        self.blockSignals(False)
