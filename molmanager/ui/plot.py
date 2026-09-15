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

"""Plot dialog: Plotly scatter linked to the main table."""

from __future__ import annotations

__all__ = [
    "AXIS_NONE",
    "PLOT_TYPE_SCATTER",
    "PLOT_TYPE_HISTOGRAM",
    "PLOT_TYPE_CHOICES",
    "PLOT_SESSION_KIND",
    "PlotDialog",
    "PlotWidget",
    "compute_histogram_bin_edges",
    "infer_plot_mode",
    "normalize_axis_name",
    "oids_in_histogram_bin",
    "resolve_plot_mode",
]

AXIS_NONE = "None"

PLOT_TYPE_SCATTER = "scatter"
PLOT_TYPE_HISTOGRAM = "histogram"
PLOT_TYPE_LINE_2D = "line_2d"
PLOT_TYPE_BOX = "box"
PLOT_TYPE_VIOLIN = "violin"
PLOT_TYPE_HEATMAP = "heatmap"
PLOT_TYPE_RADAR = "radar"

PLOT_TYPE_CHOICES: tuple[tuple[str, str], ...] = (
    ("Scatter", PLOT_TYPE_SCATTER),
    ("Histogram", PLOT_TYPE_HISTOGRAM),
    ("2D Line", PLOT_TYPE_LINE_2D),
    ("Heatmap", PLOT_TYPE_HEATMAP),
    ("Box plot", PLOT_TYPE_BOX),
    ("Violin", PLOT_TYPE_VIOLIN),
    ("Radar", PLOT_TYPE_RADAR),
)

PLOT_SESSION_KIND = "plotter"

import json
import math
import tempfile
import time
import webbrowser
from pathlib import Path

from PyQt5.QtCore import QEvent, QObject, Qt, QTimer, QUrl, pyqtSlot
from PyQt5.QtGui import QKeySequence
from PyQt5.QtWebChannel import QWebChannel
from PyQt5.QtWebEngineWidgets import QWebEngineView
from PyQt5.QtWidgets import (
    QAbstractSpinBox,
    QCheckBox,
    QComboBox,
    QDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QShortcut,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from plotly import graph_objects as go

from .dockable_plot import (
    apply_plot_chrome_glyphs,
    handle_floating_plot_close_event,
    make_add_to_main_button,
    make_clear_selection_button,
    make_close_plot_button,
    make_plot_options_button,
    make_plot_options_dialog,
    make_send_window_button,
    request_close_plot_widget,
    show_plot_options_dialog,
)
from ..plot_analysis import (
    FIT_NONE,
    FIT_TRUNCATED_GAUSSIAN,
    HISTOGRAM_ONLY_FITS,
    PLOT_FIT_CHOICES,
    PLOT_FIT_CHOICES_XY,
    fit_histogram_curve,
    fit_xy_curve,
    summarize_univariate,
    summarize_xy,
)
from ..plot_color import (
    PLOT_COLORSCALE_CHOICES,
    attach_marker_size_legend,
    color_values_are_numeric,
    normalize_color_column,
    normalize_size_column,
    resolve_plot_colorscale,
    scatter_marker_from_column_values,
)
from ..medchem_space import snapshot_scope_row_indices
from ..plot_heatmap import build_heatmap_figure, oids_in_heatmap_cell, summarize_heatmap
from ..plot_labels import add_fit_formula_annotation, apply_plotly_label_overrides
from ..plot_radar import (
    MAX_RADAR_DISPLAY_ENTRIES,
    MAX_RADAR_TRACES,
    MAX_RADAR_VARIABLES,
    MIN_RADAR_VARIABLES,
    SPOKE_NONE,
    build_radar_figure,
    collect_radar_rows,
    compute_radar_normalization_bounds,
    filter_radar_rows_by_oids,
    resolve_entry_row_oid,
    summarize_radar,
)
from .plot_color_range_controls import PlotColorRangeControls
from .plot_on_hover_controls import PlotOnHoverControls
from .plot_size_controls import PlotSizeRangeControls
from .plot_hover import hover_cards_payload
from .plot_table_sync import (
    apply_table_selection_for_source_rows,
    build_oid_point_index,
    clear_table_selection_from_plot,
    point_indices_for_oids,
    run_javascript_apply_figure,
    run_javascript_set_selection,
    selected_oids_for_plot,
    selection_visual_push_key,
    source_rows_for_point_indices,
)
from ..utils import safe_float
from .qt_widget_utils import apply_monospace_to_text_edit, make_window_minimizable


def normalize_axis_name(text: str | None) -> str | None:
    """Return a column name, or None when the combo is unset or ``AXIS_NONE``."""
    if not text:
        return None
    name = text.strip()
    if not name or name == AXIS_NONE:
        return None
    return name


def infer_plot_mode(x: str | None, y: str | None, z: str | None) -> str | None:
    """Infer scatter dimensionality from axis combo text: 2D, 3D, or None if invalid."""
    xn = normalize_axis_name(x)
    yn = normalize_axis_name(y)
    zn = normalize_axis_name(z)
    if not xn or yn is None:
        return None
    if zn is None:
        return "2D"
    return "3D"


def resolve_plot_mode(
    plot_type: str,
    x: str | None,
    y: str | None,
    z: str | None,
) -> str | None:
    """Resolve plot mode from plot type and axis selections."""
    xn = normalize_axis_name(x)
    yn = normalize_axis_name(y)
    if plot_type == PLOT_TYPE_HISTOGRAM:
        return "Histogram" if xn else None
    if plot_type == PLOT_TYPE_SCATTER:
        return infer_plot_mode(x, y, z)
    if plot_type == PLOT_TYPE_LINE_2D:
        return "2D" if xn and yn else None
    if plot_type == PLOT_TYPE_HEATMAP:
        return "Heatmap" if xn and yn else None
    return None


def compute_histogram_bin_edges(
    vals: list[float],
    *,
    bin_width: float | None = None,
    xmin: float | None = None,
    xmax: float | None = None,
) -> tuple[list[float], float]:
    """Return histogram bin edges (length n+1) and the bin width used."""
    if not vals:
        return [0.0, 1.0], 1.0
    lo = float(xmin) if xmin is not None else min(vals)
    hi = float(xmax) if xmax is not None else max(vals)
    if lo > hi:
        lo, hi = hi, lo
    if math.isclose(lo, hi, rel_tol=0.0, abs_tol=1e-12):
        hi = lo + 1.0
    if bin_width is not None and bin_width > 0:
        width = float(bin_width)
        start = math.floor(lo / width) * width
        end = math.ceil(hi / width) * width
        edges = []
        x = start
        guard = 0
        while x <= end + abs(end) * 1e-9 and guard < 10_000:
            edges.append(x)
            x += width
            guard += 1
        if len(edges) < 2:
            edges = [lo, lo + width]
        return edges, width
    n = len(vals)
    n_bins = max(1, int(math.ceil(math.log2(n) + 1))) if n else 1
    width = (hi - lo) / n_bins
    edges = [lo + i * width for i in range(n_bins + 1)]
    edges[-1] = hi
    return edges, width


def oids_at_histogram_point_indices(oids: list[int], indices: list[int]) -> list[int]:
    """Map Plotly histogram ``pointNumbers`` indices to row OIDs (deduped, order preserved)."""
    n = len(oids)
    seen: set[int] = set()
    selected: list[int] = []
    for raw in indices:
        try:
            i = int(raw)
        except (TypeError, ValueError):
            continue
        if not (0 <= i < n):
            continue
        oid = int(oids[i])
        if oid in seen:
            continue
        seen.add(oid)
        selected.append(oid)
    return selected


def oids_in_histogram_bin(
    vals: list[float],
    oids: list[int],
    edges: list[float],
    bin_index: int,
) -> list[int]:
    """OIDs whose values fall in histogram bin ``bin_index`` (half-open, last bin inclusive)."""
    if bin_index < 0 or bin_index + 1 >= len(edges):
        return []
    lo, hi = float(edges[bin_index]), float(edges[bin_index + 1])
    last_bin = bin_index == len(edges) - 2
    selected: list[int] = []
    for v, oid in zip(vals, oids):
        vf = float(v)
        if last_bin:
            if lo <= vf <= hi:
                selected.append(int(oid))
        elif lo <= vf < hi:
            selected.append(int(oid))
    return selected


class _PlotBridge(QObject):
    """Bridge JS Plotly events back to Qt."""

    def __init__(self, plot_widget: "PlotWidget") -> None:
        super().__init__(plot_widget)
        self._plot_widget = plot_widget

    @pyqtSlot(int, bool)
    def pointClicked(self, point_index: int, additive: bool = False) -> None:  # noqa: N802
        self._plot_widget._on_plot_point_clicked(int(point_index), additive=bool(additive))

    @pyqtSlot(str, bool)
    def pointsSelected(self, points_json: str, additive: bool = False) -> None:  # noqa: N802
        self._plot_widget._on_plot_points_selected(points_json, additive=bool(additive))

    @pyqtSlot(str, bool)
    def histogramPointsSelected(self, indices_json: str, additive: bool = False) -> None:  # noqa: N802
        self._plot_widget._on_histogram_points_selected(indices_json, additive=bool(additive))

    @pyqtSlot(int)
    def histogramBinClicked(self, bin_index: int) -> None:  # noqa: N802
        self._plot_widget._on_histogram_bin_clicked(int(bin_index))

    @pyqtSlot(float, float)
    def heatmapCellClicked(self, x_value: float, y_value: float) -> None:  # noqa: N802
        self._plot_widget._on_heatmap_cell_clicked(float(x_value), float(y_value))

    @pyqtSlot(int)
    def radarTraceClicked(self, trace_index: int) -> None:  # noqa: N802
        self._plot_widget._on_radar_trace_clicked(int(trace_index))

    @pyqtSlot(int, result=str)
    def hoverCardJson(self, point_index: int) -> str:  # noqa: N802
        return self._plot_widget._hover_card_json_for_point(int(point_index))

    @pyqtSlot(str, result=str)
    def hoverCardsJson(self, indices_json: str) -> str:  # noqa: N802
        return self._plot_widget._hover_card_json_for_points(indices_json)


class PlotStatisticsPanel(QWidget):
    """Embedded statistics and curve-fit summary beside the plot options."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumWidth(240)
        root = QVBoxLayout(self)
        root.setContentsMargins(4, 0, 0, 0)
        root.setSpacing(4)
        title = QLabel("Statistics")
        title.setStyleSheet("font-weight: bold;")
        root.addWidget(title)
        self.summary_text = QTextEdit()
        self.summary_text.setReadOnly(True)
        self.summary_text.setMinimumHeight(120)
        apply_monospace_to_text_edit(self.summary_text)
        root.addWidget(self.summary_text, 1)
        self.set_lines(["Plot data to see summary statistics."])

    def set_lines(self, lines: list[str]) -> None:
        self.summary_text.setPlainText("\n".join(lines) if lines else "")


class PlotWidget(QWidget):
    """Interactive Plotly plotter for numeric table columns (dialog or main-window panel)."""

    # Color-by + Spectrum + Min/Max need ~640px; Statistics sits beside axes.
    _AXES_CONTROLS_MIN_WIDTH = 640
    _STATS_PANEL_MIN_WIDTH = 240
    owns_docked_plot_actions = True

    def __init__(self, parent_app=None):
        super().__init__(None)
        self.parent_app = parent_app

        self._plot_shell_path = (
            Path(tempfile.gettempdir()) / f"MOLMANAGER_plot_shell_{id(self)}.html"
        )
        self._last_browser_opened_path: str | None = None
        self._plotted_oids: list[int] = []
        self._oid_point_index: dict[int, list[int]] = {}
        self._selected_point_indices: set[int] = set()
        self._last_pushed_selection_key: tuple[int, int] | None = None
        self._web_ready = False
        self._pending_table_selection_sync = False
        self._pending_payload_json: str | None = None
        self._prev_range_axis: dict[str, str] = {"x": "", "y": "", "z": ""}
        self._ignore_plot_clear_until: float = 0.0
        self._hist_edges: list[float] = []
        self._hist_vals: list[float] = []
        self._hist_oids: list[int] = []
        self._heat_x: list[float] = []
        self._heat_y: list[float] = []
        self._heat_oids: list[int] = []
        self._heat_x_edges: list[float] = []
        self._heat_y_edges: list[float] = []
        self._radar_oids: list[int] = []

        root = QVBoxLayout(self)
        # Top inset matches root spacing so floating (chrome→plot) and docked
        # (pane header→plot) share the same gap under the toolbar.
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(4)

        self._opts_panel = QWidget()
        opts_root = QVBoxLayout(self._opts_panel)
        opts_root.setContentsMargins(0, 0, 0, 0)
        opts_root.setSpacing(6)

        self._type_row_host = QWidget()
        type_row = QHBoxLayout(self._type_row_host)
        type_row.setContentsMargins(0, 0, 0, 0)
        type_row.setSpacing(6)
        type_row.addWidget(QLabel("Plot type:"))
        self.plot_type_combo = QComboBox()
        for label, key in PLOT_TYPE_CHOICES:
            self.plot_type_combo.addItem(label, key)
        self.plot_type_combo.setToolTip(
            "Scatter: 2D or 3D from X/Y/Z. Histogram: single-column distribution. "
            "Radar: compare 2–6 numeric spokes. Other types use a fixed chart style."
        )
        type_row.addWidget(self.plot_type_combo, 1)
        opts_root.addWidget(self._type_row_host)

        self.web = QWebEngineView(self)
        self.web.setMinimumHeight(420)
        self.web.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        ctrl_wrap = QWidget(self)
        ctrl_root = QVBoxLayout(ctrl_wrap)
        ctrl_root.setContentsMargins(0, 0, 0, 0)
        ctrl_root.setSpacing(4)

        range_edit_w = 76
        self.x_combo = QComboBox()
        self.y_combo = QComboBox()
        self.z_combo = QComboBox()
        self.xmin = QLineEdit()
        self.xmin.setFixedWidth(range_edit_w)
        self.xmax = QLineEdit()
        self.xmax.setFixedWidth(range_edit_w)
        self.ymin = QLineEdit()
        self.ymin.setFixedWidth(range_edit_w)
        self.ymax = QLineEdit()
        self.ymax.setFixedWidth(range_edit_w)
        self.zmin = QLineEdit()
        self.zmin.setFixedWidth(range_edit_w)
        self.zmax = QLineEdit()
        self.zmax.setFixedWidth(range_edit_w)
        self.hist_bin_width = QLineEdit()
        self.hist_bin_width.setFixedWidth(range_edit_w)
        self.hist_bin_width.setToolTip(
            "X-axis bin width for histogram or heatmap (empty = automatic)."
        )
        self.hist_bin_width.editingFinished.connect(self._schedule_plot)
        self.heatmap_y_bin_width_label = QLabel("Y bin width:")
        self.heatmap_y_bin_width = QLineEdit()
        self.heatmap_y_bin_width.setFixedWidth(range_edit_w)
        self.heatmap_y_bin_width.setToolTip("Y-axis bin width for heatmap (empty = automatic).")
        self.heatmap_y_bin_width.editingFinished.connect(self._schedule_plot)

        gb_axes = QGroupBox("Axes")
        axes_l = QVBoxLayout(gb_axes)
        axes_l.setSpacing(4)

        self.hist_bin_width_label = QLabel("Bin width:")
        self._x_axis_row = self._build_axis_row(
            "X",
            self.x_combo,
            self.xmin,
            self.xmax,
            extra_after_range=(self.hist_bin_width_label, self.hist_bin_width),
        )
        self._y_axis_row = self._build_axis_row(
            "Y",
            self.y_combo,
            self.ymin,
            self.ymax,
            extra_after_range=(self.heatmap_y_bin_width_label, self.heatmap_y_bin_width),
        )
        self._z_axis_row = self._build_axis_row("Z", self.z_combo, self.zmin, self.zmax)
        axes_l.addWidget(self._x_axis_row)
        axes_l.addWidget(self._y_axis_row)
        axes_l.addWidget(self._z_axis_row)

        cols = self._numeric_column_names()
        self.x_combo.addItems(cols)
        # Scatter needs X+Y; default Y to the second numeric column when available.
        y_default = cols[1] if len(cols) > 1 else AXIS_NONE
        self._set_axis_combo_items(self.y_combo, cols, previous=y_default, allow_none=True)
        self._populate_optional_axis_combo(self.z_combo, cols, AXIS_NONE)

        n_sel = len(parent_app._selected_logical_rows()) if parent_app is not None else 0
        self._plot_scope_has_selection = n_sel > 0
        self.only_selected_cb = QCheckBox("Selected Rows Only")
        self._only_selected_scope_prefix = "Selected Rows Only"
        if self._plot_scope_has_selection:
            self.only_selected_cb.setText(f"{self._only_selected_scope_prefix} ({n_sel} row(s))")
        else:
            self.only_selected_cb.setEnabled(False)

        self.only_selected_cb.stateChanged.connect(self._schedule_plot)
        gb_options = QGroupBox("Options")
        options_l = QVBoxLayout(gb_options)
        options_l.setSpacing(4)
        options_l.addWidget(self.only_selected_cb)
        ctrl_root.addWidget(gb_options)

        self._hover_controls = PlotOnHoverControls()
        self.hover_structure_cb = self._hover_controls.hover_structure_cb
        self.hover_persist_cb = self._hover_controls.hover_persist_cb
        self._hover_combos = self._hover_controls._hover_combos
        self._hover_controls.changed.connect(self._schedule_plot)
        self._hover_controls.persist_changed.connect(self._on_hover_persist_changed)
        ctrl_root.addWidget(self._hover_controls)

        color_row = QHBoxLayout()
        color_row.setSpacing(6)
        self._color_by_label = QLabel("Color by:")
        color_row.addWidget(self._color_by_label)
        self.color_combo = QComboBox()
        self.color_combo.setMinimumWidth(100)
        self.color_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.color_combo.setToolTip(
            "Color scatter and line points by a table column (numeric or categorical)."
        )
        self.color_combo.currentIndexChanged.connect(self._on_color_column_changed)
        color_row.addWidget(self.color_combo, 1)
        self._spectrum_label = QLabel("Spectrum:")
        color_row.addWidget(self._spectrum_label)
        self.colorscale_combo = QComboBox()
        self.colorscale_combo.setMinimumWidth(90)
        self.colorscale_combo.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.colorscale_combo.addItems(PLOT_COLORSCALE_CHOICES)
        self.colorscale_combo.setToolTip("Continuous colorscale for numeric Color by columns.")
        self.colorscale_combo.currentIndexChanged.connect(self._schedule_plot)
        color_row.addWidget(self.colorscale_combo)
        self.color_range = PlotColorRangeControls()
        self.color_range.connect_changed(self._schedule_plot)
        color_row.addWidget(self.color_range, 0)
        axes_l.addLayout(color_row)

        size_row = QHBoxLayout()
        size_row.setSpacing(6)
        self._size_by_label = QLabel("Size by:")
        size_row.addWidget(self._size_by_label)
        self.size_combo = QComboBox()
        self.size_combo.setMinimumWidth(100)
        self.size_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.size_combo.setToolTip(
            "Size scatter and line points by a table column (numeric or categorical)."
        )
        self.size_combo.currentIndexChanged.connect(self._on_size_column_changed)
        size_row.addWidget(self.size_combo, 1)
        self.size_range = PlotSizeRangeControls()
        self.size_range.connect_changed(self._schedule_plot)
        size_row.addWidget(self.size_range, 0)
        axes_l.addLayout(size_row)

        analysis_row = QHBoxLayout()
        analysis_row.setSpacing(6)
        self._fit_label = QLabel("Fit:")
        analysis_row.addWidget(self._fit_label)
        self.fit_combo = QComboBox()
        self.fit_combo.setMinimumWidth(120)
        self.fit_combo.setToolTip(
            "Overlay a fit on 2D/line plots, or on histograms (Gaussian, log-normal, truncated Gaussian, or bin trends)."
        )
        self._refresh_fit_combo_items()
        self.fit_combo.currentIndexChanged.connect(self._on_fit_option_changed)
        analysis_row.addWidget(self.fit_combo)
        self.show_fit_formula_cb = QCheckBox("Show formula on plot")
        self.show_fit_formula_cb.setChecked(False)
        self.show_fit_formula_cb.setToolTip(
            "Draw the fit equation on the graph (also shown in the statistics panel)."
        )
        self.show_fit_formula_cb.stateChanged.connect(self._schedule_plot)
        analysis_row.addWidget(self.show_fit_formula_cb)
        trunc_bound_w = 64
        self._trunc_lower_label = QLabel("Trunc lower:")
        self._trunc_lower_label.setToolTip("Lower truncation bound (empty = no lower bound).")
        analysis_row.addWidget(self._trunc_lower_label)
        self.fit_trunc_lower = QLineEdit()
        self.fit_trunc_lower.setFixedWidth(trunc_bound_w)
        self.fit_trunc_lower.setPlaceholderText("—")
        self.fit_trunc_lower.setToolTip(self._trunc_lower_label.toolTip())
        self.fit_trunc_lower.editingFinished.connect(self._schedule_plot)
        analysis_row.addWidget(self.fit_trunc_lower)
        self._trunc_upper_label = QLabel("Trunc upper:")
        self._trunc_upper_label.setToolTip("Upper truncation bound (empty = no upper bound).")
        analysis_row.addWidget(self._trunc_upper_label)
        self.fit_trunc_upper = QLineEdit()
        self.fit_trunc_upper.setFixedWidth(trunc_bound_w)
        self.fit_trunc_upper.setPlaceholderText("—")
        self.fit_trunc_upper.setToolTip(self._trunc_upper_label.toolTip())
        self.fit_trunc_upper.editingFinished.connect(self._schedule_plot)
        analysis_row.addWidget(self.fit_trunc_upper)
        analysis_row.addStretch()
        axes_l.addLayout(analysis_row)

        self._axes_group = gb_axes
        ctrl_root.addWidget(gb_axes)

        gb_labels = QGroupBox("Titles")
        labels_l = QVBoxLayout(gb_labels)
        labels_l.setSpacing(4)
        title_row = QHBoxLayout()
        title_row.setSpacing(6)
        title_row.addWidget(QLabel("Plot title:"))
        self.plot_title_edit = QLineEdit()
        self.plot_title_edit.setPlaceholderText("Optional (empty = no title)")
        self.plot_title_edit.setToolTip("Overall figure title. Leave blank for no title.")
        self.plot_title_edit.editingFinished.connect(self._schedule_plot)
        title_row.addWidget(self.plot_title_edit, 1)
        labels_l.addLayout(title_row)
        axis_title_row = QHBoxLayout()
        axis_title_row.setSpacing(6)
        axis_title_row.addWidget(QLabel("X title:"))
        self.xaxis_title_edit = QLineEdit()
        self.xaxis_title_edit.setPlaceholderText("Auto (column name)")
        self.xaxis_title_edit.setToolTip("Override the X-axis title. Empty keeps the column name.")
        self.xaxis_title_edit.editingFinished.connect(self._schedule_plot)
        axis_title_row.addWidget(self.xaxis_title_edit, 1)
        axis_title_row.addWidget(QLabel("Y title:"))
        self.yaxis_title_edit = QLineEdit()
        self.yaxis_title_edit.setPlaceholderText("Auto (column name)")
        self.yaxis_title_edit.setToolTip("Override the Y-axis title. Empty keeps the column name.")
        self.yaxis_title_edit.editingFinished.connect(self._schedule_plot)
        axis_title_row.addWidget(self.yaxis_title_edit, 1)
        self._z_title_label = QLabel("Z title:")
        axis_title_row.addWidget(self._z_title_label)
        self.zaxis_title_edit = QLineEdit()
        self.zaxis_title_edit.setPlaceholderText("Auto (column name)")
        self.zaxis_title_edit.setToolTip(
            "Override the Z-axis title (3D scatter). Empty keeps the column name."
        )
        self.zaxis_title_edit.editingFinished.connect(self._schedule_plot)
        axis_title_row.addWidget(self.zaxis_title_edit, 1)
        labels_l.addLayout(axis_title_row)
        self._labels_group = gb_labels
        ctrl_root.addWidget(gb_labels)

        self._radar_host = QWidget()
        radar_ly = QVBoxLayout(self._radar_host)
        radar_ly.setContentsMargins(0, 0, 0, 0)
        radar_ly.setSpacing(6)
        spokes_gb = QGroupBox("Spokes (numeric columns)")
        spokes_ly = QVBoxLayout(spokes_gb)
        spoke_row = QHBoxLayout()
        spoke_row.setSpacing(6)
        self.spoke_combos: list[QComboBox] = []
        for i in range(MAX_RADAR_VARIABLES):
            spoke_row.addWidget(QLabel(f"{i + 1}:"))
            combo = QComboBox()
            combo.setToolTip(f"Spoke {i + 1}: choose a numeric column, or {SPOKE_NONE}.")
            combo.currentIndexChanged.connect(lambda _idx, n=i: self._on_radar_spoke_changed(n))
            self.spoke_combos.append(combo)
            spoke_row.addWidget(combo, 1)
        spokes_ly.addLayout(spoke_row)
        self.entry_edits: list[QLineEdit] = []
        for row_start in (0, 3):
            entries_row = QHBoxLayout()
            entries_row.setSpacing(6)
            for i in range(row_start, min(row_start + 3, MAX_RADAR_DISPLAY_ENTRIES)):
                entries_row.addWidget(QLabel(f"Entry {i + 1}:"))
                edit = QLineEdit()
                edit.setPlaceholderText("Row ID")
                edit.setToolTip(
                    "OID or 1-based table row number. Leave empty to plot all rows in scope."
                )
                edit.textChanged.connect(self._schedule_plot)
                self.entry_edits.append(edit)
                entries_row.addWidget(edit, 1)
            spokes_ly.addLayout(entries_row)
        hint = QLabel(
            f"Choose {MIN_RADAR_VARIABLES}–{MAX_RADAR_VARIABLES} different spoke columns. "
            f"Type up to {MAX_RADAR_DISPLAY_ENTRIES} row IDs to plot only those entries; "
            f"leave entry fields empty to plot every row in scope (up to {MAX_RADAR_TRACES:,}). "
            "Spoke values are min–max normalized across all rows in scope before plotting. "
            "Click a trace to select that row in the table."
        )
        hint.setWordWrap(True)
        spokes_ly.addWidget(hint)
        radar_ly.addWidget(spokes_gb)
        self._radar_host.hide()
        ctrl_root.addWidget(self._radar_host)

        self._controls_bottom = QSplitter(Qt.Horizontal)
        self._controls_bottom.setChildrenCollapsible(False)
        ctrl_wrap.setMinimumWidth(PlotWidget._AXES_CONTROLS_MIN_WIDTH)
        self._controls_bottom.addWidget(ctrl_wrap)
        self._stats_panel = PlotStatisticsPanel(self)
        self._stats_panel.setMinimumWidth(PlotWidget._STATS_PANEL_MIN_WIDTH)
        self._controls_bottom.addWidget(self._stats_panel)
        self._controls_bottom.setStretchFactor(0, 1)
        self._controls_bottom.setStretchFactor(1, 1)
        self._controls_bottom.setSizes(
            [PlotWidget._AXES_CONTROLS_MIN_WIDTH, PlotWidget._STATS_PANEL_MIN_WIDTH + 40]
        )
        opts_root.addWidget(self._controls_bottom, 1)

        self._opts_dialog = make_plot_options_dialog(
            self,
            self._opts_panel,
            min_width=720,
            min_height=420,
        )

        root.addWidget(self.web, 1)

        self._footer_bar = QWidget(self)
        self._footer_bar.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        foot = QHBoxLayout(self._footer_bar)
        foot.setContentsMargins(0, 0, 0, 0)
        foot.setSpacing(4)
        self._opts_btn = make_plot_options_button(
            self,
            tooltip="Configure plot type, axes, titles, color, fit, and statistics.",
        )
        self._opts_btn.clicked.connect(self._open_plot_options)
        foot.addWidget(self._opts_btn)
        self._clear_sel_btn = make_clear_selection_button(self)
        self._clear_sel_btn.clicked.connect(self._on_clear_selection_clicked)
        foot.addWidget(self._clear_sel_btn)
        foot.addStretch(1)
        self._add_to_main_btn = make_add_to_main_button(
            self,
            tooltip="Dock this plot beside the table in the main window (like the filter panel).",
        )
        self._add_to_main_btn.clicked.connect(self._add_to_main_window)
        foot.addWidget(self._add_to_main_btn)
        self._send_window_btn = make_send_window_button(
            self,
            tooltip="Open this docked plot in a separate floating window.",
        )
        self._send_window_btn.clicked.connect(self._send_to_new_window)
        foot.addWidget(self._send_window_btn)
        self._close_plot_btn = make_close_plot_button(self)
        self._close_plot_btn.clicked.connect(self._close_docked_plot)
        foot.addWidget(self._close_plot_btn)
        root.insertWidget(0, self._footer_bar)
        self._sync_footer_chrome()
        self.setMinimumWidth(self.embedded_minimum_width())

        self._bridge = _PlotBridge(self)
        self._web_channel = QWebChannel(self.web.page())
        self._web_channel.registerObject("chemBridge", self._bridge)
        self.web.page().setWebChannel(self._web_channel)
        self.web.loadFinished.connect(self._on_web_load_finished)

        self._plot_debounce = QTimer(self)
        self._plot_debounce.setSingleShot(True)
        self._plot_debounce.timeout.connect(self.plot)

        self.plot_type_combo.currentIndexChanged.connect(self._on_plot_type_change)
        self.x_combo.currentIndexChanged.connect(self._on_axis_change)
        self.y_combo.currentIndexChanged.connect(self._on_axis_change)
        self.z_combo.currentIndexChanged.connect(self._on_axis_change)
        self.xmin.editingFinished.connect(self._schedule_plot)
        self.xmax.editingFinished.connect(self._schedule_plot)
        self.ymin.editingFinished.connect(self._schedule_plot)
        self.ymax.editingFinished.connect(self._schedule_plot)
        self.zmin.editingFinished.connect(self._schedule_plot)
        self.zmax.editingFinished.connect(self._schedule_plot)

        self._load_plot_shell()
        self._reload_color_columns()
        self._refresh_radar_spoke_columns()
        self._on_axis_change()
        if parent_app is not None:
            model = parent_app._table_model
            model.rowsRemoved.connect(self._on_table_rows_changed)
            model.rowsInserted.connect(self._on_table_rows_changed)
            model.dataChanged.connect(self._on_table_data_changed)
            model.modelReset.connect(self._on_table_model_reset)
            model.columnsInserted.connect(self._on_table_columns_changed)
            model.columnsRemoved.connect(self._on_table_columns_changed)
            model.headerDataChanged.connect(self._on_table_header_data_changed)

    def _open_plot_options(self) -> None:
        """Open the plot configuration dialog (axes, titles, color, fit, statistics)."""
        show_plot_options_dialog(self._opts_dialog)

    def _add_to_main_window(self) -> None:
        if self.parent_app is None:
            return
        dlg = self.window()
        teardown = getattr(dlg, "_scope_sync_disconnect", None)
        if callable(teardown):
            teardown()
        if not self.parent_app.dock_plot_widget(self):
            return
        if isinstance(dlg, PlotDialog):
            dlg._plot_widget = None
            dlg._force_close = True
            dlg.close()

    def _send_to_new_window(self) -> None:
        if self.parent_app is not None:
            self.parent_app.undock_plot_to_window(self)

    def _close_docked_plot(self) -> None:
        request_close_plot_widget(self)

    def _is_docked_in_main_window(self) -> bool:
        app = self.parent_app
        if app is None:
            return False
        check = getattr(app, "is_plot_docked", None)
        if callable(check):
            return bool(check(self))
        return getattr(app, "_docked_plot_widget", None) is self

    def _sync_footer_chrome(self) -> None:
        """Floating: opts + clear + Add. Docked: opts + clear + Send + Close Plot."""
        from .dockable_plot import sync_docked_footer_bar

        apply_plot_chrome_glyphs(self)
        floating = isinstance(self.window(), PlotDialog)
        docked = self._is_docked_in_main_window()
        self._add_to_main_btn.setVisible(floating)
        self._send_window_btn.setVisible(docked)
        self._close_plot_btn.setVisible(docked)
        sync_docked_footer_bar(self, docked=docked)

    def _on_clear_selection_clicked(self) -> None:
        """Clear table and plot point selection from the footer button."""
        if self.parent_app is None:
            return
        self._clear_plot_table_selection(update_plot=True)
        if hasattr(self.parent_app, "status_label"):
            self.parent_app.status_label.setText("Plot: selection cleared.")

    def event(self, event):  # noqa: N802 — Qt API name
        if event.type() == QEvent.ParentChange:
            self._sync_footer_chrome()
        return super().event(event)

    def create_floating_dialog(self, parent_app) -> PlotDialog:
        """Re-open this plotter in a floating window after undocking from the main table."""
        return PlotDialog(parent_app, plot_widget=self)

    def embedded_minimum_width(self) -> int:
        """Minimum dock width for the figure (options open in a separate dialog)."""
        return 420

    def embedded_preferred_width(self) -> int:
        return max(self.embedded_minimum_width(), 640)

    def _on_table_rows_changed(self, *_args) -> None:
        """Refresh plot when rows are added or removed."""
        if self._selected_point_indices:
            self._clear_plot_table_selection(update_plot=False)
        self._schedule_plot()

    def _on_table_data_changed(self, top_left=None, bottom_right=None, roles=()) -> None:
        """Refresh plot when cell values change (filters, descriptors, edits)."""
        from .compound_table_model import CompoundTableModel

        if CompoundTableModel.is_structure_paint_data_change(top_left, bottom_right, roles):
            return
        self._schedule_plot()

    def _on_table_model_reset(self, *_args) -> None:
        """Rows and columns may both change after a model reset."""
        self._on_table_columns_changed()

    def _on_table_columns_changed(self, *_args) -> None:
        """Repopulate axis combos when columns are inserted or removed."""
        self.refresh_axis_columns()

    def _on_table_header_data_changed(self, orientation, first: int, last: int) -> None:
        if int(orientation) == Qt.Horizontal:
            self.refresh_axis_columns()

    def refresh_axis_columns(self) -> None:
        """Sync X/Y/Z and radar spoke column lists with the table."""
        if self.parent_app is None:
            return
        cols = self._numeric_column_names()
        x_prev = self.x_combo.currentText()
        y_prev = self.y_combo.currentText()
        z_prev = self.z_combo.currentText()
        self._set_axis_combo_items(self.x_combo, cols, previous=x_prev, allow_none=False)
        self._set_axis_combo_items(self.y_combo, cols, previous=y_prev, allow_none=True)
        self._set_axis_combo_items(self.z_combo, cols, previous=z_prev, allow_none=True)
        self._prev_range_axis = {"x": "", "y": "", "z": ""}
        self._reload_color_columns()
        self._refresh_radar_spoke_columns()
        self._on_axis_change()

    def _refresh_radar_spoke_columns(self) -> None:
        """Sync radar spoke dropdowns when table columns change."""
        if self.parent_app is None or not self.spoke_combos:
            return
        cols = self._numeric_column_names()
        previous = [c.currentText() for c in self.spoke_combos]
        for combo, prev in zip(self.spoke_combos, previous):
            combo.blockSignals(True)
            try:
                combo.clear()
                combo.addItem(SPOKE_NONE)
                for col in cols:
                    combo.addItem(col)
                idx = combo.findText(prev)
                combo.setCurrentIndex(idx if idx >= 0 else 0)
            finally:
                combo.blockSignals(False)

    def _selected_radar_spoke_columns(self) -> list[str]:
        cols: list[str] = []
        for combo in self.spoke_combos:
            text = combo.currentText()
            if text and text != SPOKE_NONE:
                cols.append(text)
        return cols

    def _on_radar_spoke_changed(self, spoke_index: int) -> None:
        combo = self.spoke_combos[spoke_index]
        chosen = combo.currentText()
        if chosen and chosen != SPOKE_NONE:
            for i, other in enumerate(self.spoke_combos):
                if i != spoke_index and other.currentText() == chosen:
                    combo.blockSignals(True)
                    try:
                        combo.setCurrentIndex(0)
                    finally:
                        combo.blockSignals(False)
                    QMessageBox.information(
                        self,
                        "Radar Plot",
                        f'Column "{chosen}" is already assigned to another spoke.',
                    )
                    return
        self._schedule_plot()

    def _selected_radar_entry_oids(self) -> tuple[list[int] | None, list[str]]:
        """Return (oids to plot, or None for all rows) and invalid ID strings entered."""
        if self.parent_app is None:
            return None, []
        model = self.parent_app._table_model
        oids: list[int] = []
        invalid: list[str] = []
        for edit in self.entry_edits:
            text = edit.text().strip()
            if not text:
                continue
            oid = resolve_entry_row_oid(
                text,
                model=model,
                row_for_oid=self.parent_app.logical_row_for_oid,
            )
            if oid is None:
                invalid.append(text)
                continue
            if oid not in oids:
                oids.append(oid)
        return (oids or None), invalid

    def _reload_color_columns(self) -> None:
        prev = self.color_combo.currentText()
        prev_size = self.size_combo.currentText()
        self.color_combo.blockSignals(True)
        self.size_combo.blockSignals(True)
        try:
            self.color_combo.clear()
            self.color_combo.addItem("(none)")
            self.size_combo.clear()
            self.size_combo.addItem("(none)")
            if self.parent_app is not None:
                for h in self.parent_app.headers:
                    if h and h != "ID_HIDDEN":
                        self.color_combo.addItem(h)
                        self.size_combo.addItem(h)
            idx = self.color_combo.findText(prev)
            if idx >= 0:
                self.color_combo.setCurrentIndex(idx)
            sidx = self.size_combo.findText(prev_size)
            if sidx >= 0:
                self.size_combo.setCurrentIndex(sidx)
        finally:
            self.color_combo.blockSignals(False)
            self.size_combo.blockSignals(False)
        self._reload_hover_columns()

    def _reload_hover_columns(self) -> None:
        """Populate On Hover column pickers from current table headers."""
        headers = list(getattr(self.parent_app, "headers", []) or []) if self.parent_app else []
        self._hover_controls.reload_columns(headers)

    def _selected_hover_columns(self) -> list[str]:
        return self._hover_controls.selected_columns()

    def _hover_card_json_for_point(self, point_index: int) -> str:
        if point_index < 0 or point_index >= len(self._plotted_oids):
            return ""
        oid = int(self._plotted_oids[point_index])
        show_struct = bool(
            getattr(self, "hover_structure_cb", None) and self.hover_structure_cb.isChecked()
        )
        payload = hover_cards_payload(
            self.parent_app,
            [oid],
            self._selected_hover_columns(),
            show_structure=show_struct,
        )
        return json.dumps(payload, separators=(",", ":"))

    def _hover_card_json_for_points(self, indices_json: str) -> str:
        try:
            raw = json.loads(indices_json or "[]")
            idxs = [int(x) for x in raw if isinstance(x, (int, float))]
        except Exception:
            idxs = []
        oids: list[int] = []
        n = len(self._plotted_oids)
        for i in idxs:
            if 0 <= i < n:
                oids.append(int(self._plotted_oids[i]))
        if not oids:
            return ""
        show_struct = bool(
            getattr(self, "hover_structure_cb", None) and self.hover_structure_cb.isChecked()
        )
        payload = hover_cards_payload(
            self.parent_app,
            oids,
            self._selected_hover_columns(),
            show_structure=show_struct,
        )
        return json.dumps(payload, separators=(",", ":"))

    def _on_hover_persist_changed(self, *_args) -> None:
        self._sync_hover_persist_visual()

    def _sync_hover_persist_visual(self) -> None:
        if not self._web_ready:
            return
        persist = bool(
            getattr(self, "hover_persist_cb", None) and self.hover_persist_cb.isChecked()
        )
        self.web.page().runJavaScript(
            f"window.molmanagerSetHoverPersist && molmanagerSetHoverPersist({json.dumps(persist)});"
        )
        if not persist:
            self.web.page().runJavaScript(
                "window.molmanagerClearHoverPin && molmanagerClearHoverPin();"
            )
            return
        from .plot_hover import HOVER_MULTI_MAX_ITEMS

        n_sel = len(self._selected_point_indices)
        if n_sel == 0 or n_sel > HOVER_MULTI_MAX_ITEMS:
            self.web.page().runJavaScript(
                "window.molmanagerClearHoverPin && molmanagerClearHoverPin();"
            )
            return
        idxs = sorted(self._selected_point_indices)
        js_idxs = json.dumps(idxs)
        self.web.page().runJavaScript(
            f"window.molmanagerPinHoverPoints && molmanagerPinHoverPoints({json.dumps(js_idxs)});"
        )

    def _attach_point_hover(self, trace_kwargs: dict, oids: list[int]) -> dict:
        """Disable native Plotly hover labels; custom overlay uses OIDs via the bridge."""
        out = dict(trace_kwargs)
        out["customdata"] = [[int(oid)] for oid in oids]
        out["hoverinfo"] = "none"
        return out

    def _current_color_column(self) -> str | None:
        text = self.color_combo.currentText()
        return None if not text or text == "(none)" else text

    def _current_size_column(self) -> str | None:
        text = self.size_combo.currentText()
        return None if not text or text == "(none)" else text

    def _column_values_for_oids(self, oids: list[int], column: str | None) -> list | None:
        if not column or self.parent_app is None:
            return None
        model = self.parent_app._table_model
        out: list = []
        for oid in oids:
            row = self.parent_app.logical_row_for_oid(int(oid))
            if row < 0:
                out.append(None)
                continue
            raw = model.value_for_header(row, column)
            out.append(raw if (raw or "").strip() else None)
        return out

    def _color_values_for_oids(self, oids: list[int]) -> tuple[list | None, str | None]:
        color_col = self._current_color_column()
        if not color_col:
            return None, None
        return self._column_values_for_oids(oids, color_col), color_col

    def _size_values_for_oids(self, oids: list[int]) -> tuple[list | None, str | None]:
        size_col = self._current_size_column()
        if not size_col:
            return None, None
        return self._column_values_for_oids(oids, size_col), size_col

    def _scatter_marker_for_oids(self, oids: list[int], *, point_size: float = 6) -> dict:
        color_vals, color_label = self._color_values_for_oids(oids)
        color_vals, color_label = normalize_color_column(color_vals, color_label)
        size_vals, size_label = self._size_values_for_oids(oids)
        size_vals, size_label = normalize_size_column(size_vals, size_label)
        color_min, color_max = self.color_range.parse_bounds()
        size_min_px, size_max_px = self.size_range.parse_bounds()
        return scatter_marker_from_column_values(
            color_vals,
            color_label=color_label,
            colorscale=resolve_plot_colorscale(self.colorscale_combo.currentText()),
            color_min=color_min,
            color_max=color_max,
            size_values=size_vals,
            size_min_px=size_min_px,
            size_max_px=size_max_px,
            point_size=point_size,
        )

    def _attach_size_legend_for_oids(self, fig: go.Figure, oids: list[int]) -> None:
        size_vals, size_label = self._size_values_for_oids(oids)
        size_vals, size_label = normalize_size_column(size_vals, size_label)
        if not size_vals or not size_label:
            return
        size_min_px, size_max_px = self.size_range.parse_bounds()
        attach_marker_size_legend(
            fig,
            size_label=size_label,
            size_values=size_vals,
            size_min_px=size_min_px,
            size_max_px=size_max_px,
        )

    def _on_color_column_changed(self, _index: int = 0) -> None:
        self._update_color_controls()
        self._schedule_plot()

    def _on_size_column_changed(self, _index: int = 0) -> None:
        self._update_size_controls()
        self._schedule_plot()

    def _current_fit_kind(self) -> str:
        key = self.fit_combo.currentData()
        return str(key) if key else FIT_NONE

    def _is_histogram_plot(self) -> bool:
        return self._current_plot_type() == PLOT_TYPE_HISTOGRAM

    def _analysis_supports_fit(self) -> bool:
        ptype = self._current_plot_type()
        if ptype in (PLOT_TYPE_HEATMAP, PLOT_TYPE_BOX, PLOT_TYPE_VIOLIN, PLOT_TYPE_RADAR):
            return False
        if ptype == PLOT_TYPE_LINE_2D:
            return True
        if ptype == PLOT_TYPE_HISTOGRAM:
            return True
        if ptype != PLOT_TYPE_SCATTER:
            return False
        return self._effective_plot_mode() == "2D"

    def _refresh_fit_combo_items(self) -> None:
        prev = self._current_fit_kind()
        choices = PLOT_FIT_CHOICES if self._is_histogram_plot() else PLOT_FIT_CHOICES_XY
        self.fit_combo.blockSignals(True)
        try:
            self.fit_combo.clear()
            for label, key in choices:
                self.fit_combo.addItem(label, key)
            idx = self.fit_combo.findData(prev)
            if idx < 0:
                idx = 0
            self.fit_combo.setCurrentIndex(idx)
        finally:
            self.fit_combo.blockSignals(False)

    def _on_fit_option_changed(self, *_args) -> None:
        self._update_analysis_controls()
        self._schedule_plot()

    def _truncation_bounds(self) -> tuple[float | None, float | None]:
        return (
            self._parse_edit_float(self.fit_trunc_lower),
            self._parse_edit_float(self.fit_trunc_upper),
        )

    def _uses_truncated_gaussian_fit(self) -> bool:
        return self._is_histogram_plot() and self._current_fit_kind() == FIT_TRUNCATED_GAUSSIAN

    def _present_analysis_panel(
        self,
        stats_lines: list[str] | None,
        fit_summary: str | None,
    ) -> None:
        parts: list[str] = []
        if stats_lines:
            parts.extend(stats_lines)
        if fit_summary:
            if parts:
                parts.append("")
            parts.append("Curve fit")
            parts.append(f"  {fit_summary}")
            parts.append("  (orange line on plot)")
        if not parts:
            self._stats_panel.set_lines(["No statistics for the current plot."])
            return
        self._stats_panel.set_lines(parts)

    def _present_analysis_dialog(
        self,
        stats_lines: list[str] | None,
        fit_summary: str | None,
    ) -> None:
        """Backward-compatible alias for :meth:`_present_analysis_panel`."""
        self._present_analysis_panel(stats_lines, fit_summary)

    def _fit_summary_from_name(self, name: str) -> str:
        return name.removeprefix("Fit: ").strip() if name.startswith("Fit:") else name

    def _add_fit_line_trace(self, fig: go.Figure, xs: list[float], ys: list[float]) -> None:
        fig.add_trace(
            go.Scatter(
                x=xs,
                y=ys,
                mode="lines",
                name="Fit",
                showlegend=False,
                line={"color": "#e76f51", "width": 2.5, "dash": "solid"},
            )
        )

    def _add_xy_fit_trace(self, fig: go.Figure, x: list[float], y: list[float]) -> str | None:
        if self._is_histogram_plot() or self._current_fit_kind() in HISTOGRAM_ONLY_FITS:
            return None
        if not self._analysis_supports_fit() or self._current_fit_kind() == FIT_NONE:
            return None
        fit = fit_xy_curve(x, y, self._current_fit_kind())
        if not fit:
            return None
        xs, ys, name = fit
        self._add_fit_line_trace(fig, xs, ys)
        summary = self._fit_summary_from_name(name)
        self._maybe_annotate_fit_formula(fig, summary)
        return summary

    def _add_histogram_fit_trace(
        self,
        fig: go.Figure,
        vals: list[float],
        edges: list[float],
        *,
        bin_width: float,
    ) -> str | None:
        if not self._is_histogram_plot() or self._current_fit_kind() == FIT_NONE:
            return None
        trunc_lo, trunc_hi = self._truncation_bounds()
        fit = fit_histogram_curve(
            vals,
            edges,
            self._current_fit_kind(),
            bin_width=bin_width,
            trunc_lower=trunc_lo,
            trunc_upper=trunc_hi,
        )
        if not fit:
            return None
        xs, ys, name = fit
        self._add_fit_line_trace(fig, xs, ys)
        summary = self._fit_summary_from_name(name)
        self._maybe_annotate_fit_formula(fig, summary)
        return summary

    def _maybe_annotate_fit_formula(self, fig: go.Figure, fit_summary: str | None) -> None:
        if not fit_summary:
            return
        cb = getattr(self, "show_fit_formula_cb", None)
        if cb is None or not cb.isChecked():
            return
        add_fit_formula_annotation(fig, fit_summary)

    def _apply_user_plot_labels(self, fig: go.Figure) -> None:
        apply_plotly_label_overrides(
            fig,
            title=self.plot_title_edit.text() if hasattr(self, "plot_title_edit") else "",
            x_title=self.xaxis_title_edit.text() if hasattr(self, "xaxis_title_edit") else "",
            y_title=self.yaxis_title_edit.text() if hasattr(self, "yaxis_title_edit") else "",
            z_title=self.zaxis_title_edit.text() if hasattr(self, "zaxis_title_edit") else "",
        )

    def _update_analysis_controls(self) -> None:
        self._refresh_fit_combo_items()
        fit_ok = self._analysis_supports_fit()
        self._fit_label.setEnabled(fit_ok)
        self.fit_combo.setEnabled(fit_ok)
        if hasattr(self, "show_fit_formula_cb"):
            self.show_fit_formula_cb.setEnabled(fit_ok)
        trunc_on = fit_ok and self._uses_truncated_gaussian_fit()
        for widget in (
            self._trunc_lower_label,
            self.fit_trunc_lower,
            self._trunc_upper_label,
            self.fit_trunc_upper,
        ):
            widget.setEnabled(trunc_on)
            widget.setVisible(self._is_histogram_plot())

    def _color_by_supported(self) -> bool:
        ptype = self._current_plot_type()
        if ptype in (PLOT_TYPE_HEATMAP, PLOT_TYPE_BOX, PLOT_TYPE_VIOLIN, PLOT_TYPE_RADAR):
            return False
        if ptype == PLOT_TYPE_LINE_2D:
            return True
        if ptype != PLOT_TYPE_SCATTER:
            return False
        return self._effective_plot_mode() in ("2D", "3D")

    def _probe_color_values(self) -> list | None:
        """Sample color-column values for numeric vs categorical detection."""
        color_col = self._current_color_column()
        if not color_col or self.parent_app is None:
            return None
        if self._plotted_oids:
            vals, _ = self._color_values_for_oids(self._plotted_oids)
            return vals
        model = self.parent_app._table_model
        out: list = []
        for r in range(min(model.rowCount(), 2000)):
            raw = model.value_for_header(r, color_col)
            out.append(raw if (raw or "").strip() else None)
        return out

    def _update_color_controls(self) -> None:
        heatmap = self._is_heatmap_plot()
        supported = self._color_by_supported()
        self.color_combo.setEnabled(supported)
        self._color_by_label.setEnabled(supported)
        spectrum_on = heatmap or (supported and self._current_color_column() is not None)
        self._spectrum_label.setEnabled(spectrum_on)
        self.colorscale_combo.setEnabled(spectrum_on)
        numeric = (
            not heatmap and spectrum_on and color_values_are_numeric(self._probe_color_values())
        )
        self.color_range.set_enabled(numeric)
        self._update_size_controls()
        self._update_analysis_controls()

    def _update_size_controls(self) -> None:
        supported = self._color_by_supported()
        self.size_combo.setEnabled(supported)
        self._size_by_label.setEnabled(supported)
        size_on = supported and self._current_size_column() is not None
        self.size_range.set_enabled(size_on)

    def _schedule_plot(self) -> None:
        timer = getattr(self, "_plot_debounce", None)
        if timer is None:
            return
        timer.start(70)

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
        if vmin is None and vmax is None:
            return {}
        vals = data_vals or []
        lo = float(vmin) if vmin is not None else (min(vals) if vals else 0.0)
        hi = float(vmax) if vmax is not None else (max(vals) if vals else lo + 1.0)
        if lo > hi:
            lo, hi = hi, lo
        return {"range": [lo, hi], "autorange": False}

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
        PlotWidget._set_axis_combo_items(combo, cols, previous=default, allow_none=True)

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

    def _supports_table_linked_selection(self) -> bool:
        """Plot types that mirror table row selection via ``molmanagerSetSelection``."""
        ptype = self._current_plot_type()
        mode = self._effective_plot_mode()
        if ptype == PLOT_TYPE_LINE_2D and mode == "2D":
            return True
        if ptype == PLOT_TYPE_HEATMAP:
            return False
        if ptype in (PLOT_TYPE_BOX, PLOT_TYPE_VIOLIN, PLOT_TYPE_RADAR):
            return False
        if ptype == PLOT_TYPE_HISTOGRAM:
            return mode == "Histogram"
        return mode in ("2D", "3D")

    def _plot_source_row_indices(self):
        """Source-model rows for plotting (visible/filtered rows; optional selection-only).

        When every row is in scope, returns ``range(rowCount)`` instead of ``None`` so callers
        can iterate without allocating a full index list.
        """
        model = self.parent_app._table_model
        only_sel = None
        n_sel_now = len(self.parent_app._selected_logical_rows())
        if n_sel_now > 0 and self.only_selected_cb.isChecked():
            only_sel = list(self.parent_app._selected_logical_rows())
        visible = self.parent_app._visible_source_row_indices()
        rows = snapshot_scope_row_indices(
            model.rowCount(),
            only_selected_rows=only_sel,
            visible_row_indices=visible,
        )
        if rows is None:
            return range(model.rowCount())
        return rows

    def _collect_points(
        self,
    ) -> tuple[list[float], list[float], list[float], list[int], str, str, str | None]:
        mode = self._effective_plot_mode()
        if mode not in ("2D", "3D", "Heatmap"):
            return [], [], [], [], "", "", None

        xname = self._combo_axis_name(self.x_combo) or ""
        yname = self._combo_axis_name(self.y_combo) or ""
        if not xname or not yname:
            return [], [], [], [], "", "", None

        h_map = {h: i for i, h in enumerate(self.parent_app.headers)}
        xi = h_map.get(xname)
        yi = h_map.get(yname)
        if xi is None or yi is None:
            return [], [], [], [], xname, yname, None

        n_sel_now = (
            len(self.parent_app._selected_logical_rows()) if self.parent_app is not None else 0
        )
        only_sel = n_sel_now > 0 and self.only_selected_cb.isChecked()
        allowed = self.parent_app._selected_oids_set() if only_sel else None
        if only_sel and not allowed:
            QMessageBox.warning(
                self, "Plot", "“Selected Rows Only” is checked but nothing is selected."
            )
            return [], [], [], [], xname, yname, None

        is3d = mode == "3D"
        zname = self._combo_axis_name(self.z_combo) if is3d else None
        zi = h_map.get(zname) if is3d else None
        if is3d and zi is None:
            return [], [], [], [], xname, yname, zname

        xmin = self._parse_edit_float(self.xmin)
        xmax = self._parse_edit_float(self.xmax)
        ymin = self._parse_edit_float(self.ymin)
        ymax = self._parse_edit_float(self.ymax)
        zmin = self._parse_edit_float(self.zmin) if is3d else None
        zmax = self._parse_edit_float(self.zmax) if is3d else None

        fx: list[float] = []
        fy: list[float] = []
        fz: list[float] = []
        foids: list[int] = []
        m = self.parent_app._table_model
        for r in self._plot_source_row_indices():
            oid = int(m.row_oid(r))
            if allowed is not None and oid not in allowed:
                continue
            xv = safe_float(m.cell_text(r, xi))
            yv = safe_float(m.cell_text(r, yi))
            if xv is None or yv is None:
                continue
            xv = float(xv)
            yv = float(yv)
            if xmin is not None and xv < xmin:
                continue
            if xmax is not None and xv > xmax:
                continue
            if ymin is not None and yv < ymin:
                continue
            if ymax is not None and yv > ymax:
                continue
            if is3d:
                zv = safe_float(m.cell_text(r, zi)) if zi is not None else None
                if zv is None:
                    continue
                zv = float(zv)
                if zmin is not None and zv < zmin:
                    continue
                if zmax is not None and zv > zmax:
                    continue
                fz.append(zv)
            fx.append(xv)
            fy.append(yv)
            foids.append(oid)
        return fx, fy, fz, foids, xname, yname, zname

    def _collect_histogram(self) -> tuple[list[float], list[int], str]:
        """Values and oids for a single-column histogram."""
        xname = self._combo_axis_name(self.x_combo) or ""
        if not xname:
            return [], [], ""
        h_map = {h: i for i, h in enumerate(self.parent_app.headers)}
        xi = h_map.get(xname)
        if xi is None:
            return [], [], xname

        n_sel_now = (
            len(self.parent_app._selected_logical_rows()) if self.parent_app is not None else 0
        )
        only_sel = n_sel_now > 0 and self.only_selected_cb.isChecked()
        allowed = self.parent_app._selected_oids_set() if only_sel else None
        if only_sel and not allowed:
            QMessageBox.warning(
                self, "Plot", "“Selected Rows Only” is checked but nothing is selected."
            )
            return [], [], xname

        xmin = self._parse_edit_float(self.xmin)
        xmax = self._parse_edit_float(self.xmax)
        vals: list[float] = []
        oids: list[int] = []
        m = self.parent_app._table_model
        for r in self._plot_source_row_indices():
            oid = int(m.row_oid(r))
            if allowed is not None and oid not in allowed:
                continue
            xv = safe_float(m.cell_text(r, xi))
            if xv is None:
                continue
            xv = float(xv)
            if xmin is not None and xv < xmin:
                continue
            if xmax is not None and xv > xmax:
                continue
            vals.append(xv)
            oids.append(oid)
        return vals, oids, xname

    def _load_plot_shell(self) -> None:
        from .plotly_shell import write_interactive_plot_shell

        write_interactive_plot_shell(self._plot_shell_path)
        self.web.load(QUrl.fromLocalFile(str(self._plot_shell_path)))

    def _annotate_scatter_selection_meta(self, fig: go.Figure) -> None:
        """Tell the Plotly shell which traces map to table row indices (skip fit lines, etc.)."""
        meta: dict = {}
        if self._supports_table_linked_selection():
            indices: list[int] = []
            for i, tr in enumerate(fig.data):
                t = getattr(tr, "type", None)
                mode = str(getattr(tr, "mode", "") or "")
                if t in ("scatter", "scattergl") and ("markers" in mode or mode == ""):
                    indices.append(i)
                elif t == "scatter3d" and i == 0:
                    indices.append(i)
                elif t == "histogram" and i == 0:
                    indices.append(i)
            if indices:
                meta["molmanager_selection_traces"] = indices
        persist = bool(
            getattr(self, "hover_persist_cb", None) and self.hover_persist_cb.isChecked()
        )
        meta["molmanager_hover_persist"] = persist
        if meta:
            fig.update_layout(meta=meta)

    def _push_plotly_figure(self, fig: go.Figure) -> None:
        from .plotly_html import figure_payload_json

        self._apply_user_plot_labels(fig)
        self._oid_point_index = build_oid_point_index(self._plotted_oids)
        self._last_pushed_selection_key = None
        self._annotate_scatter_selection_meta(fig)
        self._pending_payload_json = figure_payload_json(fig)
        self._last_browser_opened_path = None
        if self._web_ready:
            self._apply_pending_payload()
            QTimer.singleShot(0, self.sync_from_table_selection)
            QTimer.singleShot(50, self._sync_hover_persist_visual)

    def _apply_pending_payload(self) -> None:
        if not self._web_ready or not self._pending_payload_json:
            return
        run_javascript_apply_figure(self.web.page(), self._pending_payload_json)
        self._arm_ignore_plot_clear()
        QTimer.singleShot(300, self.sync_from_table_selection)

    def sync_from_table_selection(
        self, selected_oids: set[int] | frozenset[int] | None = None
    ) -> None:
        """Highlight plot points for the current table row selection."""
        if not self._plotted_oids or self.parent_app is None:
            return
        if not self._supports_table_linked_selection():
            return
        selected = (
            {int(x) for x in selected_oids}
            if selected_oids is not None
            else selected_oids_for_plot(self.parent_app)
        )
        new_idxs = point_indices_for_oids(
            self._plotted_oids, selected, oid_index=getattr(self, "_oid_point_index", None)
        )
        if new_idxs == self._selected_point_indices and self._last_pushed_selection_key is not None:
            return
        self._selected_point_indices = new_idxs
        self._arm_ignore_plot_clear()
        self._sync_plot_selection_visual()

    def _sync_plot_selection_visual(self) -> None:
        if not self._web_ready:
            self._pending_table_selection_sync = True
            return
        self._pending_table_selection_sync = False
        key = selection_visual_push_key(self._selected_point_indices)
        if key == getattr(self, "_last_pushed_selection_key", None):
            return
        self._last_pushed_selection_key = key
        run_javascript_set_selection(self.web.page(), self._selected_point_indices)
        QTimer.singleShot(0, self._sync_hover_persist_visual)

    def _clear_plot_table_selection(self, *, update_plot: bool = True) -> None:
        self._selected_point_indices = set()
        self._ignore_plot_clear_until = 0.0
        clear_table_selection_from_plot(self.parent_app)
        if update_plot:
            self._sync_plot_selection_visual()
        else:
            self._last_pushed_selection_key = None
            self._sync_hover_persist_visual()

    def _arm_ignore_plot_clear(self, ms: int = 500) -> None:
        self._ignore_plot_clear_until = time.monotonic() + (ms / 1000.0)

    def _render_empty_plot(self, title: str) -> None:
        self._stats_panel.set_lines(["No statistics for the current plot."])
        fig = go.Figure()
        fig.update_layout(
            title=title,
            xaxis={"visible": False},
            yaxis={"visible": False},
            annotations=[
                {
                    "text": title,
                    "xref": "paper",
                    "yref": "paper",
                    "x": 0.5,
                    "y": 0.5,
                    "showarrow": False,
                }
            ],
            margin={"l": 20, "r": 20, "t": 50, "b": 20},
        )
        self._push_plotly_figure(fig)

    def _on_web_load_finished(self, ok: bool) -> None:
        if not ok:
            self._fallback_open_in_browser("Plot view failed to load in embedded renderer.")
            return

        def _after_probe(result) -> None:
            if not bool(result):
                self._fallback_open_in_browser(
                    "Embedded Plotly renderer is not supported on this system."
                )
                return
            self._web_ready = True
            self._apply_pending_payload()
            QTimer.singleShot(0, self.sync_from_table_selection)
            if self._pending_table_selection_sync:
                QTimer.singleShot(0, self.sync_from_table_selection)

        QTimer.singleShot(
            0,
            lambda: self.web.page().runJavaScript(
                "typeof window.Plotly !== 'undefined' && typeof window.molmanagerApply === 'function'",
                _after_probe,
            ),
        )

    def _fallback_open_in_browser(self, reason: str) -> None:
        path = str(self._plot_shell_path)
        if self._last_browser_opened_path == path:
            return
        self._last_browser_opened_path = path
        webbrowser.open(self._plot_shell_path.as_uri())
        self.parent_app.status_label.setText(f"Plot fallback: opened in browser ({reason})")

    def _empty_plot_hint(self) -> str:
        ptype = self._current_plot_type()
        if ptype == PLOT_TYPE_SCATTER:
            return "Choose X and Y for 2D scatter; set Z as well for 3D."
        if ptype == PLOT_TYPE_HISTOGRAM:
            return "Choose a numeric column for the X axis."
        if ptype in (PLOT_TYPE_BOX, PLOT_TYPE_VIOLIN):
            return "Choose a numeric column for the X axis."
        if ptype == PLOT_TYPE_LINE_2D:
            return "Choose X and Y columns for the line chart."
        if ptype == PLOT_TYPE_HEATMAP:
            return "Choose X and Y columns for the heatmap."
        if ptype == PLOT_TYPE_RADAR:
            return (
                f"Choose {MIN_RADAR_VARIABLES}–{MAX_RADAR_VARIABLES} numeric spokes "
                "in Plot Options."
            )
        return "Choose axes for the current plot type."

    def plot(self):
        ptype = self._current_plot_type()
        if ptype in (PLOT_TYPE_BOX, PLOT_TYPE_VIOLIN):
            self._plot_distribution(ptype)
        elif ptype == PLOT_TYPE_LINE_2D:
            self._plot_line_2d()
        elif ptype == PLOT_TYPE_HEATMAP:
            self._plot_heatmap()
        elif ptype == PLOT_TYPE_RADAR:
            self._plot_radar()
        elif ptype == PLOT_TYPE_HISTOGRAM:
            if self._effective_plot_mode() == "Histogram":
                self._plot_histogram()
            else:
                self._render_empty_plot(self._empty_plot_hint())
        else:
            mode = self._effective_plot_mode()
            if mode is None:
                self._render_empty_plot(self._empty_plot_hint())
            else:
                self._plot_scatter(mode)
        self._update_color_controls()

    def _plot_scatter(self, mode: str) -> None:
        self._hist_edges = []
        self._hist_vals = []
        self._hist_oids = []
        self._clear_heatmap_state()
        fx, fy, fz, foids, xname, yname, zname = self._collect_points()
        if not xname or not yname:
            self._render_empty_plot(self._empty_plot_hint())
            return
        is3d = mode == "3D"
        xmin = self._parse_edit_float(self.xmin)
        xmax = self._parse_edit_float(self.xmax)
        ymin = self._parse_edit_float(self.ymin)
        ymax = self._parse_edit_float(self.ymax)
        zmin = self._parse_edit_float(self.zmin) if is3d else None
        zmax = self._parse_edit_float(self.zmax) if is3d else None

        if not fx:
            self._plotted_oids = []
            self._selected_point_indices = set()
            fig = go.Figure()
            if is3d:
                fig.update_layout(
                    scene={
                        "xaxis": {"title": xname, **self._plotly_axis_range(xmin, xmax, [])},
                        "yaxis": {"title": yname, **self._plotly_axis_range(ymin, ymax, [])},
                        "zaxis": {"title": zname or "Z", **self._plotly_axis_range(zmin, zmax, [])},
                    },
                    margin={"l": 20, "r": 20, "t": 20, "b": 20},
                )
            else:
                fig.update_layout(
                    xaxis={"title": xname, **self._plotly_axis_range(xmin, xmax, [])},
                    yaxis={"title": yname, **self._plotly_axis_range(ymin, ymax, [])},
                    margin={"l": 50, "r": 20, "t": 20, "b": 45},
                )
            self._stats_panel.set_lines(["No statistics for the current plot."])
            self._push_plotly_figure(fig)
            self.parent_app.status_label.setText("Plot: no points for current axis/range/scope.")
            return

        self._plotted_oids = list(foids)
        self._selected_point_indices = {
            i for i in self._selected_point_indices if 0 <= i < len(self._plotted_oids)
        }
        selected_points = (
            sorted(self._selected_point_indices) if self._selected_point_indices else []
        )
        from ..config import load_config

        overlay_max = int(load_config().plot_selection_overlay_max_points)
        # Large selections are applied after react via molmanagerSetSelection (avoids fat payloads).
        bake_selection = bool(selected_points) and len(selected_points) <= overlay_max
        marker = self._scatter_marker_for_oids(foids, point_size=4 if is3d else 6)

        fig = go.Figure()
        if is3d:
            fig.add_trace(
                go.Scatter3d(
                    **self._attach_point_hover(
                        {
                            "x": fx,
                            "y": fy,
                            "z": fz,
                            "mode": "markers",
                            "marker": marker,
                            "name": "Points",
                            "showlegend": False,
                        },
                        foids,
                    )
                )
            )
            if bake_selection:
                sx = [fx[i] for i in selected_points]
                sy = [fy[i] for i in selected_points]
                sz = [fz[i] for i in selected_points]
                fig.add_trace(
                    go.Scatter3d(
                        x=sx,
                        y=sy,
                        z=sz,
                        mode="markers",
                        marker={"size": 7, "opacity": 1.0, "color": "#d62828"},
                        name="Selected",
                        showlegend=False,
                        hoverinfo="skip",
                    )
                )
            fig.update_layout(
                scene={
                    "xaxis": {"title": xname, **self._plotly_axis_range(xmin, xmax, fx)},
                    "yaxis": {"title": yname, **self._plotly_axis_range(ymin, ymax, fy)},
                    "zaxis": {"title": zname or "Z", **self._plotly_axis_range(zmin, zmax, fz)},
                },
                margin={"l": 20, "r": 20, "t": 20, "b": 20},
            )
            stats_lines = (
                summarize_univariate(fx, label=xname)
                + summarize_univariate(fy, label=yname)
                + summarize_univariate(fz, label=zname or "Z")
            )
            self._present_analysis_dialog(stats_lines, None)
        else:
            fig.add_trace(
                go.Scatter(
                    **self._attach_point_hover(
                        {
                            "x": fx,
                            "y": fy,
                            "mode": "markers",
                            "marker": marker,
                            "showlegend": False,
                            "selectedpoints": selected_points if bake_selection else None,
                            "selected": {"marker": {"size": 9, "color": "#d62828", "opacity": 1.0}},
                            "unselected": {"marker": {"opacity": 0.35}},
                        },
                        foids,
                    )
                )
            )
            fig.update_layout(
                xaxis={"title": xname, **self._plotly_axis_range(xmin, xmax, fx)},
                yaxis={"title": yname, **self._plotly_axis_range(ymin, ymax, fy)},
                dragmode="lasso",
                margin={"l": 50, "r": 20, "t": 20, "b": 45},
            )
            fit_summary = self._add_xy_fit_trace(fig, fx, fy)
            self._present_analysis_dialog(
                summarize_xy(fx, fy, x_label=xname, y_label=yname),
                fit_summary,
            )

        self._attach_size_legend_for_oids(fig, foids)
        self._push_plotly_figure(fig)
        self.parent_app.status_label.setText(f"Plot: rendered {len(fx):,} point(s).")

    def _plot_line_2d(self) -> None:
        self._clear_heatmap_state()
        fx, fy, _fz, foids, xname, yname, _zname = self._collect_points()
        if not xname or not yname:
            self._render_empty_plot(self._empty_plot_hint())
            return
        xmin = self._parse_edit_float(self.xmin)
        xmax = self._parse_edit_float(self.xmax)
        ymin = self._parse_edit_float(self.ymin)
        ymax = self._parse_edit_float(self.ymax)
        if not fx:
            self._plotted_oids = []
            self._selected_point_indices = set()
            fig = go.Figure()
            fig.update_layout(
                xaxis={"title": xname, **self._plotly_axis_range(xmin, xmax, [])},
                yaxis={"title": yname, **self._plotly_axis_range(ymin, ymax, [])},
                margin={"l": 50, "r": 20, "t": 20, "b": 45},
            )
            self._stats_panel.set_lines(["No statistics for the current plot."])
            self._push_plotly_figure(fig)
            self.parent_app.status_label.setText(
                "Line plot: no points for current axis/range/scope."
            )
            return
        ordered = sorted(zip(fx, fy, foids), key=lambda t: t[0])
        fx, fy, foids = [list(c) for c in zip(*ordered)]
        self._plotted_oids = list(foids)
        self._selected_point_indices = {
            i for i in self._selected_point_indices if 0 <= i < len(self._plotted_oids)
        }
        selected_points = (
            sorted(self._selected_point_indices) if self._selected_point_indices else []
        )
        marker = self._scatter_marker_for_oids(foids, point_size=5)
        fig = go.Figure()
        fig.add_trace(
            go.Scatter(
                **self._attach_point_hover(
                    {
                        "x": fx,
                        "y": fy,
                        "mode": "lines+markers",
                        "line": {"color": "#2a74d6", "width": 1.5},
                        "marker": marker,
                        "showlegend": False,
                        "selectedpoints": selected_points if selected_points else None,
                        "selected": {"marker": {"size": 9, "color": "#d62828", "opacity": 1.0}},
                        "unselected": {"marker": {"opacity": 0.35}},
                    },
                    foids,
                )
            )
        )
        fig.update_layout(
            xaxis={"title": xname, **self._plotly_axis_range(xmin, xmax, fx)},
            yaxis={"title": yname, **self._plotly_axis_range(ymin, ymax, fy)},
            dragmode="lasso",
            margin={"l": 50, "r": 20, "t": 20, "b": 45},
        )
        fit_summary = self._add_xy_fit_trace(fig, fx, fy)
        self._present_analysis_dialog(
            summarize_xy(fx, fy, x_label=xname, y_label=yname),
            fit_summary,
        )
        self._attach_size_legend_for_oids(fig, foids)
        self._push_plotly_figure(fig)
        self.parent_app.status_label.setText(f"Line plot: {len(fx):,} point(s).")

    def _plot_distribution(self, kind: str) -> None:
        self._clear_heatmap_state()
        vals, oids, xname = self._collect_histogram()
        if not xname:
            self._render_empty_plot(self._empty_plot_hint())
            return
        xmin = self._parse_edit_float(self.xmin)
        xmax = self._parse_edit_float(self.xmax)
        label = "Box plot" if kind == PLOT_TYPE_BOX else "Violin"
        if not vals:
            self._plotted_oids = []
            self._selected_point_indices = set()
            fig = go.Figure()
            fig.update_layout(
                yaxis={"title": xname, **self._plotly_axis_range(xmin, xmax, [])},
                margin={"l": 50, "r": 20, "t": 20, "b": 45},
            )
            self._stats_panel.set_lines(["No statistics for the current plot."])
            self._push_plotly_figure(fig)
            self.parent_app.status_label.setText(
                f"{label}: no values for current column/range/scope."
            )
            return
        self._plotted_oids = list(oids)
        self._selected_point_indices = set()
        trace_kwargs: dict = {
            "y": vals,
            "name": xname,
            "marker": {"color": "#2a74d6", "line": {"color": "#1d3557", "width": 1}},
        }
        if kind == PLOT_TYPE_BOX:
            trace_kwargs["boxmean"] = "sd"
            trace = go.Box(**trace_kwargs)
        else:
            trace = go.Violin(**trace_kwargs)
        fig = go.Figure(data=[trace])
        fig.update_layout(
            yaxis={"title": xname, **self._plotly_axis_range(xmin, xmax, vals)},
            showlegend=False,
            margin={"l": 50, "r": 20, "t": 20, "b": 45},
        )
        self._present_analysis_dialog(summarize_univariate(vals, label=xname), None)
        self._push_plotly_figure(fig)
        self.parent_app.status_label.setText(f"{label}: {len(vals):,} value(s) in {xname!r}.")

    def _plot_histogram(self) -> None:
        self._clear_heatmap_state()
        vals, oids, xname = self._collect_histogram()
        if not xname:
            self._render_empty_plot("Choose a column for the histogram.")
            return
        xmin = self._parse_edit_float(self.xmin)
        xmax = self._parse_edit_float(self.xmax)
        bin_width = self._parse_edit_float(self.hist_bin_width)
        if not vals:
            self._hist_edges = []
            self._hist_vals = []
            self._hist_oids = []
            self._plotted_oids = []
            self._selected_point_indices = set()
            fig = go.Figure()
            fig.update_layout(
                xaxis={"title": xname, **self._plotly_axis_range(xmin, xmax, [])},
                yaxis={"title": "Count"},
                margin={"l": 50, "r": 20, "t": 20, "b": 45},
            )
            self._stats_panel.set_lines(["No statistics for the current plot."])
            self._push_plotly_figure(fig)
            self.parent_app.status_label.setText(
                "Histogram: no values for current column/range/scope."
            )
            return
        self._hist_vals = list(vals)
        self._hist_oids = list(oids)
        self._plotted_oids = list(oids)
        self._selected_point_indices = set()
        edges, width = compute_histogram_bin_edges(vals, bin_width=bin_width, xmin=xmin, xmax=xmax)
        self._hist_edges = edges
        hist_kwargs: dict = {
            "x": vals,
            "xbins": {"start": edges[0], "end": edges[-1], "size": width},
        }
        fig = go.Figure(
            data=[
                go.Histogram(
                    **hist_kwargs,
                    marker={"color": "#2a74d6", "line": {"color": "white", "width": 0.5}},
                    showlegend=False,
                )
            ]
        )
        fig.update_layout(
            xaxis={"title": xname, **self._plotly_axis_range(xmin, xmax, vals)},
            yaxis={"title": "Count"},
            bargap=0.02,
            margin={"l": 50, "r": 20, "t": 20, "b": 45},
        )
        fit_summary = self._add_histogram_fit_trace(fig, vals, edges, bin_width=width)
        self._present_analysis_dialog(summarize_univariate(vals, label=xname), fit_summary)
        self._push_plotly_figure(fig)
        self.parent_app.status_label.setText(f"Histogram: {len(vals):,} value(s) in {xname!r}.")

    def _radar_scope_allowed_oids(self) -> set[int] | None:
        if self.parent_app is None:
            return None
        n_sel = len(self.parent_app._selected_logical_rows())
        if n_sel > 0 and self.only_selected_cb.isChecked():
            return self.parent_app._selected_oids_set()
        return None

    def _plot_radar(self) -> None:
        self._clear_heatmap_state()
        self._hist_edges = []
        self._hist_vals = []
        self._hist_oids = []
        columns = self._selected_radar_spoke_columns()
        if len(columns) < MIN_RADAR_VARIABLES:
            self._radar_oids = []
            self._plotted_oids = []
            self._selected_point_indices = set()
            self._render_empty_plot(self._empty_plot_hint())
            return
        if self.parent_app is None:
            return

        row_indices = list(self._plot_source_row_indices())
        oids, raw_rows = collect_radar_rows(
            self.parent_app._table_model,
            list(self.parent_app.headers),
            columns,
            allowed_oids=self._radar_scope_allowed_oids(),
            row_indices=row_indices,
        )
        rows = [[float(v) for v in row] for row in raw_rows]
        if not rows:
            self._radar_oids = []
            self._plotted_oids = []
            self._selected_point_indices = set()
            self._stats_panel.set_lines(["No statistics for the current plot."])
            self._render_empty_plot("No rows with numeric values in all selected spokes.")
            self.parent_app.status_label.setText(
                "Radar Plot: no rows with numeric values in all selected spokes."
            )
            return

        norm_mins, norm_maxs = compute_radar_normalization_bounds(rows)
        display_oids, invalid_ids = self._selected_radar_entry_oids()
        if invalid_ids:
            self.parent_app.status_label.setText(
                "Radar Plot: unknown row ID(s): " + ", ".join(invalid_ids)
            )
        total_in_scope = len(oids)
        if display_oids is not None:
            oids, rows = filter_radar_rows_by_oids(oids, rows, display_oids)
            if not rows:
                self._radar_oids = []
                self._plotted_oids = []
                self._selected_point_indices = set()
                self._stats_panel.set_lines(["No statistics for the current plot."])
                self._render_empty_plot("Entered row IDs have no data for the current spokes.")
                if not invalid_ids:
                    self.parent_app.status_label.setText(
                        "Radar Plot: entered row IDs have no data for the current spokes."
                    )
                return
        elif total_in_scope > MAX_RADAR_TRACES:
            oids = oids[:MAX_RADAR_TRACES]
            rows = rows[:MAX_RADAR_TRACES]

        self._radar_oids = list(oids)
        self._plotted_oids = list(oids)
        self._selected_point_indices = set()
        fig = build_radar_figure(
            columns,
            oids,
            rows,
            norm_mins=norm_mins,
            norm_maxs=norm_maxs,
        )
        self._present_analysis_panel(summarize_radar(columns, rows, oids=oids), None)
        self._push_plotly_figure(fig)
        msg = f"Radar Plot: {len(rows):,} row(s), {len(columns)} spoke(s) (normalized)."
        if display_oids is None and total_in_scope > len(rows):
            msg = (
                f"Radar Plot: showing first {MAX_RADAR_TRACES:,} of "
                f"{total_in_scope:,} rows (normalized)."
            )
        if not invalid_ids:
            self.parent_app.status_label.setText(msg)

    def _on_radar_trace_clicked(self, trace_index: int) -> None:
        if trace_index < 0 or trace_index >= len(self._radar_oids):
            return
        if self.parent_app is None:
            return
        oid = int(self._radar_oids[trace_index])
        row = self.parent_app.logical_row_for_oid(oid)
        if row < 0:
            return
        apply_table_selection_for_source_rows(self.parent_app, [row])
        self.parent_app.status_label.setText(f"Radar Plot: selected row {row + 1:,} (OID {oid}).")

    def _clear_heatmap_state(self) -> None:
        self._heat_x = []
        self._heat_y = []
        self._heat_oids = []
        self._heat_x_edges = []
        self._heat_y_edges = []

    def _plot_heatmap(self) -> None:
        self._hist_edges = []
        self._hist_vals = []
        self._hist_oids = []
        self._clear_heatmap_state()
        fx, fy, _fz, foids, xname, yname, _zname = self._collect_points()
        if not xname or not yname:
            self._render_empty_plot(self._empty_plot_hint())
            return
        xmin = self._parse_edit_float(self.xmin)
        xmax = self._parse_edit_float(self.xmax)
        ymin = self._parse_edit_float(self.ymin)
        ymax = self._parse_edit_float(self.ymax)
        x_bin_width = self._parse_edit_float(self.hist_bin_width)
        y_bin_width = self._parse_edit_float(self.heatmap_y_bin_width)

        if not fx:
            self._plotted_oids = []
            self._selected_point_indices = set()
            fig = go.Figure()
            fig.update_layout(
                xaxis={"title": xname, **self._plotly_axis_range(xmin, xmax, [])},
                yaxis={"title": yname, **self._plotly_axis_range(ymin, ymax, [])},
                margin={"l": 50, "r": 20, "t": 20, "b": 45},
            )
            self._stats_panel.set_lines(["No statistics for the current plot."])
            self._push_plotly_figure(fig)
            self.parent_app.status_label.setText("Heatmap: no points for current axis/range/scope.")
            return

        x_edges, x_width = compute_histogram_bin_edges(
            fx, bin_width=x_bin_width, xmin=xmin, xmax=xmax
        )
        y_edges, y_width = compute_histogram_bin_edges(
            fy, bin_width=y_bin_width, xmin=ymin, xmax=ymax
        )
        colorscale = resolve_plot_colorscale(self.colorscale_combo.currentText())
        fig, counts = build_heatmap_figure(
            fx,
            fy,
            x_label=xname,
            y_label=yname,
            x_edges=x_edges,
            y_edges=y_edges,
            colorscale=colorscale,
        )
        self._heat_x = list(fx)
        self._heat_y = list(fy)
        self._heat_oids = list(foids)
        self._heat_x_edges = list(x_edges)
        self._heat_y_edges = list(y_edges)
        self._plotted_oids = list(foids)
        self._selected_point_indices = set()
        stats = summarize_heatmap(
            fx,
            fy,
            x_label=xname,
            y_label=yname,
            x_edges=x_edges,
            y_edges=y_edges,
            counts=counts,
        )
        self._present_analysis_dialog(stats, None)
        self._push_plotly_figure(fig)
        self.parent_app.status_label.setText(
            f"Heatmap: {len(fx):,} point(s), {len(x_edges) - 1}×{len(y_edges) - 1} bins."
        )

    def _on_heatmap_cell_clicked(self, x_value: float, y_value: float) -> None:
        oids = oids_in_heatmap_cell(
            self._heat_x,
            self._heat_y,
            self._heat_oids,
            self._heat_x_edges,
            self._heat_y_edges,
            x_value,
            y_value,
        )
        if not oids:
            return
        self._arm_ignore_plot_clear()
        self._select_rows_for_oids(oids)
        self.parent_app.status_label.setText(
            f"Heatmap: selected {len(oids):,} row(s) in the clicked cell."
        )

    def _on_histogram_points_selected(self, indices_json: str, *, additive: bool = False) -> None:
        try:
            raw = json.loads(indices_json)
        except json.JSONDecodeError:
            return
        if not isinstance(raw, list):
            return
        indices = [int(x) for x in raw if isinstance(x, (int, float)) and not isinstance(x, bool)]
        oids = oids_at_histogram_point_indices(self._hist_oids, indices)
        if not oids:
            return
        if additive:
            oids = sorted({int(x) for x in oids} | selected_oids_for_plot(self.parent_app))
        self._arm_ignore_plot_clear()
        self._select_rows_for_oids(oids)
        self.parent_app.status_label.setText(
            f"Histogram: selected {len(oids):,} row(s) in the clicked bar."
        )

    def _on_histogram_bin_clicked(self, bin_index: int) -> None:
        oids = oids_in_histogram_bin(self._hist_vals, self._hist_oids, self._hist_edges, bin_index)
        if not oids:
            return
        self._arm_ignore_plot_clear()
        self._select_rows_for_oids(oids)
        self.parent_app.status_label.setText(
            f"Histogram: selected {len(oids):,} row(s) in bin {bin_index + 1}."
        )

    def _select_rows_for_oids(self, oids: list[int]) -> None:
        source_rows: list[int] = []
        for oid in oids:
            row = self.parent_app.logical_row_for_oid(int(oid))
            if row >= 0:
                source_rows.append(int(row))
        if not source_rows:
            return
        self._select_rows_for_source_rows(source_rows)

    def _select_rows_for_point_indices(self, point_indices: list[int]) -> None:
        source_rows = source_rows_for_point_indices(
            self.parent_app, self._plotted_oids, point_indices
        )
        # Do not scroll the table — keeps docked-plot clicks from flashing scrollbars.
        apply_table_selection_for_source_rows(
            self.parent_app,
            source_rows,
            scroll=False,
            debounce=len(source_rows) > 1,
        )

    def _select_rows_for_source_rows(self, source_rows: list[int]) -> None:
        apply_table_selection_for_source_rows(
            self.parent_app,
            source_rows,
            scroll=False,
            debounce=len(source_rows) > 1,
        )

    def _on_plot_point_clicked(self, point_index: int, *, additive: bool = False) -> None:
        if point_index < 0:
            return
        idx = int(point_index)
        if additive:
            self._selected_point_indices.add(idx)
        else:
            self._selected_point_indices = {idx}
        self._arm_ignore_plot_clear()
        self._select_rows_for_point_indices(sorted(self._selected_point_indices))
        self._sync_plot_selection_visual()
        n = len(self._selected_point_indices)
        if n > 1:
            self.parent_app.status_label.setText(f"Plot: selected {n:,} point(s).")
        elif 0 <= idx < len(self._plotted_oids):
            oid = int(self._plotted_oids[idx])
            row = self.parent_app.logical_row_for_oid(oid)
            if row >= 0:
                self.parent_app.status_label.setText(f"Plot: selected row {row + 1:,} (OID {oid}).")

    def _on_plot_points_selected(self, points_json: str, *, additive: bool = False) -> None:
        try:
            raw = json.loads(points_json or "[]")
            idxs = [int(x) for x in raw if isinstance(x, (int, float))]
        except Exception:
            idxs = []
        if not idxs:
            if additive:
                return
            if time.monotonic() < self._ignore_plot_clear_until:
                return
            self._clear_plot_table_selection()
            self.parent_app.status_label.setText("Plot: selection cleared.")
            return
        new_idxs = {i for i in idxs if 0 <= i < len(self._plotted_oids)}
        if not new_idxs:
            return
        if additive:
            self._selected_point_indices |= new_idxs
        else:
            self._selected_point_indices = new_idxs
        self._arm_ignore_plot_clear()
        sel_sorted = sorted(self._selected_point_indices)
        self._select_rows_for_point_indices(sel_sorted)
        self.parent_app.status_label.setText(f"Plot: selected {len(sel_sorted):,} point(s).")
        self._sync_plot_selection_visual()

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

    def collect_session_state(self) -> dict:
        """JSON-safe Plotter settings for ``.cms`` session files."""
        spokes = [c.currentText() for c in getattr(self, "spoke_combos", None) or []]
        entries = [e.text() for e in getattr(self, "entry_edits", None) or []]
        fit_key = self.fit_combo.currentData()
        return {
            "kind": PLOT_SESSION_KIND,
            "plot_type": self._current_plot_type(),
            "x": self.x_combo.currentText(),
            "y": self.y_combo.currentText(),
            "z": self.z_combo.currentText(),
            "xmin": self.xmin.text(),
            "xmax": self.xmax.text(),
            "ymin": self.ymin.text(),
            "ymax": self.ymax.text(),
            "zmin": self.zmin.text(),
            "zmax": self.zmax.text(),
            "hist_bin_width": self.hist_bin_width.text(),
            "heatmap_y_bin_width": self.heatmap_y_bin_width.text(),
            "color": self.color_combo.currentText(),
            "colorscale": self.colorscale_combo.currentText(),
            "color_min": self.color_range.color_min.text(),
            "color_max": self.color_range.color_max.text(),
            "size": self.size_combo.currentText(),
            "size_min": float(self.size_range.size_min.value()),
            "size_max": float(self.size_range.size_max.value()),
            "fit": fit_key if isinstance(fit_key, str) else "",
            "show_fit_formula": bool(self.show_fit_formula_cb.isChecked()),
            "fit_trunc_lower": self.fit_trunc_lower.text(),
            "fit_trunc_upper": self.fit_trunc_upper.text(),
            "plot_title": self.plot_title_edit.text(),
            "xaxis_title": self.xaxis_title_edit.text(),
            "yaxis_title": self.yaxis_title_edit.text(),
            "zaxis_title": self.zaxis_title_edit.text(),
            "only_selected": bool(self.only_selected_cb.isChecked()),
            **self._hover_controls.collect_state(),
            "radar_spokes": spokes,
            "radar_entries": entries,
        }

    @staticmethod
    def _set_combo_text(combo: QComboBox, text: str | None) -> None:
        if not text:
            return
        idx = combo.findText(str(text))
        if idx >= 0:
            combo.setCurrentIndex(idx)

    def apply_session_state(self, state: dict | None) -> None:
        """Restore Plotter controls from ``collect_session_state``."""
        if not isinstance(state, dict):
            return
        ptype = state.get("plot_type")
        self.plot_type_combo.blockSignals(True)
        self.x_combo.blockSignals(True)
        self.y_combo.blockSignals(True)
        self.z_combo.blockSignals(True)
        try:
            if isinstance(ptype, str):
                idx = self.plot_type_combo.findData(ptype)
                if idx >= 0:
                    self.plot_type_combo.setCurrentIndex(idx)
            self._set_combo_text(self.x_combo, state.get("x"))
            self._set_combo_text(self.y_combo, state.get("y"))
            self._set_combo_text(self.z_combo, state.get("z"))
        finally:
            self.plot_type_combo.blockSignals(False)
            self.x_combo.blockSignals(False)
            self.y_combo.blockSignals(False)
            self.z_combo.blockSignals(False)
        self._prev_range_axis = {
            "x": self.x_combo.currentText(),
            "y": self._combo_axis_name(self.y_combo) or "",
            "z": self._combo_axis_name(self.z_combo) or "",
        }
        for edit, key in (
            (self.xmin, "xmin"),
            (self.xmax, "xmax"),
            (self.ymin, "ymin"),
            (self.ymax, "ymax"),
            (self.zmin, "zmin"),
            (self.zmax, "zmax"),
            (self.hist_bin_width, "hist_bin_width"),
            (self.heatmap_y_bin_width, "heatmap_y_bin_width"),
            (self.plot_title_edit, "plot_title"),
            (self.xaxis_title_edit, "xaxis_title"),
            (self.yaxis_title_edit, "yaxis_title"),
            (self.zaxis_title_edit, "zaxis_title"),
            (self.fit_trunc_lower, "fit_trunc_lower"),
            (self.fit_trunc_upper, "fit_trunc_upper"),
        ):
            val = state.get(key)
            if isinstance(val, str):
                edit.setText(val)
        self._on_plot_type_change()
        self._set_combo_text(self.color_combo, state.get("color"))
        self._set_combo_text(self.colorscale_combo, state.get("colorscale"))
        self._set_combo_text(self.size_combo, state.get("size"))
        cmin, cmax = state.get("color_min"), state.get("color_max")
        if isinstance(cmin, str):
            self.color_range.color_min.setText(cmin)
        if isinstance(cmax, str):
            self.color_range.color_max.setText(cmax)
        try:
            if state.get("size_min") is not None:
                self.size_range.size_min.setValue(float(state["size_min"]))
            if state.get("size_max") is not None:
                self.size_range.size_max.setValue(float(state["size_max"]))
        except (TypeError, ValueError):
            pass
        fit_key = state.get("fit")
        if isinstance(fit_key, str) and fit_key:
            fidx = self.fit_combo.findData(fit_key)
            if fidx >= 0:
                self.fit_combo.setCurrentIndex(fidx)
        if "show_fit_formula" in state:
            self.show_fit_formula_cb.setChecked(bool(state.get("show_fit_formula")))
        if "only_selected" in state:
            self.only_selected_cb.setChecked(bool(state.get("only_selected")))
        self._hover_controls.apply_state(state)
        spokes = state.get("radar_spokes")
        if isinstance(spokes, list):
            for combo, name in zip(self.spoke_combos, spokes, strict=False):
                self._set_combo_text(combo, str(name) if name else SPOKE_NONE)
        entries = state.get("radar_entries")
        if isinstance(entries, list):
            for edit, text in zip(self.entry_edits, entries, strict=False):
                edit.setText(str(text) if text is not None else "")
        self._update_color_controls()
        self._schedule_plot()

    @classmethod
    def from_session_state(cls, parent_app, state: dict | None) -> "PlotWidget":
        widget = cls(parent_app)
        widget.apply_session_state(state)
        return widget


class PlotDialog(QDialog):
    """Floating window hosting a :class:`PlotWidget`."""

    def __init__(self, parent_app=None, plot_widget: PlotWidget | None = None):
        super().__init__(parent_app)
        self.parent_app = parent_app
        self.setWindowTitle("Plot Data")
        self.resize(960, 900)

        self._plot_widget = plot_widget if plot_widget is not None else PlotWidget(parent_app)
        self.only_selected_cb = self._plot_widget.only_selected_cb
        self._only_selected_scope_prefix = self._plot_widget._only_selected_scope_prefix

        root = QVBoxLayout(self)
        root.addWidget(self._plot_widget, 1)
        self._plot_widget._sync_footer_chrome()

        self._configure_floating_plot_dialog()

    def _configure_floating_plot_dialog(self) -> None:
        self.setModal(False)
        self.setWindowModality(Qt.NonModal)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self._force_close = False
        for btn in self.findChildren(QPushButton):
            btn.setAutoDefault(False)
            btn.setDefault(False)

        esc = QShortcut(QKeySequence(Qt.Key_Escape), self)
        esc.setContext(Qt.WidgetWithChildrenShortcut)
        esc.activated.connect(self.close)
        make_window_minimizable(self)

    def keyPressEvent(self, event) -> None:  # noqa: N802 — Qt API name
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            fw = self.focusWidget()
            if fw is not None and isinstance(fw, (QLineEdit, QComboBox, QAbstractSpinBox)):
                event.accept()
                return
        super().keyPressEvent(event)

    def closeEvent(self, event):
        handle_floating_plot_close_event(self, event)
