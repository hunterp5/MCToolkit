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

"""PCA, t-SNE, UMAP, and SOM visualization dialogs (Data menu)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pandas as pd
from PyQt5.QtCore import QEvent, Qt, QTimer
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QDoubleSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from rdkit import Chem

from ..dockable_plot import (
    PlotTitlesControls,
    apply_plot_chrome_glyphs,
    handle_floating_plot_close_event,
    hide_plot_options_dialog,
    make_add_to_main_button,
    make_clear_selection_button,
    make_close_plot_button,
    make_plot_options_button,
    make_plot_options_dialog,
    make_send_window_button,
    request_close_plot_widget,
    show_plot_options_dialog,
)
from ...dimensionality_reduction import (
    DimensionReductionResult,
    is_fingerprint_bitcount_column,
    subset_dimension_reduction_result,
)
from ...workers import SIMILARITY_FP_TYPE_LABELS
from ...workers.dimensionality_reduction import DimensionReductionSignals, DimensionReductionWorker
from .data_analysis import numeric_subset, table_to_dataframe
from ...plot_color import (
    PLOT_COLORSCALE_CHOICES,
    color_values_are_numeric,
    normalize_color_column,
    normalize_size_column,
    resolve_plot_colorscale,
)
from ..plot_color_range_controls import PlotColorRangeControls
from ..plot_on_hover_controls import PlotOnHoverControls
from ..plot_size_controls import PlotSizeRangeControls
from ..dimred_plot import build_dimension_reduction_figure, dimension_reduction_result_with_color
from ..plotly_interactive_view import PlotlyInteractiveView
from ..plot_table_sync import visible_oids_for_plot
from ..qt_widget_utils import apply_monospace_to_text_edit, make_window_minimizable
from .scope import selection_scope_checked

if TYPE_CHECKING:
    from ..main_window import ChemicalTableApp

try:
    from PyQt5.QtWebEngineWidgets import QWebEngineView  # noqa: F401

    _HAS_WEB = True
except ImportError:
    _HAS_WEB = False

_FP_NONE_LABEL = "None"


class DimensionReductionPanel(QWidget):
    """PCA / t-SNE / UMAP / SOM panel; owns Send/Close when docked so all actions share one footer."""

    DIMRED_SESSION_KIND = "dimension_reduction"
    owns_docked_plot_actions = True

    def __init__(self, parent: ChemicalTableApp | None, *, window_title: str, method: str):
        super().__init__(None)
        self.parent_app = parent
        self._method = method
        self._window_title = window_title
        n_sel = len(parent._selected_logical_rows()) if parent is not None else 0
        self._have_selection = n_sel > 0
        self._job_running = False
        self._last_result: DimensionReductionResult | None = None

        root = QVBoxLayout(self)
        # Top inset matches spacing: same toolbar→plot gap when floating or docked.
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(4)

        plot_host = QWidget()
        plot_ly = QVBoxLayout(plot_host)
        plot_ly.setContentsMargins(0, 0, 0, 0)
        if _HAS_WEB and parent is not None:
            self._plot_view = PlotlyInteractiveView(parent, plot_host)
            self._plot_view.setMinimumHeight(420)
            plot_ly.addWidget(self._plot_view, 1)
            self._plot_placeholder = None
        else:
            self._plot_view = None
            self._plot_placeholder = QLabel(
                "Install PyQtWebEngine to show the interactive plot in this window."
            )
            self._plot_placeholder.setWordWrap(True)
            self._plot_placeholder.setAlignment(Qt.AlignCenter)
            plot_ly.addWidget(self._plot_placeholder, 1)
        root.addWidget(plot_host, 1)

        self._opts_panel = QWidget()
        opts = QVBoxLayout(self._opts_panel)
        opts.setContentsMargins(0, 0, 0, 0)
        opts.setSpacing(6)

        self._titles = PlotTitlesControls(self._opts_panel)
        self._titles.changed.connect(self._on_titles_changed)
        opts.addWidget(self._titles)

        features_opts_row = QHBoxLayout()
        features_opts_row.setSpacing(8)

        src_grp = QGroupBox("Features")
        src_ly = QVBoxLayout(src_grp)
        self.column_list = QListWidget()
        self.column_list.setMinimumWidth(220)
        self.column_list.setMaximumHeight(140)
        src_ly.addWidget(self.column_list)

        fp_row = QHBoxLayout()
        fp_row.addWidget(QLabel("Fingerprint:"))
        self.fp_combo = QComboBox()
        self.fp_combo.addItem(_FP_NONE_LABEL)
        self.fp_combo.addItems(SIMILARITY_FP_TYPE_LABELS)
        self.fp_combo.setToolTip(
            "None: numeric columns only. Otherwise concatenate a 2D fingerprint bit vector."
        )
        self.fp_combo.currentIndexChanged.connect(self._on_fp_selection_changed)
        fp_row.addWidget(self.fp_combo, 1)
        src_ly.addLayout(fp_row)
        struct_row = QHBoxLayout()
        struct_row.addWidget(QLabel("Structure from:"))
        self.struct_src_combo = QComboBox()
        struct_row.addWidget(self.struct_src_combo, 1)
        src_ly.addLayout(struct_row)
        features_opts_row.addWidget(src_grp, 1)

        method_opts = QGroupBox("Options")
        self._opts_form = QFormLayout(method_opts)
        features_opts_row.addWidget(method_opts, 1)
        opts.addLayout(features_opts_row)

        self.only_selected_cb = QCheckBox("Selected Rows Only")
        self._only_selected_scope_prefix = "Selected Rows Only"
        if self._have_selection:
            self.only_selected_cb.setText(f"{self._only_selected_scope_prefix} ({n_sel} row(s))")
        else:
            self.only_selected_cb.setEnabled(False)
        self.only_selected_cb.stateChanged.connect(self._reload_columns)
        self._opts_form.addRow(self.only_selected_cb)

        self._build_method_options(self._opts_form)
        self.standardize_cb = QCheckBox("Standardize features (zero mean, unit variance)")
        self.standardize_cb.setChecked(True)
        self._opts_form.addRow(self.standardize_cb)

        color_row = QHBoxLayout()
        color_row.setSpacing(6)
        self._color_by_label = QLabel("Color by:")
        color_row.addWidget(self._color_by_label)
        self.color_combo = QComboBox()
        self.color_combo.setMinimumWidth(120)
        self.color_combo.currentIndexChanged.connect(self._on_color_column_changed)
        color_row.addWidget(self.color_combo, 1)
        self._spectrum_label = QLabel("Spectrum:")
        color_row.addWidget(self._spectrum_label)
        self.colorscale_combo = QComboBox()
        self.colorscale_combo.setMinimumWidth(100)
        self.colorscale_combo.addItems(PLOT_COLORSCALE_CHOICES)
        self.colorscale_combo.setToolTip("Continuous colorscale for numeric Color by columns.")
        self.colorscale_combo.currentIndexChanged.connect(self._on_color_range_or_scale_changed)
        color_row.addWidget(self.colorscale_combo)
        self.color_range = PlotColorRangeControls()
        self.color_range.connect_changed(self._on_color_range_changed)
        color_row.addWidget(self.color_range)
        opts.addLayout(color_row)

        size_row = QHBoxLayout()
        size_row.setSpacing(6)
        self._size_by_label = QLabel("Size by:")
        size_row.addWidget(self._size_by_label)
        self.size_combo = QComboBox()
        self.size_combo.setMinimumWidth(120)
        self.size_combo.setToolTip("Size points by a table column (numeric or categorical).")
        self.size_combo.currentIndexChanged.connect(self._on_size_column_changed)
        size_row.addWidget(self.size_combo, 1)
        self.size_range = PlotSizeRangeControls()
        self.size_range.connect_changed(self._on_size_range_changed)
        size_row.addWidget(self.size_range)
        opts.addLayout(size_row)

        self._hover_controls = PlotOnHoverControls(self._opts_panel)
        self._hover_controls.changed.connect(self._on_hover_options_changed)
        self._hover_controls.persist_changed.connect(self._on_hover_options_changed)
        opts.addWidget(self._hover_controls)

        run_row = QHBoxLayout()
        run_row.setContentsMargins(0, 10, 0, 6)
        run_row.addStretch()
        self.run_btn = QPushButton(self._run_button_label())
        self.run_btn.clicked.connect(self._on_run)
        self.run_btn.setMinimumWidth(160)
        self.run_btn.setStyleSheet("QPushButton { padding: 8px 28px; }")
        run_row.addWidget(self.run_btn)
        run_row.addStretch()
        opts.addLayout(run_row)

        self.summary_text = QTextEdit()
        self.summary_text.setReadOnly(True)
        self.summary_text.setMaximumHeight(100)
        apply_monospace_to_text_edit(self.summary_text)
        opts.addWidget(QLabel("Results"))
        opts.addWidget(self.summary_text)

        self._opts_dialog = make_plot_options_dialog(
            self,
            self._opts_panel,
            min_width=640,
            min_height=480,
        )

        self._footer_bar = QWidget(self)
        self._footer_bar.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        foot = QHBoxLayout(self._footer_bar)
        foot.setContentsMargins(0, 0, 0, 0)
        foot.setSpacing(4)
        self._opts_btn = make_plot_options_button(
            self,
            tooltip="Configure features, method parameters, color, and On Hover options.",
        )
        self._opts_btn.clicked.connect(self._open_plot_options)
        foot.addWidget(self._opts_btn)
        self._clear_sel_btn = make_clear_selection_button(self)
        self._clear_sel_btn.clicked.connect(self._clear_selection)
        foot.addWidget(self._clear_sel_btn)
        foot.addStretch(1)
        self._add_to_main_btn = make_add_to_main_button(
            self,
            tooltip="Dock this plot beside the compound table.",
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

        host = parent if parent is not None else self
        self._signals = DimensionReductionSignals(host)
        self._signals.finished.connect(self._on_finished, Qt.QueuedConnection)
        self._signals.failed.connect(self._on_failed, Qt.QueuedConnection)

        self._refresh_structure_sources()
        self._reload_columns()
        self._reload_hover_columns()
        self._on_fp_selection_changed()
        self._update_spectrum_controls()
        self._update_size_controls()
        self._sync_hover_options_to_plot_view()
        self._sync_footer_chrome()
        self.setMinimumWidth(self.embedded_minimum_width())

    def _open_plot_options(self) -> None:
        """Open the feature/method configuration dialog."""
        show_plot_options_dialog(self._opts_dialog)

    def _clear_selection(self) -> None:
        """Clear table and plot point selection."""
        if self._plot_view is not None:
            self._plot_view.clear_table_selection(update_plot=True)
        elif self.parent_app is not None:
            self.parent_app.clear_table_selection()

    def _add_to_main_window(self) -> None:
        """Dock this panel beside the compound table (from a floating dialog)."""
        if self.parent_app is None:
            return
        dlg = self.window()
        teardown = getattr(dlg, "_scope_sync_disconnect", None)
        if callable(teardown):
            teardown()
        if not self.parent_app.dock_plot_widget(self):
            return
        if isinstance(dlg, DimensionReductionDialog):
            dlg._panel = None
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
        from ..dockable_plot import sync_docked_footer_bar

        apply_plot_chrome_glyphs(self)
        floating = isinstance(self.window(), DimensionReductionDialog)
        docked = self._is_docked_in_main_window()
        self._add_to_main_btn.setVisible(floating)
        self._send_window_btn.setVisible(docked)
        self._close_plot_btn.setVisible(docked)
        sync_docked_footer_bar(self, docked=docked)

    def event(self, event):  # noqa: N802 — Qt API name
        if event.type() == QEvent.ParentChange:
            self._sync_footer_chrome()
        return super().event(event)

    def embedded_minimum_width(self) -> int:
        """Minimum dock width for the figure (options open in a separate dialog)."""
        return 420

    def embedded_preferred_width(self) -> int:
        return max(self.embedded_minimum_width(), 640)

    def create_floating_dialog(self, parent_app: ChemicalTableApp) -> QDialog:
        """Re-open this panel in a floating window after undocking from the main table."""
        return _DIMRED_FLOATING_DIALOGS[self._method](parent_app, panel=self)

    def _run_button_label(self) -> str:
        labels = {
            "pca": "Run PCA",
            "tsne": "Run t-SNE",
            "umap": "Run UMAP",
            "som": "Run SOM",
        }
        return labels.get(self._method, "Run")

    def _build_method_options(self, form: QFormLayout) -> None:
        raise NotImplementedError

    def _method_params(self) -> dict:
        raise NotImplementedError

    def _apply_method_params(self, params: dict | None) -> None:
        return None

    @staticmethod
    def _set_combo_text(combo: QComboBox, text: str | None) -> None:
        if not text:
            return
        idx = combo.findText(str(text))
        if idx >= 0:
            combo.setCurrentIndex(idx)

    def collect_session_state(self) -> dict:
        from ...dimensionality_reduction import result_to_dict

        state: dict = {
            "kind": self.DIMRED_SESSION_KIND,
            "method": self._method,
            "features": self._selected_feature_columns(),
            "use_fingerprints": self._use_fingerprints(),
            "fingerprint": self.fp_combo.currentText(),
            "struct_src": self.struct_src_combo.currentText(),
            "standardize": bool(self.standardize_cb.isChecked()),
            "only_selected": bool(self.only_selected_cb.isChecked()),
            "color": self.color_combo.currentText(),
            "colorscale": self.colorscale_combo.currentText(),
            "color_min": self.color_range.color_min.text(),
            "color_max": self.color_range.color_max.text(),
            "size": self.size_combo.currentText(),
            "size_min": float(self.size_range.size_min.value()),
            "size_max": float(self.size_range.size_max.value()),
            "method_params": dict(self._method_params()),
            **self._titles.title_overrides(),
            **self._hover_controls.collect_state(),
        }
        if self._last_result is not None:
            state["result"] = result_to_dict(self._last_result)
            state["summary"] = self.summary_text.toPlainText()
        return state

    def apply_session_state(self, state: dict | None) -> None:
        if not isinstance(state, dict):
            return
        self._reload_columns()
        features = set(state.get("features") or [])
        for i in range(self.column_list.count()):
            item = self.column_list.item(i)
            item.setCheckState(Qt.Checked if item.text() in features else Qt.Unchecked)
        self.fp_combo.blockSignals(True)
        self.struct_src_combo.blockSignals(True)
        self.color_combo.blockSignals(True)
        self.size_combo.blockSignals(True)
        try:
            self._set_combo_text(self.fp_combo, state.get("fingerprint"))
            self._set_combo_text(self.struct_src_combo, state.get("struct_src"))
            self._set_combo_text(self.color_combo, state.get("color"))
            self._set_combo_text(self.colorscale_combo, state.get("colorscale"))
            self._set_combo_text(self.size_combo, state.get("size"))
        finally:
            self.fp_combo.blockSignals(False)
            self.struct_src_combo.blockSignals(False)
            self.color_combo.blockSignals(False)
            self.size_combo.blockSignals(False)
        if "standardize" in state:
            self.standardize_cb.setChecked(bool(state.get("standardize")))
        if "only_selected" in state:
            self.only_selected_cb.setChecked(bool(state.get("only_selected")))
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
        for edit, key in (
            (self._titles.plot_title_edit, "plot_title"),
            (self._titles.xaxis_title_edit, "xaxis_title"),
            (self._titles.yaxis_title_edit, "yaxis_title"),
        ):
            val = state.get(key)
            if isinstance(val, str):
                edit.setText(val)
        self._hover_controls.apply_state(state)
        self._sync_hover_options_to_plot_view()
        params = state.get("method_params")
        if isinstance(params, dict):
            self._apply_method_params(params)
        self._on_fp_selection_changed()
        self._update_spectrum_controls()
        self._update_size_controls()
        raw_result = state.get("result")
        if isinstance(raw_result, dict):
            self._last_result = DimensionReductionResult(**raw_result)
            summary = state.get("summary")
            if isinstance(summary, str):
                self.summary_text.setPlainText(summary)
            elif isinstance(raw_result.get("summary"), str):
                self.summary_text.setPlainText(raw_result["summary"])
            QTimer.singleShot(0, self._refresh_plot_colors)

    @classmethod
    def from_session_state(cls, parent_app, state: dict | None) -> "DimensionReductionPanel":
        return dimension_reduction_panel_from_session(parent_app, state)

    def _use_fingerprints(self) -> bool:
        return self.fp_combo.currentText() != _FP_NONE_LABEL

    def _on_fp_selection_changed(self, *_args) -> None:
        use_fp = self._use_fingerprints()
        self.struct_src_combo.setEnabled(use_fp)
        if use_fp and not self._selected_feature_columns():
            self.standardize_cb.setToolTip(
                "When combined with fingerprints, only numeric columns are scaled; "
                "fingerprint bits are left unchanged."
            )
        else:
            self.standardize_cb.setToolTip("")

    def _refresh_structure_sources(self) -> None:
        self.struct_src_combo.clear()
        if self.parent_app is None:
            return
        self.struct_src_combo.addItems(self.parent_app.chemistry_tool_structure_sources())

    def _reload_columns(self) -> None:
        prev_color = self.color_combo.currentText()
        prev_size = self.size_combo.currentText()
        self.column_list.clear()
        self.color_combo.blockSignals(True)
        self.size_combo.blockSignals(True)
        try:
            self.color_combo.clear()
            self.color_combo.addItem("(none)")
            self.size_combo.clear()
            self.size_combo.addItem("(none)")
            if self.parent_app is None:
                return
            self._refresh_structure_sources()
            only_sel = selection_scope_checked(self)
            df, _rows = table_to_dataframe(
                self.parent_app, visible_only=False, only_selected=only_sel
            )
            num = numeric_subset(df, exclude_id=True)
            for col in num.columns:
                item = QListWidgetItem(col)
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(Qt.Unchecked)
                self.column_list.addItem(item)
            for col in df.columns:
                if col != "ID_HIDDEN":
                    self.color_combo.addItem(col)
                    self.size_combo.addItem(col)
            idx = self.color_combo.findText(prev_color)
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
        headers = list(getattr(self.parent_app, "headers", []) or []) if self.parent_app else []
        self._hover_controls.reload_columns(headers)
        self._sync_hover_options_to_plot_view()

    def _sync_hover_options_to_plot_view(self) -> None:
        self._hover_controls.apply_to_plot_view(getattr(self, "_plot_view", None))

    def _on_hover_options_changed(self) -> None:
        self._sync_hover_options_to_plot_view()

    def _column_values_for_oids(self, oids: list[int], column: str | None) -> list[Any] | None:
        if not column or column == "(none)" or self.parent_app is None:
            return None
        model = self.parent_app._table_model
        out: list[Any] = []
        for oid in oids:
            row = self.parent_app.logical_row_for_oid(int(oid))
            if row < 0:
                out.append(None)
                continue
            raw = model.value_for_header(row, column)
            out.append(raw if (raw or "").strip() else None)
        return out

    def _color_values_for_oids(self, oids: list[int], color_col: str | None) -> list[Any] | None:
        return self._column_values_for_oids(oids, color_col)

    def _size_values_for_oids(self, oids: list[int], size_col: str | None) -> list[Any] | None:
        return self._column_values_for_oids(oids, size_col)

    def _current_colorscale(self) -> str:
        return resolve_plot_colorscale(self.colorscale_combo.currentText())

    def _current_color_bounds(self) -> tuple[float | None, float | None]:
        return self.color_range.parse_bounds()

    def _current_size_bounds(self) -> tuple[float, float]:
        return self.size_range.parse_bounds()

    def _update_spectrum_controls(self) -> None:
        enabled = self.color_combo.currentText() != "(none)"
        self._spectrum_label.setEnabled(enabled)
        self.colorscale_combo.setEnabled(enabled)
        numeric = False
        if enabled and self._last_result is not None:
            color_col = self.color_combo.currentText()
            vals = self._color_values_for_oids(self._last_result.oids, color_col)
            numeric = color_values_are_numeric(vals)
        self.color_range.set_enabled(enabled and numeric)
        self._update_size_controls()

    def _update_size_controls(self) -> None:
        size_on = self.size_combo.currentText() != "(none)"
        self.size_range.set_enabled(size_on)

    def _on_color_range_changed(self) -> None:
        if self._last_result is None or self._job_running:
            return
        self._refresh_plot_colors()

    def _on_size_range_changed(self) -> None:
        if self._last_result is None or self._job_running:
            return
        self._refresh_plot_colors()

    def _on_color_column_changed(self, _index: int = 0) -> None:
        self._update_spectrum_controls()
        if self._last_result is None or self._job_running:
            return
        self._refresh_plot_colors()

    def _on_size_column_changed(self, _index: int = 0) -> None:
        self._update_size_controls()
        if self._last_result is None or self._job_running:
            return
        self._refresh_plot_colors()

    def _on_color_range_or_scale_changed(self, *_args) -> None:
        if self._last_result is None or self._job_running:
            return
        self._refresh_plot_colors()

    def _size_encoding_for_oids(
        self, oids: list[int]
    ) -> tuple[list[Any] | None, str | None, float, float]:
        size_col = self.size_combo.currentText()
        if size_col == "(none)":
            size_col = None
        size_vals = self._size_values_for_oids(oids, size_col)
        size_vals, size_label = normalize_size_column(size_vals, size_col)
        size_min_px, size_max_px = self._current_size_bounds()
        return size_vals, size_label, size_min_px, size_max_px

    def _on_titles_changed(self) -> None:
        self._refresh_plot_colors()

    def _schedule_plot(self) -> None:
        """Re-draw the last embedding using the currently visible table rows."""
        if self._last_result is None or self._job_running:
            return
        self._refresh_plot_colors()

    def _displayed_dimred_result(self) -> DimensionReductionResult | None:
        if self._last_result is None:
            return None
        return subset_dimension_reduction_result(
            self._last_result, visible_oids_for_plot(self.parent_app)
        )

    def _refresh_plot_colors(self) -> None:
        result = self._displayed_dimred_result()
        if result is None or self._plot_view is None or self._job_running:
            return
        if not result.oids:
            from plotly import graph_objects as go

            self._plot_view.push_figure(go.Figure(), [])
            return
        color_col = self.color_combo.currentText()
        if color_col == "(none)":
            color_col = None
        color_vals = self._color_values_for_oids(result.oids, color_col)
        color_vals, color_col = normalize_color_column(color_vals, color_col)
        updated = dimension_reduction_result_with_color(
            result,
            color_values=color_vals,
            color_label=color_col,
        )
        try:
            color_min, color_max = self._current_color_bounds()
            size_vals, size_label, size_min_px, size_max_px = self._size_encoding_for_oids(
                updated.oids
            )
            fig = build_dimension_reduction_figure(
                updated,
                colorscale=self._current_colorscale(),
                color_min=color_min,
                color_max=color_max,
                size_values=size_vals,
                size_label=size_label,
                size_min_px=size_min_px,
                size_max_px=size_max_px,
                **self._titles.title_overrides(),
            )
            self._plot_view.push_figure(fig, list(updated.oids))
        except Exception as exc:
            QMessageBox.warning(self, self._window_title, f"Plot failed: {exc}")

    def _selected_feature_columns(self) -> list[str]:
        cols: list[str] = []
        for i in range(self.column_list.count()):
            item = self.column_list.item(i)
            if item.checkState() == Qt.Checked:
                cols.append(item.text())
        return cols

    def _collect_table_mols(self, src: str, only_selected: bool) -> list[tuple[int, Chem.Mol]]:
        """Fingerprint mols for Run: all table rows; table filters only hide points at draw time."""
        app = self.parent_app
        assert app is not None
        return app.collect_scoped_table_mols(
            src,
            only_selected=only_selected,
            only_visible=False,
        )

    def _scoped_dataframe_and_oids(self) -> tuple[pd.DataFrame, list[int]]:
        """Feature rows for Run: full table (Selected Rows Only still applies)."""
        app = self.parent_app
        assert app is not None
        only_sel = selection_scope_checked(self)
        df, source_rows = table_to_dataframe(app, visible_only=False, only_selected=only_sel)
        oids: list[int] = []
        for r in source_rows:
            t0 = app._table_model.cell_text(r, 0)
            oids.append(int(t0) if t0.isdigit() else int(r))
        return df, oids

    def _on_run(self) -> None:
        if self._job_running or self.parent_app is None:
            return
        self._last_result = None
        use_fp = self._use_fingerprints()
        features = self._selected_feature_columns()
        only_sel = selection_scope_checked(self)
        if only_sel and not self.parent_app._selected_oids_set():
            QMessageBox.warning(
                self,
                self._window_title,
                "\u201cSelected Rows Only\u201d is checked but nothing is selected.",
            )
            return
        if not features and not use_fp:
            QMessageBox.warning(
                self,
                self._window_title,
                "Select at least one numeric column and/or choose a fingerprint type.",
            )
            return
        if (
            features
            and len(features) == 1
            and is_fingerprint_bitcount_column(features[0])
            and not use_fp
        ):
            QMessageBox.warning(
                self,
                self._window_title,
                f"The column “{features[0]}” stores only the number of on-bits, not the full "
                "fingerprint vector.\n\n"
                "Choose a fingerprint type other than None, or select multiple numeric columns.",
            )
            return
        color_col = self.color_combo.currentText()
        if color_col == "(none)":
            color_col = None

        # Close options and report status before any heavy prep so the UI stays responsive.
        hide_plot_options_dialog(self._opts_dialog)
        self._job_running = True
        self.run_btn.setEnabled(False)
        self.summary_text.setPlainText("Computing…")
        self.parent_app.status_label.setText(f"{self._window_title}: preparing…")

        prep = {
            "use_fp": use_fp,
            "features": features,
            "only_sel": only_sel,
            "color_col": color_col,
            "struct_src": self.struct_src_combo.currentText() if use_fp else None,
            "method_params": dict(self._method_params()),
            "standardize": self.standardize_cb.isChecked(),
            "fingerprint": self.fp_combo.currentText() if use_fp else None,
        }
        QTimer.singleShot(0, lambda p=prep: self._launch_dimred_job(p))

    def _launch_dimred_job(self, prep: dict) -> None:
        """Build inputs then start the background worker (after options dialog has closed)."""
        if self.parent_app is None or not self._job_running:
            return
        use_fp = bool(prep.get("use_fp"))
        features = list(prep.get("features") or [])
        only_sel = bool(prep.get("only_sel"))
        color_col = prep.get("color_col")
        try:
            df, oids = self._scoped_dataframe_and_oids()
        except Exception as exc:
            self._reset_dimred_job_ui()
            QMessageBox.warning(self, self._window_title, str(exc))
            return
        if df.empty:
            self._reset_dimred_job_ui()
            QMessageBox.information(self, self._window_title, "No rows in the current scope.")
            return
        mol_rows = None
        if use_fp:
            src = str(prep.get("struct_src") or "")
            self.parent_app.status_label.setText(f"{self._window_title}: collecting structures…")
            mol_rows = self._collect_table_mols(src, only_sel)
            if len(mol_rows) < 2 and not features:
                self._reset_dimred_job_ui()
                QMessageBox.information(
                    self,
                    self._window_title,
                    "Need at least two rows with valid structures when using fingerprints alone.",
                )
                return
        params = {
            "method": self._method,
            "dataframe": df,
            "oids": oids,
            "feature_columns": features,
            "use_fingerprints": use_fp,
            "mol_rows": mol_rows,
            "fingerprint": prep.get("fingerprint"),
            "standardize": bool(prep.get("standardize", True)),
            "color_column": color_col,
            **dict(prep.get("method_params") or {}),
        }
        import threading

        from ..background_jobs import register_background_job

        self._bg_cancel_event = threading.Event()
        self._bg_job_id = f"dimred-{id(self)}"
        register_background_job(
            self.parent_app,
            self._bg_job_id,
            f"{self._window_title}…",
            cancel=self._bg_cancel_event.set,
        )
        n = len(oids)
        begin = getattr(self.parent_app, "_begin_tool_progress", None)
        if callable(begin):
            begin(self._window_title, n)
        else:
            self.parent_app.status_label.setText(
                f"{self._window_title}: computing in background ({n:,} row(s))…"
            )
        worker = DimensionReductionWorker(params, self._signals, cancel_event=self._bg_cancel_event)
        self.parent_app.threadpool.start(worker)

    def _reset_dimred_job_ui(self) -> None:
        self._clear_dimred_background_job()
        self._job_running = False
        self.run_btn.setEnabled(True)
        if self.parent_app is not None:
            finish = getattr(self.parent_app, "_finish_tool_progress", None)
            if callable(finish):
                finish(self._window_title, status_message=f"{self._window_title}: ready.")
            else:
                self.parent_app.status_label.setText(f"{self._window_title}: ready.")

    def _clear_dimred_background_job(self) -> None:
        job_id = getattr(self, "_bg_job_id", None)
        if job_id and self.parent_app is not None:
            from ..background_jobs import unregister_background_job

            unregister_background_job(self.parent_app, job_id)
        self._bg_job_id = None

    def _on_finished(self, result) -> None:
        self._clear_dimred_background_job()
        self._job_running = False
        self.run_btn.setEnabled(True)
        self.summary_text.setPlainText(result.summary)
        self._last_result = result
        if self._plot_view is None:
            if self.parent_app is not None:
                finish = getattr(self.parent_app, "_finish_tool_progress", None)
                msg = f"{self._window_title}: done."
                if callable(finish):
                    finish(self._window_title, status_message=msg)
                else:
                    self.parent_app.status_label.setText(msg)
            return
        self._refresh_plot_colors()
        self._update_spectrum_controls()
        if self.parent_app is not None:
            shown = self._displayed_dimred_result()
            n = len(shown.oids) if shown is not None else 0
            msg = (
                f"{self._window_title}: rendered {n:,} point(s). "
                "Lasso or click to select table rows."
            )
            finish = getattr(self.parent_app, "_finish_tool_progress", None)
            if callable(finish):
                finish(self._window_title, status_message=msg)
            else:
                self.parent_app.status_label.setText(msg)

    def _on_failed(self, message: str) -> None:
        self._clear_dimred_background_job()
        self._job_running = False
        self.run_btn.setEnabled(True)
        if message == "Cancelled.":
            self.summary_text.setPlainText("Cancelled.")
            if self.parent_app is not None:
                msg = f"{self._window_title}: cancelled."
                finish = getattr(self.parent_app, "_finish_tool_progress", None)
                if callable(finish):
                    finish(self._window_title, status_message=msg)
                else:
                    self.parent_app.status_label.setText(msg)
            return
        self.summary_text.setPlainText("")
        if self.parent_app is not None:
            msg = f"{self._window_title}: failed."
            finish = getattr(self.parent_app, "_finish_tool_progress", None)
            if callable(finish):
                finish(self._window_title, status_message=msg)
            else:
                self.parent_app.status_label.setText(msg)
        QMessageBox.warning(self, self._window_title, message or "Computation failed.")


class DimensionReductionDialog(QDialog):
    """Floating window hosting a :class:`DimensionReductionPanel`."""

    def __init__(
        self,
        parent: ChemicalTableApp | None,
        *,
        panel: DimensionReductionPanel,
    ):
        super().__init__(parent)
        self.parent_app = parent
        self._panel = panel
        self._panel.setParent(self)
        self._panel.parent_app = parent
        self.only_selected_cb = self._panel.only_selected_cb
        self._only_selected_scope_prefix = self._panel._only_selected_scope_prefix

        self.setWindowTitle(panel._window_title)
        self.resize(900, 900)

        root = QVBoxLayout(self)
        root.addWidget(self._panel, 1)
        self._panel._sync_footer_chrome()

        self.setModal(False)
        self.setWindowModality(Qt.NonModal)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self._force_close = False
        make_window_minimizable(self)

    def closeEvent(self, event) -> None:  # noqa: N802 — Qt API name
        handle_floating_plot_close_event(self, event)


class PCAPlotPanel(DimensionReductionPanel):
    """Principal component analysis on numeric table columns."""

    def __init__(self, parent: ChemicalTableApp | None = None):
        super().__init__(parent, window_title="Principal Component Analysis", method="pca")

    def _build_method_options(self, form: QFormLayout) -> None:
        self.pca_components = QSpinBox()
        self.pca_components.setRange(2, 50)
        self.pca_components.setValue(2)
        self.pca_components.setToolTip(
            "Number of principal components to compute (plot uses PC1 vs PC2)."
        )
        form.addRow("Components:", self.pca_components)

    def _method_params(self) -> dict:
        return {"n_components": int(self.pca_components.value())}

    def _apply_method_params(self, params: dict | None) -> None:
        if not isinstance(params, dict):
            return
        n = params.get("n_components")
        if isinstance(n, int):
            self.pca_components.setValue(max(2, min(50, n)))


class PCADialog(DimensionReductionDialog):
    def __init__(
        self,
        parent: ChemicalTableApp | None = None,
        *,
        panel: DimensionReductionPanel | None = None,
    ):
        super().__init__(parent, panel=panel or PCAPlotPanel(parent))


class TSNEPlotPanel(DimensionReductionPanel):
    """t-SNE embedding of numeric table columns."""

    def __init__(self, parent: ChemicalTableApp | None = None):
        super().__init__(parent, window_title="t-SNE Visualization", method="tsne")

    def _build_method_options(self, form: QFormLayout) -> None:
        self.tsne_perplexity = QDoubleSpinBox()
        self.tsne_perplexity.setRange(5.0, 500.0)
        self.tsne_perplexity.setDecimals(1)
        self.tsne_perplexity.setValue(30.0)
        form.addRow("Perplexity:", self.tsne_perplexity)

        self.tsne_learning_rate = QDoubleSpinBox()
        self.tsne_learning_rate.setRange(10.0, 1000.0)
        self.tsne_learning_rate.setDecimals(0)
        self.tsne_learning_rate.setValue(200.0)
        form.addRow("Learning rate:", self.tsne_learning_rate)

        self.tsne_max_iter = QSpinBox()
        self.tsne_max_iter.setRange(250, 10000)
        self.tsne_max_iter.setSingleStep(250)
        self.tsne_max_iter.setValue(1000)
        form.addRow("Max iterations:", self.tsne_max_iter)

        self.tsne_max_points = QSpinBox()
        from ...config import load_config

        dimred_cap = int(load_config().memory_guard_dimred_max_points)
        self.tsne_max_points.setRange(100, dimred_cap)
        self.tsne_max_points.setValue(min(2500, dimred_cap))
        self.tsne_max_points.setToolTip(
            "Subsample to this many rows when the table is larger (keeps the UI responsive)."
        )
        form.addRow("Max points:", self.tsne_max_points)

        self.tsne_seed = QSpinBox()
        self.tsne_seed.setRange(0, 999_999)
        self.tsne_seed.setValue(42)
        form.addRow("Random seed:", self.tsne_seed)

    def _method_params(self) -> dict:
        return {
            "perplexity": float(self.tsne_perplexity.value()),
            "learning_rate": float(self.tsne_learning_rate.value()),
            "max_iter": int(self.tsne_max_iter.value()),
            "max_points": int(self.tsne_max_points.value()),
            "random_state": int(self.tsne_seed.value()),
        }

    def _apply_method_params(self, params: dict | None) -> None:
        if not isinstance(params, dict):
            return
        if params.get("perplexity") is not None:
            self.tsne_perplexity.setValue(float(params["perplexity"]))
        if params.get("learning_rate") is not None:
            self.tsne_learning_rate.setValue(float(params["learning_rate"]))
        if isinstance(params.get("max_iter"), int):
            self.tsne_max_iter.setValue(int(params["max_iter"]))
        if isinstance(params.get("max_points"), int):
            self.tsne_max_points.setValue(int(params["max_points"]))
        if isinstance(params.get("random_state"), int):
            self.tsne_seed.setValue(int(params["random_state"]))


class TSNEVisualizationDialog(DimensionReductionDialog):
    def __init__(
        self,
        parent: ChemicalTableApp | None = None,
        *,
        panel: DimensionReductionPanel | None = None,
    ):
        super().__init__(parent, panel=panel or TSNEPlotPanel(parent))


class UMAPPlotPanel(DimensionReductionPanel):
    """UMAP embedding of numeric table columns or fingerprints."""

    def __init__(self, parent: ChemicalTableApp | None = None):
        super().__init__(parent, window_title="UMAP Visualization", method="umap")

    def _build_method_options(self, form: QFormLayout) -> None:
        self.umap_neighbors = QSpinBox()
        self.umap_neighbors.setRange(2, 200)
        self.umap_neighbors.setValue(15)
        self.umap_neighbors.setToolTip(
            "Local neighborhood size; lower values emphasize fine structure, higher values global layout."
        )
        form.addRow("n_neighbors:", self.umap_neighbors)

        self.umap_min_dist = QDoubleSpinBox()
        self.umap_min_dist.setRange(0.0, 0.99)
        self.umap_min_dist.setDecimals(2)
        self.umap_min_dist.setSingleStep(0.05)
        self.umap_min_dist.setValue(0.1)
        self.umap_min_dist.setToolTip(
            "Minimum spacing between embedded points (0 = tight clusters, ~1 = spread out)."
        )
        form.addRow("min_dist:", self.umap_min_dist)

        self.umap_max_points = QSpinBox()
        from ...config import load_config

        dimred_cap = int(load_config().memory_guard_dimred_max_points)
        self.umap_max_points.setRange(100, dimred_cap)
        self.umap_max_points.setValue(min(2500, dimred_cap))
        self.umap_max_points.setToolTip(
            "Subsample to this many rows when the table is larger (keeps the UI responsive)."
        )
        form.addRow("Max points:", self.umap_max_points)

        self.umap_seed = QSpinBox()
        self.umap_seed.setRange(0, 999_999)
        self.umap_seed.setValue(42)
        form.addRow("Random seed:", self.umap_seed)

    def _method_params(self) -> dict:
        return {
            "n_neighbors": int(self.umap_neighbors.value()),
            "min_dist": float(self.umap_min_dist.value()),
            "max_points": int(self.umap_max_points.value()),
            "random_state": int(self.umap_seed.value()),
        }

    def _apply_method_params(self, params: dict | None) -> None:
        if not isinstance(params, dict):
            return
        if isinstance(params.get("n_neighbors"), int):
            self.umap_neighbors.setValue(int(params["n_neighbors"]))
        if params.get("min_dist") is not None:
            self.umap_min_dist.setValue(float(params["min_dist"]))
        if isinstance(params.get("max_points"), int):
            self.umap_max_points.setValue(int(params["max_points"]))
        if isinstance(params.get("random_state"), int):
            self.umap_seed.setValue(int(params["random_state"]))


class UMAPVisualizationDialog(DimensionReductionDialog):
    def __init__(
        self,
        parent: ChemicalTableApp | None = None,
        *,
        panel: DimensionReductionPanel | None = None,
    ):
        super().__init__(parent, panel=panel or UMAPPlotPanel(parent))


class SOMPlotPanel(DimensionReductionPanel):
    """Kohonen self-organizing map of numeric columns and/or fingerprints."""

    def __init__(self, parent: ChemicalTableApp | None = None):
        super().__init__(parent, window_title="Self-Organizing Map", method="som")

    def _build_method_options(self, form: QFormLayout) -> None:
        self.som_grid_w = QSpinBox()
        self.som_grid_w.setRange(2, 40)
        self.som_grid_w.setValue(10)
        self.som_grid_w.setToolTip("Number of map columns (X). Nodes = width × height (max 2,500).")
        form.addRow("Map width:", self.som_grid_w)

        self.som_grid_h = QSpinBox()
        self.som_grid_h.setRange(2, 40)
        self.som_grid_h.setValue(10)
        self.som_grid_h.setToolTip("Number of map rows (Y). Nodes = width × height (max 2,500).")
        form.addRow("Map height:", self.som_grid_h)

        self.som_epochs = QSpinBox()
        self.som_epochs.setRange(5, 500)
        self.som_epochs.setValue(50)
        self.som_epochs.setToolTip("Training epochs; each epoch presents every sample once.")
        form.addRow("Epochs:", self.som_epochs)

        self.som_lr = QDoubleSpinBox()
        self.som_lr.setRange(0.01, 1.0)
        self.som_lr.setDecimals(2)
        self.som_lr.setSingleStep(0.05)
        self.som_lr.setValue(0.5)
        self.som_lr.setToolTip("Initial learning rate (decays linearly to near zero).")
        form.addRow("Learning rate:", self.som_lr)

        self.som_sigma = QDoubleSpinBox()
        self.som_sigma.setRange(0.0, 40.0)
        self.som_sigma.setDecimals(1)
        self.som_sigma.setSingleStep(0.5)
        self.som_sigma.setValue(0.0)
        self.som_sigma.setSpecialValueText("auto (½ max side)")
        self.som_sigma.setToolTip(
            "Initial neighborhood radius in node units. 0 = half the longer map side."
        )
        form.addRow("Sigma:", self.som_sigma)

        self.som_jitter = QDoubleSpinBox()
        self.som_jitter.setRange(0.0, 0.5)
        self.som_jitter.setDecimals(2)
        self.som_jitter.setSingleStep(0.05)
        self.som_jitter.setValue(0.35)
        self.som_jitter.setToolTip(
            "Jitter BMU coordinates so compounds on the same node do not stack exactly."
        )
        form.addRow("Point jitter:", self.som_jitter)

        self.som_max_points = QSpinBox()
        from ...config import load_config

        dimred_cap = int(load_config().memory_guard_dimred_max_points)
        self.som_max_points.setRange(100, dimred_cap)
        self.som_max_points.setValue(min(2500, dimred_cap))
        self.som_max_points.setToolTip(
            "Subsample to this many rows when the table is larger (keeps training responsive)."
        )
        form.addRow("Max points:", self.som_max_points)

        self.som_seed = QSpinBox()
        self.som_seed.setRange(0, 999_999)
        self.som_seed.setValue(42)
        form.addRow("Random seed:", self.som_seed)

    def _method_params(self) -> dict:
        return {
            "grid_width": int(self.som_grid_w.value()),
            "grid_height": int(self.som_grid_h.value()),
            "n_epochs": int(self.som_epochs.value()),
            "learning_rate": float(self.som_lr.value()),
            "sigma": float(self.som_sigma.value()),
            "jitter": float(self.som_jitter.value()),
            "max_points": int(self.som_max_points.value()),
            "random_state": int(self.som_seed.value()),
        }

    def _apply_method_params(self, params: dict | None) -> None:
        if not isinstance(params, dict):
            return
        for key, spin in (
            ("grid_width", self.som_grid_w),
            ("grid_height", self.som_grid_h),
            ("n_epochs", self.som_epochs),
            ("max_points", self.som_max_points),
            ("random_state", self.som_seed),
        ):
            if isinstance(params.get(key), int):
                spin.setValue(int(params[key]))
        for key, spin in (
            ("learning_rate", self.som_lr),
            ("sigma", self.som_sigma),
            ("jitter", self.som_jitter),
        ):
            if params.get(key) is not None:
                spin.setValue(float(params[key]))


class SOMVisualizationDialog(DimensionReductionDialog):
    def __init__(
        self,
        parent: ChemicalTableApp | None = None,
        *,
        panel: DimensionReductionPanel | None = None,
    ):
        super().__init__(parent, panel=panel or SOMPlotPanel(parent))


_DIMRED_FLOATING_DIALOGS = {
    "pca": PCADialog,
    "tsne": TSNEVisualizationDialog,
    "umap": UMAPVisualizationDialog,
    "som": SOMVisualizationDialog,
}

_DIMRED_PANELS = {
    "pca": PCAPlotPanel,
    "tsne": TSNEPlotPanel,
    "umap": UMAPPlotPanel,
    "som": SOMPlotPanel,
}


def dimension_reduction_panel_from_session(
    parent_app: ChemicalTableApp | None,
    state: dict | None,
) -> DimensionReductionPanel:
    method = "pca"
    if isinstance(state, dict):
        method = str(state.get("method") or "pca")
    panel_cls = _DIMRED_PANELS.get(method, PCAPlotPanel)
    panel = panel_cls(parent_app)
    panel.apply_session_state(state)
    return panel
