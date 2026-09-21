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
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with MCToolkit. If not, see <https://www.gnu.org/licenses/>.

"""Axis / plot-type control helpers for :class:`PlotWidget`."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSizePolicy,
    QWidget,
)

from ..plotting.plot_axes import (
    AXIS_NONE,
    PLOT_TYPE_BOX,
    PLOT_TYPE_HEATMAP,
    PLOT_TYPE_HISTOGRAM,
    PLOT_TYPE_LINE_2D,
    PLOT_TYPE_RADAR,
    PLOT_TYPE_SCATTER,
    PLOT_TYPE_VIOLIN,
    infer_plot_mode,
    normalize_axis_name,
    resolve_plot_mode,
)
from ..plotting.plot_series_collect import plotly_axis_range


class PlotAxisMixin:
    """Axis combos, range edits, and plot-type visibility wiring."""

    @staticmethod
    def _build_axis_row(
        axis_label: str,
        combo: QComboBox,
        edit_min: QLineEdit,
        edit_max: QLineEdit,
        *,
        extra_after_range: tuple[QWidget, QWidget] | None = None,
    ) -> QWidget:
        """One axis row: column combo with min/max range edits on the same line."""
        row = QWidget()
        lay = QHBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        axis_lbl = QLabel(f"{axis_label}:")
        axis_lbl.setMinimumWidth(14)
        lay.addWidget(axis_lbl)
        combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        lay.addWidget(combo, 1)
        lay.addWidget(QLabel("Min:"))
        lay.addWidget(edit_min)
        lay.addWidget(QLabel("Max:"))
        lay.addWidget(edit_max)
        if extra_after_range is not None:
            extra_label, extra_widget = extra_after_range
            lay.addWidget(extra_label)
            lay.addWidget(extra_widget)
        lay.addStretch(0)
        return row

    def _set_axis_range_edits(
        self, axis_name: str, edit_min: QLineEdit, edit_max: QLineEdit
    ) -> None:
        meta = self.parent_app.global_bounds.get(axis_name)
        if not meta:
            edit_min.setText("")
            edit_max.setText("")
            return
        scale_int = bool(meta.get("is_int"))
        fmt = "{:.0f}" if scale_int else "{:.2f}"
        edit_min.setText(fmt.format(float(meta["min"])))
        edit_max.setText(fmt.format(float(meta["max"])))

    @staticmethod
    def _parse_edit_float(edit: QLineEdit) -> float | None:
        try:
            return float(edit.text()) if edit.text().strip() else None
        except Exception:
            return None

    @staticmethod
    def _plotly_axis_range(vmin: float | None, vmax: float | None, data_vals: list[float]) -> dict:
        """Build Plotly axis settings from user limits (may extend beyond plotted points)."""
        return plotly_axis_range(vmin, vmax, data_vals)

    def _numeric_column_names(self) -> list[str]:
        cols = (
            list(self.parent_app.global_bounds.keys())
            if getattr(self.parent_app, "global_bounds", None)
            else []
        )
        if not cols and self.parent_app is not None:
            cols = [h for h in self.parent_app.headers[2:]]
        return cols

    @staticmethod
    def _populate_optional_axis_combo(combo: QComboBox, cols: list[str], default: str) -> None:
        PlotAxisMixin._set_axis_combo_items(combo, cols, previous=default, allow_none=True)

    @staticmethod
    def _set_axis_combo_items(
        combo: QComboBox,
        cols: list[str],
        *,
        previous: str,
        allow_none: bool,
    ) -> None:
        combo.blockSignals(True)
        combo.clear()
        if allow_none:
            combo.addItem(AXIS_NONE)
        combo.addItems(cols)
        if previous and combo.findText(previous) >= 0:
            combo.setCurrentText(previous)
        elif allow_none and (
            not previous or previous == AXIS_NONE or normalize_axis_name(previous) is None
        ):
            combo.setCurrentIndex(0)
        elif cols:
            combo.setCurrentIndex(0 if not allow_none else 1)
        combo.blockSignals(False)

    def _combo_axis_name(self, combo: QComboBox) -> str | None:
        return normalize_axis_name(combo.currentText())

    def _current_plot_type(self) -> str:
        key = self.plot_type_combo.currentData()
        return key if isinstance(key, str) else PLOT_TYPE_SCATTER

    def _effective_plot_mode(self) -> str | None:
        return resolve_plot_mode(
            self._current_plot_type(),
            self.x_combo.currentText(),
            self.y_combo.currentText(),
            self.z_combo.currentText(),
        )

    def _infer_plot_mode(self) -> str | None:
        return infer_plot_mode(
            self.x_combo.currentText(),
            self.y_combo.currentText(),
            self.z_combo.currentText(),
        )

    def _is_single_column_plot(self) -> bool:
        ptype = self._current_plot_type()
        return ptype in (PLOT_TYPE_BOX, PLOT_TYPE_VIOLIN, PLOT_TYPE_HISTOGRAM)

    def _is_heatmap_plot(self) -> bool:
        return self._current_plot_type() == PLOT_TYPE_HEATMAP

    def _shows_x_bin_width(self) -> bool:
        ptype = self._current_plot_type()
        return ptype in (PLOT_TYPE_HISTOGRAM, PLOT_TYPE_HEATMAP)

    def _shows_y_bin_width(self) -> bool:
        return self._is_heatmap_plot()

    def _maybe_default_axis_range_edits(
        self, axis_key: str, axis_name: str, edit_min: QLineEdit, edit_max: QLineEdit
    ) -> None:
        """Fill min/max from column bounds only when that axis column changes."""
        if self._prev_range_axis.get(axis_key) == axis_name:
            return
        self._prev_range_axis[axis_key] = axis_name
        self._set_axis_range_edits(axis_name, edit_min, edit_max)

    def _ensure_scatter_y_axis(self) -> None:
        """If Scatter is active and Y is unset, pick a column distinct from X when possible."""
        if self._current_plot_type() != PLOT_TYPE_SCATTER:
            return
        if self._combo_axis_name(self.y_combo) is not None:
            return
        cols = self._numeric_column_names()
        if not cols:
            return
        xname = self._combo_axis_name(self.x_combo)
        pick = next((c for c in cols if c != xname), cols[0])
        idx = self.y_combo.findText(pick)
        if idx >= 0:
            self.y_combo.blockSignals(True)
            try:
                self.y_combo.setCurrentIndex(idx)
            finally:
                self.y_combo.blockSignals(False)

    def _on_plot_type_change(self, _idx: int = 0) -> None:
        self._ensure_scatter_y_axis()
        self._on_axis_change()

    def _set_z_title_visible(self, visible: bool) -> None:
        lbl = getattr(self, "_z_title_label", None)
        edit = getattr(self, "zaxis_title_edit", None)
        if lbl is not None:
            lbl.setVisible(visible)
        if edit is not None:
            edit.setVisible(visible)

    def _on_axis_change(self):
        ptype = self._current_plot_type()
        radar = ptype == PLOT_TYPE_RADAR
        self._axes_group.setVisible(not radar)
        self._radar_host.setVisible(radar)
        if radar:
            self._set_z_title_visible(False)
            self._update_color_controls()
            self._schedule_plot()
            return
        if ptype == PLOT_TYPE_SCATTER:
            self._ensure_scatter_y_axis()
            self._x_axis_row.setVisible(True)
            self._y_axis_row.setVisible(True)
            self._z_axis_row.setVisible(True)
            self._set_z_title_visible(True)
            self.hist_bin_width_label.setVisible(False)
            self.hist_bin_width.setVisible(False)
            self.heatmap_y_bin_width_label.setVisible(False)
            self.heatmap_y_bin_width.setVisible(False)
        elif ptype == PLOT_TYPE_HISTOGRAM:
            self._x_axis_row.setVisible(True)
            self._y_axis_row.setVisible(False)
            self._z_axis_row.setVisible(False)
            self._set_z_title_visible(False)
            self.hist_bin_width_label.setText("Bin width:")
            self.hist_bin_width_label.setVisible(True)
            self.hist_bin_width.setVisible(True)
            self.heatmap_y_bin_width_label.setVisible(False)
            self.heatmap_y_bin_width.setVisible(False)
        elif ptype == PLOT_TYPE_HEATMAP:
            self._x_axis_row.setVisible(True)
            self._y_axis_row.setVisible(True)
            self._z_axis_row.setVisible(False)
            self._set_z_title_visible(False)
            self.hist_bin_width_label.setText("X bin width:")
            self.hist_bin_width_label.setVisible(True)
            self.hist_bin_width.setVisible(True)
            self.heatmap_y_bin_width_label.setVisible(True)
            self.heatmap_y_bin_width.setVisible(True)
        else:
            if ptype == PLOT_TYPE_LINE_2D:
                mode = "2D"
            elif ptype in (PLOT_TYPE_BOX, PLOT_TYPE_VIOLIN):
                mode = "Histogram"
            else:
                mode = self._infer_plot_mode()
            is3d = mode == "3D"
            single_col = self._is_single_column_plot()
            self._y_axis_row.setVisible(not single_col)
            self._z_axis_row.setVisible(is3d)
            self._set_z_title_visible(is3d)
            show_x_bw = self._shows_x_bin_width()
            self.hist_bin_width_label.setText("Bin width:")
            self.hist_bin_width_label.setVisible(show_x_bw)
            self.hist_bin_width.setVisible(show_x_bw)
            self.heatmap_y_bin_width_label.setVisible(False)
            self.heatmap_y_bin_width.setVisible(False)

        xname = self.x_combo.currentText()
        self._maybe_default_axis_range_edits("x", xname, self.xmin, self.xmax)
        yname = self._combo_axis_name(self.y_combo)
        if yname:
            self._maybe_default_axis_range_edits("y", yname, self.ymin, self.ymax)
        zname = self._combo_axis_name(self.z_combo)
        if zname:
            self._maybe_default_axis_range_edits("z", zname, self.zmin, self.zmax)
        self._update_color_controls()
        self._schedule_plot()
