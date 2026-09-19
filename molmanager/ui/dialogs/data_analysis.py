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

"""Table data extraction and statistical analysis for the main window."""

from __future__ import annotations

import io
from collections.abc import Iterator
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QDoubleSpinBox,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..qt_widget_utils import apply_monospace_to_text_edit, make_window_minimizable

if TYPE_CHECKING:
    from ..main_window import ChemistryWorkspaceWindow


def iter_scoped_table_analysis_rows(
    app: ChemistryWorkspaceWindow,
    *,
    visible_only: bool = True,
    only_selected: bool = False,
) -> Iterator[tuple[int, dict[str, str]]]:
    """Yield (table_row_index, row_dict) for rows included in Statistics scope."""
    m = app._table_model
    ncols = m.columnCount()
    nrows = m.rowCount()
    if not app.headers or ncols < 1 or nrows < 1:
        return

    selected_oids: set[int] | None = None
    if only_selected:
        selected_oids = app._selected_oids_set()

    visible_rows: set[int] | None = None
    if visible_only:
        vis = app._visible_source_row_indices()
        visible_rows = None if vis is None else set(vis)

    for r in range(nrows):
        if visible_rows is not None and r not in visible_rows:
            continue
        if only_selected:
            t0 = m.cell_text(r, 0)
            if not t0.isdigit() or int(t0) not in (selected_oids or set()):
                continue
        row: dict[str, str] = {}
        for c in range(ncols):
            if c >= len(app.headers):
                break
            name = app.headers[c]
            if name == "Structure":
                continue
            text = (m.cell_text(r, c) or "").strip()
            if not text:
                text = (m.backing_value_for_row_header(r, name) or "").strip()
            row[name] = text
        yield r, row


def table_to_dataframe(
    app: ChemistryWorkspaceWindow,
    *,
    visible_only: bool = True,
    only_selected: bool = False,
) -> tuple[pd.DataFrame, list[int]]:
    """Build a DataFrame from the main table (skips Structure column) and parallel source row indices."""
    rows: list[dict[str, str]] = []
    source_rows: list[int] = []
    for r, row in iter_scoped_table_analysis_rows(
        app, visible_only=visible_only, only_selected=only_selected
    ):
        source_rows.append(r)
        rows.append(row)
    return pd.DataFrame(rows), source_rows


def selected_table_column_headers(app: ChemistryWorkspaceWindow) -> list[str]:
    """Distinct data-column header names currently spanned by the main-table selection."""
    sm = app.table.selectionModel()
    if sm is None or not app.headers:
        return []
    view_cols = sorted({ix.column() for ix in sm.selectedIndexes() if ix.isValid()})
    names: list[str] = []
    for col in view_cols:
        if col <= 0 or col >= len(app.headers):
            continue
        name = app.headers[col]
        if name in ("ID_HIDDEN", "Structure"):
            continue
        if name not in names:
            names.append(name)
    return names


def numeric_subset(df: pd.DataFrame, *, exclude_id: bool = True) -> pd.DataFrame:
    """Columns that have at least one finite numeric value; optionally drop ID_HIDDEN."""
    if df.empty:
        return df
    cols = [c for c in df.columns if not (exclude_id and c == "ID_HIDDEN")]
    num = df[cols].apply(pd.to_numeric, errors="coerce")
    keep = [c for c in num.columns if num[c].notna().any()]
    return num[keep] if keep else pd.DataFrame(index=df.index)


def _r2_rmse(y: np.ndarray, y_hat: np.ndarray) -> tuple[float, float]:
    y = np.asarray(y, dtype=float)
    y_hat = np.asarray(y_hat, dtype=float)
    n = len(y)
    if n < 1:
        return float("nan"), float("nan")
    ss_res = float(np.sum((y - y_hat) ** 2))
    y_mean = float(np.mean(y))
    ss_tot = float(np.sum((y - y_mean) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else float("nan")
    rmse = float(np.sqrt(ss_res / n))
    return r2, rmse


def _outlier_mask_iqr(v: np.ndarray, *, k: float = 1.5) -> np.ndarray:
    """Tukey fences: True where value is outside [Q1 - k·IQR, Q3 + k·IQR]."""
    v = np.asarray(v, dtype=float)
    m = np.isfinite(v)
    out = np.zeros_like(v, dtype=bool)
    if int(np.sum(m)) < 4:
        return out
    xs = v[m]
    q1, q3 = np.percentile(xs, [25.0, 75.0])
    iqr = float(q3 - q1)
    if iqr <= 0.0 or not np.isfinite(iqr):
        return out
    lo, hi = q1 - k * iqr, q3 + k * iqr
    out[m] = (xs < lo) | (xs > hi)
    return out


def _outlier_mask_zscore(v: np.ndarray, *, z: float = 3.0) -> np.ndarray:
    """Classic Z using sample mean and SD; True where |Z| > threshold."""
    v = np.asarray(v, dtype=float)
    m = np.isfinite(v)
    out = np.zeros_like(v, dtype=bool)
    xs = v[m]
    if xs.size < 2:
        return out
    mu = float(np.mean(xs))
    sig = float(np.std(xs, ddof=1))
    if sig <= 0.0 or not np.isfinite(sig):
        return out
    zsc = np.abs((v - mu) / sig)
    return m & (zsc > z)


def _outlier_mask_modified_z(v: np.ndarray, *, threshold: float = 3.5) -> np.ndarray:
    """Modified Z (Iglewicz & Hoaglin): 0.6745 · |x − median| / MAD."""
    v = np.asarray(v, dtype=float)
    m = np.isfinite(v)
    out = np.zeros_like(v, dtype=bool)
    xs = v[m]
    if xs.size < 3:
        return out
    med = float(np.median(xs))
    mad = float(np.median(np.abs(xs - med)))
    if mad <= 0.0 or not np.isfinite(mad):
        return out
    mz = 0.6745 * np.abs(v - med) / mad
    return m & (mz > threshold)


class DataAnalysisDialog(QDialog):
    """Summarize, correlate, detect outliers, fit curves, and run tests on numeric columns."""

    def __init__(self, parent: ChemistryWorkspaceWindow | None = None):
        super().__init__(parent)
        self.parent_app = parent
        self.setWindowTitle("Statistics")
        self.resize(920, 680)
        self._df_raw = pd.DataFrame()
        self._df_num = pd.DataFrame()
        self._scoped_source_rows: list[int] = []
        self._last_outlier_table_rows: list[int] = []
        self._suppress_analysis_reload = False
        self._table_updates_wired = False
        self._reload_debounce = QTimer(self)
        self._reload_debounce.setSingleShot(True)
        self._reload_debounce.setInterval(80)
        self._reload_debounce.timeout.connect(self._reload)
        n_sel = len(parent._selected_logical_rows()) if parent is not None else 0
        self._have_selection = n_sel > 0

        root = QVBoxLayout(self)

        self.tabs = QTabWidget()
        root.addWidget(self.tabs)

        self.chk_visible = QCheckBox("Visible Rows Only")
        self.chk_visible.setChecked(True)
        self.chk_visible.stateChanged.connect(self._reload)

        self.only_selected_cb = QCheckBox("Selected Rows Only")
        self._only_selected_scope_prefix = "Selected Rows Only"
        if self._have_selection:
            self.only_selected_cb.setText(f"{self._only_selected_scope_prefix} ({n_sel} row(s))")
        else:
            self.only_selected_cb.setEnabled(False)
        self.only_selected_cb.stateChanged.connect(self._reload)

        self.chk_selected_columns = QCheckBox("Selected Columns Only")
        self._selected_columns_scope_prefix = "Selected Columns Only"
        self.chk_selected_columns.setToolTip(
            "Correlations and Percentiles use only numeric columns selected in the main table "
            "(click a column header to select a column; Shift+click for a range)."
        )
        self.chk_selected_columns.setEnabled(False)

        self._tab_summary = self._build_summary_tab()
        self._tab_corr = self._build_correlation_tab()
        self._tab_percentiles = self._build_percentiles_tab()
        self._tab_outliers = self._build_outliers_tab()
        self._tab_curve = self._build_curve_fit_tab()
        self._tab_stats = self._build_stats_tests_tab()
        self.tabs.addTab(self._tab_summary, "Summary")
        self.tabs.addTab(self._tab_corr, "Correlations")
        self.tabs.addTab(self._tab_percentiles, "Percentiles")
        self.tabs.addTab(self._tab_outliers, "Outliers")
        self.tabs.addTab(self._tab_curve, "Curve Fit")
        self.tabs.addTab(self._tab_stats, "Statistical tests")

        bottom = QHBoxLayout()
        bottom.addWidget(self.chk_visible)
        bottom.addWidget(self.only_selected_cb)
        bottom.addWidget(self.chk_selected_columns)
        bottom.addStretch()
        root.addLayout(bottom)

        self._reload()
        self._sync_selected_columns_only_scope()
        self._wire_table_updates()
        make_window_minimizable(self)

    def _wire_table_updates(self) -> None:
        """Keep scoped table data in sync when the main table, filters, or selection change."""
        if self._table_updates_wired or self.parent_app is None:
            return
        app = self.parent_app
        model = getattr(app, "_table_model", None)
        if model is None:
            return

        def _schedule_reload() -> None:
            if self._suppress_analysis_reload:
                return
            self._reload_debounce.start()

        model.dataChanged.connect(_schedule_reload)
        model.rowsInserted.connect(_schedule_reload)
        model.rowsRemoved.connect(_schedule_reload)
        model.modelReset.connect(_schedule_reload)
        model.layoutChanged.connect(_schedule_reload)
        model.headerDataChanged.connect(_schedule_reload)
        proxy = getattr(app, "_filter_proxy_model", None)
        if proxy is not None:
            proxy.layoutChanged.connect(_schedule_reload)
            proxy.modelReset.connect(_schedule_reload)
        sm = app.table.selectionModel()
        if sm is not None:
            sm.selectionChanged.connect(self._sync_selected_columns_only_scope)
        # Do not reload on selection changes — selecting outlier rows in the main table
        # must not clear the outlier log or cached row indices from the last Find run.
        self._table_updates_wired = True

    def _selected_table_column_headers(self) -> list[str]:
        app = self.parent_app
        if app is None:
            return []
        return selected_table_column_headers(app)

    def _sync_selected_columns_only_scope(self) -> None:
        """Enable Selected Columns Only when the main table has column(s) selected."""
        prefix = self._selected_columns_scope_prefix
        headers = self._selected_table_column_headers()
        n = len(headers)
        if n > 0:
            self.chk_selected_columns.setEnabled(True)
            self.chk_selected_columns.setText(f"{prefix} ({n} column(s))")
        else:
            self.chk_selected_columns.setEnabled(False)
            self.chk_selected_columns.setChecked(False)
            self.chk_selected_columns.setText(prefix)

    def _numeric_for_correlation_percentiles(self) -> pd.DataFrame | None:
        """
        Numeric columns for Correlations / Percentiles.

        Returns ``None`` when Selected Columns Only is checked but no usable columns remain.
        """
        df = self._df_num
        if not self.chk_selected_columns.isChecked():
            return df
        chosen = self._selected_table_column_headers()
        if not chosen:
            return None
        keep = [c for c in chosen if c in df.columns]
        if not keep:
            return None
        return df[keep]

    def refresh_table_data(self) -> None:
        """Reload the scoped DataFrame from the main table (immediate, not debounced)."""
        self._reload_debounce.stop()
        self._reload()

    def _build_summary_tab(self) -> QWidget:
        w = QWidget()
        ly = QVBoxLayout(w)
        self.summary_text = QTextEdit()
        self.summary_text.setReadOnly(True)
        apply_monospace_to_text_edit(self.summary_text)
        ly.addWidget(self.summary_text)
        btn = QPushButton("Copy summary to clipboard")
        btn.clicked.connect(self._copy_summary)
        ly.addWidget(btn)
        return w

    def _build_correlation_tab(self) -> QWidget:
        w = QWidget()
        ly = QVBoxLayout(w)
        row = QHBoxLayout()
        row.addWidget(QLabel("Method:"))
        self.corr_method = QComboBox()
        self.corr_method.addItems(["pearson", "spearman", "kendall"])
        row.addWidget(self.corr_method)
        self.btn_corr = QPushButton("Compute correlation matrix")
        self.btn_corr.clicked.connect(self._run_correlation)
        row.addWidget(self.btn_corr)
        row.addStretch()
        ly.addLayout(row)
        self.corr_table = QTableWidget()
        self.corr_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.corr_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        ly.addWidget(self.corr_table)
        return w

    def _build_percentiles_tab(self) -> QWidget:
        w = QWidget()
        ly = QVBoxLayout(w)
        ly.addWidget(
            QLabel(
                "Enter percentiles as comma-separated numbers (e.g. 5, 25, 50, 75, 95). "
                "Uses linear interpolation between ranks."
            )
        )
        row = QHBoxLayout()
        self.percentile_input = QLineEdit("5, 25, 50, 75, 95")
        row.addWidget(self.percentile_input)
        self.btn_percentiles = QPushButton("Compute")
        self.btn_percentiles.clicked.connect(self._run_percentiles)
        row.addWidget(self.btn_percentiles)
        ly.addLayout(row)
        self.percentile_text = QTextEdit()
        self.percentile_text.setReadOnly(True)
        apply_monospace_to_text_edit(self.percentile_text)
        ly.addWidget(self.percentile_text)
        return w

    def _build_curve_fit_tab(self) -> QWidget:
        w = QWidget()
        ly = QVBoxLayout(w)
        form = QFormLayout()
        self.fit_x = QComboBox()
        self.fit_y = QComboBox()
        form.addRow("X (predictor):", self.fit_x)
        form.addRow("Y (response):", self.fit_y)
        self.fit_model = QComboBox()
        self.fit_model.addItems(
            [
                "Polynomial (OLS, NumPy)",
                "Exponential y = a·exp(b·x)",
                "Log-X linear y = a + b·ln(x)",
                "Power law y = a·x^b (x,y > 0)",
            ]
        )
        form.addRow("Model:", self.fit_model)
        self.fit_poly_deg = QSpinBox()
        self.fit_poly_deg.setRange(1, 8)
        self.fit_poly_deg.setValue(1)
        self.fit_poly_deg.setToolTip("Degree for polynomial model (1 = straight line).")
        form.addRow("Polynomial degree:", self.fit_poly_deg)
        self.fit_model.currentIndexChanged.connect(self._sync_curve_fit_controls)
        self.btn_curve_fit = QPushButton("Fit")
        self.btn_curve_fit.clicked.connect(self._run_curve_fit)
        form.addRow(self.btn_curve_fit)
        ly.addLayout(form)
        self.curve_text = QTextEdit()
        self.curve_text.setReadOnly(True)
        apply_monospace_to_text_edit(self.curve_text)
        ly.addWidget(self.curve_text)
        self._sync_curve_fit_controls()
        return w

    def _sync_curve_fit_controls(self) -> None:
        poly = self.fit_model.currentIndex() == 0
        self.fit_poly_deg.setEnabled(poly)

    def _build_stats_tests_tab(self) -> QWidget:
        w = QWidget()
        ly = QVBoxLayout(w)
        self.stats_hint = QLabel("")
        self.stats_hint.setWordWrap(True)
        self.stats_hint.setStyleSheet("color: palette(mid);")
        ly.addWidget(self.stats_hint)
        gb = QGroupBox("Hypothesis tests (SciPy)")
        form = QFormLayout(gb)
        self.stats_test = QComboBox()
        self.stats_test.addItems(
            [
                "Paired t-test (same rows, two columns)",
                "Welch t-test (two columns as independent samples)",
                "Mann-Whitney U (two columns, independent)",
                "One-sample t-test (column vs mean)",
                "Shapiro-Wilk normality (one column)",
            ]
        )
        form.addRow("Test:", self.stats_test)
        self.stats_a = QComboBox()
        self.stats_b = QComboBox()
        form.addRow("Column A:", self.stats_a)
        form.addRow("Column B:", self.stats_b)
        self.stats_mean = QLineEdit("0")
        self.stats_mean.setPlaceholderText("Hypothesized population mean")
        form.addRow("H₀ mean (one-sample):", self.stats_mean)
        self.stats_test.currentIndexChanged.connect(self._sync_stats_controls)
        self.btn_stats = QPushButton("Run test")
        self.btn_stats.clicked.connect(self._run_stats_tests)
        form.addRow(self.btn_stats)
        ly.addWidget(gb)
        self.stats_text = QTextEdit()
        self.stats_text.setReadOnly(True)
        apply_monospace_to_text_edit(self.stats_text)
        ly.addWidget(self.stats_text)
        self._sync_stats_controls()
        self._update_stats_scipy_hint()
        return w

    def _update_stats_scipy_hint(self) -> None:
        try:
            import scipy  # noqa: F401
        except Exception:
            self.stats_hint.setText(
                "SciPy is required for statistical tests. Install with: pip install scipy"
            )
            self.btn_stats.setEnabled(False)
            return
        self.stats_hint.setText(
            "Uses SciPy's standard implementations. Interpret p-values in context; "
            "assumptions (normality, independence) differ by test."
        )
        self.btn_stats.setEnabled(True)

    def _sync_stats_controls(self) -> None:
        idx = self.stats_test.currentIndex()
        # 0 paired, 1 welch, 2 MW — need two columns; 3 one-sample — one column; 4 shapiro — one column
        need_b = idx in (0, 1, 2)
        self.stats_b.setEnabled(need_b)
        self.stats_mean.setEnabled(idx == 3)

    def _reload(self) -> None:
        if self.parent_app is None:
            return
        vis = self.chk_visible.isChecked()
        only_sel = self.only_selected_cb.isChecked() and self.only_selected_cb.isEnabled()
        self._df_raw, self._scoped_source_rows = table_to_dataframe(
            self.parent_app, visible_only=vis, only_selected=only_sel
        )
        self._df_num = numeric_subset(self._df_raw, exclude_id=True)
        self._populate_fit_combos()
        self._run_summary()
        self._sync_selected_columns_only_scope()
        self.curve_text.clear()
        self.stats_text.clear()
        self.corr_table.setRowCount(0)
        self.corr_table.setColumnCount(0)
        self.percentile_text.clear()

    def _populate_fit_combos(self, *, refresh_outlier_col: bool = True) -> None:
        cols = list(self._df_num.columns)
        prev_outlier_col = self.outlier_col.currentText()
        for combo in (self.fit_x, self.fit_y, self.stats_a, self.stats_b):
            combo.clear()
            combo.addItems(cols)
        if refresh_outlier_col:
            self._repopulate_outlier_col_combo(cols, prev_outlier_col)
        if len(cols) >= 2:
            self.fit_y.setCurrentIndex(1)
            self.stats_b.setCurrentIndex(min(1, len(cols) - 1))

    def _run_summary(self) -> None:
        lines: list[str] = []
        only_sel = self.only_selected_cb.isChecked() and self.only_selected_cb.isEnabled()
        if only_sel and self.parent_app is not None and not self.parent_app._selected_oids_set():
            lines.append("Selected Rows Only is checked, but no rows are selected.")
            lines.append("")
        n = len(self._df_raw)
        lines.append(f"Rows: {n}")
        lines.append(f"Columns (excl. Structure): {self._df_raw.shape[1]}")
        num_cols = list(self._df_num.columns)
        lines.append(f"Numeric columns (≥1 value): {len(num_cols)}")
        if num_cols and n > 0:
            lines.append("")
            desc = self._df_num.describe(percentiles=[0.05, 0.25, 0.5, 0.75, 0.95])
            lines.append(desc.to_string())
            lines.append("")
            sk = self._df_num.skew(numeric_only=True)
            ku = self._df_num.kurtosis(numeric_only=True)
            lines.append("Skewness:")
            lines.append(sk.to_string())
            lines.append("")
            lines.append("Kurtosis (excess):")
            lines.append(ku.to_string())
        elif not num_cols:
            lines.append("")
            lines.append(
                "No numeric columns detected after coercion — add numeric property columns or calculations."
            )
        miss = self._df_raw.isna().sum()
        if miss.any():
            lines.append("")
            lines.append("Missing / non-numeric cells (raw column counts as NaN after coercion):")
            lines.append(miss[miss > 0].to_string())
        self.summary_text.setPlainText("\n".join(lines))

    def _copy_summary(self) -> None:
        from PyQt5.QtWidgets import QApplication

        QApplication.clipboard().setText(self.summary_text.toPlainText())

    def _run_correlation(self) -> None:
        self.refresh_table_data()
        num = self._numeric_for_correlation_percentiles()
        if num is None:
            QMessageBox.information(
                self,
                "Correlations",
                "Selected Columns Only is checked, but no table columns are selected "
                "(click a column header in the main table; Shift+click for a range).",
            )
            self.corr_table.setRowCount(0)
            self.corr_table.setColumnCount(0)
            return
        if num.shape[1] < 2:
            QMessageBox.information(
                self,
                "Correlations",
                "Need at least two numeric columns with data. Try Calculate Descriptors or Calculator first.",
            )
            self.corr_table.setRowCount(0)
            self.corr_table.setColumnCount(0)
            return
        method = self.corr_method.currentText()
        try:
            corr = num.corr(method=method, numeric_only=True)
        except Exception as e:
            QMessageBox.warning(self, "Correlations", str(e))
            return
        self._fill_matrix_table(self.corr_table, corr)

    def _fill_matrix_table(self, table: QTableWidget, mat: pd.DataFrame) -> None:
        table.clear()
        labels = [str(x) for x in mat.columns]
        n = len(labels)
        table.setRowCount(n)
        table.setColumnCount(n)
        table.setHorizontalHeaderLabels(labels)
        table.setVerticalHeaderLabels(labels)
        for i in range(n):
            for j in range(n):
                v = mat.iloc[i, j]
                item = QTableWidgetItem("" if pd.isna(v) else f"{float(v):.6g}")
                item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                table.setItem(i, j, item)

    def _parse_percentiles(self, s: str) -> list[float]:
        parts = [p.strip() for p in s.split(",") if p.strip()]
        out: list[float] = []
        for p in parts:
            v = float(p)
            if v > 1.0:
                v = v / 100.0
            if not (0.0 < v < 1.0):
                raise ValueError(f"Percentile out of (0,100) exclusive: {p}")
            out.append(v)
        return sorted(set(out))

    def _run_percentiles(self) -> None:
        self.refresh_table_data()
        num = self._numeric_for_correlation_percentiles()
        if num is None:
            self.percentile_text.setPlainText(
                "Selected Columns Only is checked, but no table columns are selected "
                "(click a column header in the main table; Shift+click for a range)."
            )
            return
        if num.empty:
            self.percentile_text.setPlainText("No numeric columns.")
            return
        try:
            qs = self._parse_percentiles(self.percentile_input.text())
        except ValueError as e:
            QMessageBox.warning(self, "Percentiles", str(e))
            return
        try:
            res = num.quantile(q=qs, interpolation="linear")
        except Exception as e:
            QMessageBox.warning(self, "Percentiles", str(e))
            return
        buf = io.StringIO()
        res.to_csv(buf)
        self.percentile_text.setPlainText(buf.getvalue())

    def _build_outliers_tab(self) -> QWidget:
        w = QWidget()
        ly = QVBoxLayout(w)
        form = QFormLayout()
        self.outlier_method = QComboBox()
        self.outlier_method.addItems(
            [
                "IQR / Tukey fences",
                "Z-score (sample mean & SD)",
                "Modified Z-score (median & MAD)",
            ]
        )
        self.outlier_method.currentIndexChanged.connect(self._sync_outlier_controls)
        form.addRow("Method:", self.outlier_method)

        self.outlier_col = QComboBox()
        form.addRow("Column:", self.outlier_col)

        self.outlier_iqr_k = QDoubleSpinBox()
        self.outlier_iqr_k.setRange(0.5, 5.0)
        self.outlier_iqr_k.setDecimals(2)
        self.outlier_iqr_k.setSingleStep(0.1)
        self.outlier_iqr_k.setValue(1.5)
        self.outlier_iqr_k.setToolTip(
            "Distance from the quartiles in IQR units (common default 1.5)."
        )
        form.addRow("IQR multiplier k:", self.outlier_iqr_k)

        self.outlier_z_abs = QDoubleSpinBox()
        self.outlier_z_abs.setRange(1.5, 12.0)
        self.outlier_z_abs.setDecimals(2)
        self.outlier_z_abs.setSingleStep(0.25)
        self.outlier_z_abs.setValue(3.0)
        self.outlier_z_abs.setToolTip("Flag when |Z| exceeds this threshold (using sample SD).")
        form.addRow("|Z| threshold:", self.outlier_z_abs)

        self.outlier_mz_thr = QDoubleSpinBox()
        self.outlier_mz_thr.setRange(2.0, 10.0)
        self.outlier_mz_thr.setDecimals(2)
        self.outlier_mz_thr.setSingleStep(0.1)
        self.outlier_mz_thr.setValue(3.5)
        self.outlier_mz_thr.setToolTip(
            "Modified Z threshold (Iglewicz & Hoaglin; common default 3.5)."
        )
        form.addRow("Modified |Z| threshold:", self.outlier_mz_thr)

        self.btn_outliers = QPushButton("Find outliers")
        self.btn_outliers.clicked.connect(self._run_outliers)
        self.btn_select_outliers = QPushButton("Select in Table")
        self.btn_select_outliers.setToolTip(
            "Select main-table rows flagged in the last Find outliers run."
        )
        self.btn_select_outliers.clicked.connect(self._select_last_outliers_in_main_table)
        out_btn_row = QHBoxLayout()
        out_btn_row.addWidget(self.btn_outliers)
        out_btn_row.addWidget(self.btn_select_outliers)
        out_btn_row.addStretch()
        out_btn_wrap = QWidget()
        out_btn_wrap.setLayout(out_btn_row)
        form.addRow(out_btn_wrap)
        ly.addLayout(form)

        self.outlier_text = QTextEdit()
        self.outlier_text.setReadOnly(True)
        apply_monospace_to_text_edit(self.outlier_text)
        ly.addWidget(self.outlier_text)
        self._sync_outlier_controls()
        return w

    def _repopulate_outlier_col_combo(self, cols: list[str], prev_choice: str) -> None:
        self.outlier_col.blockSignals(True)
        self.outlier_col.clear()
        self.outlier_col.addItem("All numeric columns")
        self.outlier_col.addItems(cols)
        if prev_choice == "All numeric columns" or prev_choice in cols:
            idx = self.outlier_col.findText(prev_choice)
            if idx >= 0:
                self.outlier_col.setCurrentIndex(idx)
        self.outlier_col.blockSignals(False)

    def _select_last_outliers_in_main_table(self) -> None:
        app = self.parent_app
        if app is None:
            return
        if not self._last_outlier_table_rows:
            QMessageBox.information(
                self,
                "Outliers",
                "Run Find outliers first, or no outliers were flagged in the last run.",
            )
            return
        self._suppress_analysis_reload = True
        try:
            app.select_table_rows(self._last_outlier_table_rows)
        finally:
            QTimer.singleShot(300, self._end_suppress_analysis_reload)

    def _end_suppress_analysis_reload(self) -> None:
        self._suppress_analysis_reload = False

    def _sync_outlier_controls(self) -> None:
        idx = self.outlier_method.currentIndex()
        self.outlier_iqr_k.setEnabled(idx == 0)
        self.outlier_z_abs.setEnabled(idx == 1)
        self.outlier_mz_thr.setEnabled(idx == 2)

    def _outlier_row_label(self, i: int) -> str:
        if 0 <= i < len(self._df_raw) and "ID_HIDDEN" in self._df_raw.columns:
            raw = self._df_raw.iloc[i]["ID_HIDDEN"]
            s = str(raw).strip()
            if s and s.lower() != "nan":
                return f"ID_HIDDEN={s}"
        return f"row_index={i + 1}"

    def _run_outliers(self) -> None:
        self.refresh_table_data()
        self._last_outlier_table_rows = []
        if self._df_num.empty:
            self.outlier_text.setPlainText("No numeric columns in the current scope.")
            return
        choice = self.outlier_col.currentText()
        all_cols = choice == "All numeric columns"
        cols = list(self._df_num.columns) if all_cols else [choice]
        if not all_cols and (not choice or choice not in self._df_num.columns):
            self.outlier_text.setPlainText("Pick a numeric column.")
            return

        method = self.outlier_method.currentIndex()
        blocks: list[str] = []
        max_list = 500
        union_rows: set[int] = set()

        if not cols:
            self.outlier_text.setPlainText("No numeric columns in the current scope.")
            return

        for col in cols:
            lines: list[str] = []
            v = pd.to_numeric(self._df_num[col], errors="coerce").to_numpy(dtype=float)
            fin = np.isfinite(v)
            n_fin = int(np.sum(fin))

            if method == 0:
                k = float(self.outlier_iqr_k.value())
                mask = _outlier_mask_iqr(v, k=k)
                lines.append(f"Column: {col}")
                lines.append(f"Method: IQR (Tukey fences), k={k:g}")
                lines.append(f"n finite: {n_fin}")
                if n_fin >= 4:
                    xs = v[fin]
                    q1, q3 = np.percentile(xs, [25.0, 75.0])
                    iqr = float(q3 - q1)
                    lo, hi = q1 - k * iqr, q3 + k * iqr
                    lines.append(f"Q1={q1:g}, Q3={q3:g}, IQR={iqr:g}")
                    lines.append(f"Fences: [{lo:g}, {hi:g}]")
                else:
                    lines.append("(Fewer than 4 finite values — IQR fences are not applied.)")

            elif method == 1:
                zt = float(self.outlier_z_abs.value())
                mask = _outlier_mask_zscore(v, z=zt)
                lines.append(f"Column: {col}")
                lines.append(f"Method: Z-score, |Z| > {zt:g}")
                lines.append(f"n finite: {n_fin}")
                xs = v[fin]
                if xs.size >= 2:
                    mu, sig = float(np.mean(xs)), float(np.std(xs, ddof=1))
                    lines.append(f"mean={mu:g}, SD (sample)={sig:g}")
                else:
                    lines.append("(Need at least two finite values.)")

            else:
                thr = float(self.outlier_mz_thr.value())
                mask = _outlier_mask_modified_z(v, threshold=thr)
                lines.append(f"Column: {col}")
                lines.append(f"Method: modified Z (median & MAD), threshold={thr:g}")
                lines.append(f"n finite: {n_fin}")
                if n_fin >= 3:
                    med = float(np.median(v[fin]))
                    mad = float(np.median(np.abs(v[fin] - med)))
                    lines.append(f"median={med:g}, MAD={mad:g}")

            idxs = np.flatnonzero(mask)
            for ii in idxs:
                irow = int(ii)
                if 0 <= irow < len(self._scoped_source_rows):
                    union_rows.add(self._scoped_source_rows[irow])
            lines.append(f"Outliers flagged: {len(idxs)}")
            if len(idxs) > 0:
                lines.append("")
                lines.append(f"{'Label':<28} {'Value':>16}")
                n_show = min(len(idxs), max_list)
                for j in range(n_show):
                    ii = int(idxs[j])
                    lines.append(f"{self._outlier_row_label(ii):<28} {v[ii]:>16.8g}")
                if len(idxs) > max_list:
                    lines.append(f"... ({len(idxs) - max_list} more not shown)")

            blocks.append("\n".join(lines))

        self._last_outlier_table_rows = sorted(union_rows)
        self.outlier_text.setPlainText("\n\n".join(blocks).strip())

    def _run_curve_fit(self) -> None:
        self.refresh_table_data()
        xn = self.fit_x.currentText()
        yn = self.fit_y.currentText()
        if not xn or not yn or xn == yn:
            self.curve_text.setPlainText("Pick two different numeric columns.")
            return
        x = pd.to_numeric(self._df_num[xn], errors="coerce").to_numpy(dtype=float)
        y = pd.to_numeric(self._df_num[yn], errors="coerce").to_numpy(dtype=float)
        mask = np.isfinite(x) & np.isfinite(y)
        x, y = x[mask], y[mask]
        n = len(x)
        if n < 2:
            self.curve_text.setPlainText("Need at least two paired finite values.")
            return

        model_idx = self.fit_model.currentIndex()
        lines: list[str] = [f"N (finite pairs): {n}", ""]

        try:
            if model_idx == 0:
                deg = int(self.fit_poly_deg.value())
                coefs = np.polyfit(x, y, deg)
                y_hat = np.polyval(coefs, x)
                r2, rmse = _r2_rmse(y, y_hat)
                terms = []
                for i, c in enumerate(coefs):
                    p = deg - i
                    if p == 0:
                        terms.append(f"{c:.8g}")
                    elif p == 1:
                        terms.append(f"{c:.8g}*({xn})")
                    else:
                        terms.append(f"{c:.8g}*({xn})^{p}")
                eq = " + ".join(terms).replace("+ -", "- ")
                lines.append(f"Model: {yn} = {eq}")
                lines.append(f"Polynomial degree: {deg}")
                lines.append(f"R²: {r2:.8g}")
                lines.append(f"RMSE: {rmse:.8g}")
                lines.append("")
                lines.append("Coefficients (high degree first, NumPy polyfit convention):")
                lines.append(np.array2string(coefs, precision=8))

            elif model_idx == 1:
                try:
                    from scipy.optimize import curve_fit
                except ImportError as e:
                    self.curve_text.setPlainText(
                        "Exponential fitting requires SciPy. Install with: pip install scipy\n"
                        + str(e)
                    )
                    return

                if np.any(y <= 0):
                    self.curve_text.setPlainText(
                        "Exponential model requires all Y values to be positive."
                    )
                    return

                def exp_model(t, a, b):
                    return a * np.exp(b * t)

                p0 = (float(np.median(y)), 1e-4)
                popt, _pcov = curve_fit(exp_model, x, y, p0=p0, maxfev=200_000)
                a, b = float(popt[0]), float(popt[1])
                y_hat = exp_model(x, a, b)
                r2, rmse = _r2_rmse(y, y_hat)
                lines.append(f"Model: {yn} = {a:.8g} * exp({b:.8g} * ({xn}))")
                lines.append(f"R²: {r2:.8g}")
                lines.append(f"RMSE: {rmse:.8g}")

            elif model_idx == 2:
                if np.any(x <= 0):
                    self.curve_text.setPlainText(
                        "Log-X model requires all X values to be positive."
                    )
                    return
                lx = np.log(x)
                slope, intercept = np.polyfit(lx, y, 1)
                y_hat = slope * lx + intercept
                r2, rmse = _r2_rmse(y, y_hat)
                lines.append(f"Model: {yn} = {intercept:.8g} + {slope:.8g} * ln({xn})")
                lines.append(f"R²: {r2:.8g}")
                lines.append(f"RMSE: {rmse:.8g}")

            else:
                if np.any(x <= 0) or np.any(y <= 0):
                    self.curve_text.setPlainText(
                        "Power-law model requires all X and Y values to be positive."
                    )
                    return
                lx = np.log(x)
                ly = np.log(y)
                b, log_a = np.polyfit(lx, ly, 1)
                a = float(np.exp(log_a))
                b = float(b)
                y_hat = a * (x**b)
                r2, rmse = _r2_rmse(y, y_hat)
                lines.append(f"Model: {yn} = {a:.8g} * ({xn})^{b:.8g}  (fit in log-log space)")
                lines.append(f"R²: {r2:.8g}")
                lines.append(f"RMSE: {rmse:.8g}")

        except Exception as e:
            self.curve_text.setPlainText(f"Fit failed: {e}")
            return

        self.curve_text.setPlainText("\n".join(lines))

    def _run_stats_tests(self) -> None:
        self.refresh_table_data()
        try:
            from scipy import stats
        except Exception as e:
            self.stats_text.setPlainText(f"SciPy is not available: {e}")
            return

        idx = self.stats_test.currentIndex()
        lines: list[str] = []

        def col(name: str) -> np.ndarray:
            if name not in self._df_num.columns:
                return np.array([])
            return pd.to_numeric(self._df_num[name], errors="coerce").to_numpy(dtype=float)

        try:
            if idx == 4:
                an = self.stats_a.currentText()
                v = col(an)
                v = v[np.isfinite(v)]
                if len(v) < 3:
                    lines.append("Shapiro-Wilk needs at least 3 finite values.")
                else:
                    if len(v) > 5000:
                        lines.append(
                            "Note: using the first 5000 values (SciPy Shapiro-Wilk limit)."
                        )
                        v = v[:5000]
                    stat, p = stats.shapiro(v)
                    lines.append(f"Column: {an}")
                    lines.append(f"Shapiro-Wilk W = {stat:.8g}, p-value = {p:.4g}")
                    lines.append("(H0: data come from a normal distribution.)")

            elif idx == 3:
                an = self.stats_a.currentText()
                v = col(an)
                v = v[np.isfinite(v)]
                try:
                    mu0 = float((self.stats_mean.text() or "0").strip())
                except ValueError:
                    lines.append("Enter a numeric hypothesized mean.")
                else:
                    if len(v) < 2:
                        lines.append("Need at least two finite values.")
                    else:
                        res = stats.ttest_1samp(v, popmean=mu0, nan_policy="omit")
                        lines.append(f"Column: {an}  vs  H0 mean = {mu0}")
                        lines.append(
                            f"t = {float(res.statistic):.8g}, p-value (two-sided) = {float(res.pvalue):.4g}"
                        )
                        lines.append(f"n = {len(v)}")

            elif idx in (0, 1, 2):
                an, bn = self.stats_a.currentText(), self.stats_b.currentText()
                if not an or not bn or an == bn:
                    lines.append("Pick two different columns.")
                else:
                    ca, cb = col(an), col(bn)
                    paired_mask = np.isfinite(ca) & np.isfinite(cb)
                    a_p = ca[paired_mask]
                    b_p = cb[paired_mask]
                    if idx == 0:
                        if len(a_p) < 2:
                            lines.append("Need at least two paired finite values.")
                        else:
                            res = stats.ttest_rel(a_p, b_p, nan_policy="omit")
                            lines.append(f"Paired t-test: {an} vs {bn}")
                            lines.append(
                                f"t = {float(res.statistic):.8g}, p-value (two-sided) = {float(res.pvalue):.4g}"
                            )
                            lines.append(f"n (pairs) = {len(a_p)}")
                    elif idx == 1:
                        a_all = ca[np.isfinite(ca)]
                        b_all = cb[np.isfinite(cb)]
                        if len(a_all) < 2 or len(b_all) < 2:
                            lines.append("Each column needs at least two finite values.")
                        else:
                            res = stats.ttest_ind(a_all, b_all, equal_var=False, nan_policy="omit")
                            lines.append(f"Welch t-test (independent): {an} vs {bn}")
                            lines.append(
                                f"t = {float(res.statistic):.8g}, p-value (two-sided) = {float(res.pvalue):.4g}"
                            )
                            lines.append(f"n₁ = {len(a_all)}, n₂ = {len(b_all)}")
                    else:
                        a_all = ca[np.isfinite(ca)]
                        b_all = cb[np.isfinite(cb)]
                        if len(a_all) < 1 or len(b_all) < 1:
                            lines.append("Each column needs at least one finite value.")
                        else:
                            res = stats.mannwhitneyu(a_all, b_all, alternative="two-sided")
                            lines.append(f"Mann-Whitney U: {an} vs {bn}")
                            lines.append(
                                f"U = {float(res.statistic):.8g}, p-value (two-sided) = {float(res.pvalue):.4g}"
                            )
                            lines.append(f"n₁ = {len(a_all)}, n₂ = {len(b_all)}")
            else:
                lines.append("Unknown test.")

        except Exception as e:
            lines.append(f"Test failed: {e}")

        self.stats_text.setPlainText("\n".join(lines))
