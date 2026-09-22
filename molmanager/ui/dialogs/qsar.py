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

"""QSAR — quantitative structure–activity relationship modeling (Data menu)."""

from __future__ import annotations

from contextlib import suppress
from typing import TYPE_CHECKING, Any

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QCloseEvent
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ...analysis.qsar_models import (
    CLASSIFICATION_MODELS,
    REGRESSION_MODELS,
    QSARFitResult,
    param_specs_for_model,
)
from ...workers import SIMILARITY_FP_TYPE_LABELS
from ...workers.qsar_worker import QSARSignals, QSARPredictWorker, QSARTrainWorker
from ..table_dataframe import numeric_subset, table_to_dataframe
from ..qt_widget_utils import apply_monospace_to_text_edit, make_window_minimizable
from ..analysis_job_support import enqueue_process_queue_job
from .mmp import select_preferred_activity_column
from .scope import selection_scope_checked

if TYPE_CHECKING:
    from ..main_window import ChemistryWorkspaceWindow


class QSARDialog(QDialog):
    """Train ML models on table activity vs descriptors or fingerprints; write predictions to the table."""

    def __init__(self, parent: ChemistryWorkspaceWindow | None = None):
        super().__init__(parent)
        self.parent_app = parent
        self._init_qsar_state(parent)
        self._build_qsar_ui()
        self._wire_qsar_ui()
        self._reload_columns()
        self._on_fp_toggled()
        self._on_task_changed(self.task_combo.currentIndex())

    def _init_qsar_state(self, parent: ChemistryWorkspaceWindow | None) -> None:
        self.setWindowTitle("QSAR")
        self.setMinimumSize(720, 560)
        self.resize(900, 680)
        make_window_minimizable(self)
        n_sel = len(parent._selected_logical_rows()) if parent is not None else 0
        self._have_selection = n_sel > 0
        self._initial_selected_row_count = n_sel
        self._fit_result: QSARFitResult | None = None
        self._job_running = False
        self._active_progress_label = "QSAR"
        self._active_qsar_job_id: str | None = None
        self._param_widgets: dict[str, QWidget] = {}
        self._signals = QSARSignals(self)

    def _build_qsar_ui(self) -> None:
        n_sel = self._initial_selected_row_count
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 6)
        splitter = QSplitter(Qt.Horizontal)
        root.addWidget(splitter, 1)

        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_host = QWidget()
        left_lyt = QVBoxLayout(left_host)
        left_lyt.setSpacing(8)

        scope = QHBoxLayout()
        self.chk_visible = QCheckBox("Visible Rows Only")
        self.chk_visible.setChecked(True)
        scope.addWidget(self.chk_visible)
        self.only_selected_cb = QCheckBox("Selected Rows Only")
        self._only_selected_scope_prefix = "Selected Rows Only"
        if self._have_selection:
            self.only_selected_cb.setText(f"{self._only_selected_scope_prefix} ({n_sel} row(s))")
        else:
            self.only_selected_cb.setEnabled(False)
        scope.addWidget(self.only_selected_cb)
        scope.addStretch()
        self.btn_refresh = QPushButton("Refresh columns")
        scope.addWidget(self.btn_refresh)
        left_lyt.addLayout(scope)

        data_grp = QGroupBox("Activity (Y)")
        data_form = QFormLayout(data_grp)
        self.activity_combo = QComboBox()
        self.activity_combo.setMinimumWidth(200)
        data_form.addRow("Column:", self.activity_combo)
        self.task_combo = QComboBox()
        self.task_combo.addItems(["Auto", "Regression", "Classification"])
        self.task_combo.setToolTip(
            "Auto picks classification when activity has few discrete values; otherwise regression."
        )
        data_form.addRow("Task:", self.task_combo)
        left_lyt.addWidget(data_grp)

        feat_grp = QGroupBox("Features (X)")
        feat_lyt = QVBoxLayout(feat_grp)
        self.include_fp_cb = QCheckBox("Include 2D fingerprints (from structure)")
        self.include_fp_cb.setToolTip(
            "Concatenate a full fingerprint bit vector with any selected numeric columns."
        )
        feat_lyt.addWidget(self.include_fp_cb)

        fp_row = QHBoxLayout()
        fp_row.addWidget(QLabel("Fingerprint:"))
        self.fp_combo = QComboBox()
        self.fp_combo.addItems(SIMILARITY_FP_TYPE_LABELS)
        fp_row.addWidget(self.fp_combo, 1)
        feat_lyt.addLayout(fp_row)

        src_row = QHBoxLayout()
        src_row.addWidget(QLabel("Structure:"))
        self.struct_src_combo = QComboBox()
        src_row.addWidget(self.struct_src_combo, 1)
        feat_lyt.addLayout(src_row)

        col_btns = QHBoxLayout()
        self._btn_col_all = QPushButton("All")
        self._btn_col_none = QPushButton("None")
        col_btns.addWidget(self._btn_col_all)
        col_btns.addWidget(self._btn_col_none)
        col_btns.addStretch()
        feat_lyt.addLayout(col_btns)

        self.column_list = QListWidget()
        self.column_list.setMinimumHeight(120)
        self.column_list.setSelectionMode(QListWidget.NoSelection)
        feat_lyt.addWidget(self.column_list)
        left_lyt.addWidget(feat_grp)

        model_grp = QGroupBox("Model")
        model_form = QFormLayout(model_grp)
        self.model_combo = QComboBox()
        model_form.addRow("Algorithm:", self.model_combo)
        self.train_frac_spin = QDoubleSpinBox()
        self.train_frac_spin.setRange(0.5, 0.95)
        self.train_frac_spin.setSingleStep(0.05)
        self.train_frac_spin.setValue(0.8)
        self.train_frac_spin.setToolTip(
            "Fraction of labeled rows used for training (remainder is hold-out test)."
        )
        model_form.addRow("Train fraction:", self.train_frac_spin)
        self.cv_folds_spin = QSpinBox()
        self.cv_folds_spin.setRange(2, 10)
        self.cv_folds_spin.setValue(5)
        model_form.addRow("CV folds:", self.cv_folds_spin)
        self.standardize_cb = QCheckBox("Standardize numeric features")
        self.standardize_cb.setChecked(True)
        model_form.addRow("", self.standardize_cb)
        left_lyt.addWidget(model_grp)

        self.param_grp = QGroupBox("Parameters")
        self._param_form = QFormLayout(self.param_grp)
        self._param_hint = QLabel("Select an algorithm to edit its hyperparameters.")
        self._param_hint.setWordWrap(True)
        self._param_form.addRow(self._param_hint)
        left_lyt.addWidget(self.param_grp)

        out_grp = QGroupBox("Output")
        out_form = QFormLayout(out_grp)
        self.pred_column_edit = QLineEdit()
        self.pred_column_edit.setPlaceholderText("QSAR_<activity column>")
        out_form.addRow("Prediction column:", self.pred_column_edit)
        left_lyt.addWidget(out_grp)

        btn_row = QHBoxLayout()
        self.train_btn = QPushButton("Train & evaluate")
        btn_row.addWidget(self.train_btn)
        self.predict_btn = QPushButton("Add predictions to table")
        self.predict_btn.setEnabled(False)
        btn_row.addWidget(self.predict_btn)
        btn_row.addStretch()
        left_lyt.addLayout(btn_row)
        left_lyt.addStretch()

        left_scroll.setWidget(left_host)
        splitter.addWidget(left_scroll)

        right = QWidget()
        right_lyt = QVBoxLayout(right)
        right_lyt.addWidget(QLabel("Results"))
        self.results_text = QTextEdit()
        self.results_text.setReadOnly(True)
        apply_monospace_to_text_edit(self.results_text)
        self.results_text.setPlaceholderText(
            "Configure activity and features, then click Train & evaluate.\n\n"
            "Select numeric descriptor columns (e.g. MW, LogP) and/or 2D fingerprints. "
            "Requires scikit-learn (included with MolManager dependencies)."
        )
        right_lyt.addWidget(self.results_text, 1)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)

    def _wire_qsar_ui(self) -> None:
        self._signals.train_finished.connect(self._on_train_finished, Qt.QueuedConnection)
        self._signals.predict_finished.connect(self._on_predict_finished, Qt.QueuedConnection)
        self._signals.failed.connect(self._on_failed, Qt.QueuedConnection)
        self.chk_visible.stateChanged.connect(self._reload_columns)
        self.only_selected_cb.stateChanged.connect(self._reload_columns)
        self.btn_refresh.clicked.connect(self._reload_columns)
        self.task_combo.currentIndexChanged.connect(self._on_task_changed)
        self.include_fp_cb.stateChanged.connect(self._on_fp_toggled)
        self._btn_col_all.clicked.connect(self._select_all_columns)
        self._btn_col_none.clicked.connect(self._clear_column_checks)
        self.model_combo.currentIndexChanged.connect(self._rebuild_model_params)
        self.train_btn.clicked.connect(self._on_train)
        self.predict_btn.clicked.connect(self._on_predict)

    def _clear_param_form(self) -> None:
        while self._param_form.rowCount():
            self._param_form.removeRow(0)
        self._param_widgets.clear()

    def _rebuild_model_params(self, *_args) -> None:
        self._clear_param_form()
        model_key = self.model_combo.currentData()
        specs = param_specs_for_model(str(model_key)) if model_key else []
        if not specs:
            hint = QLabel("No tunable parameters for this algorithm.")
            hint.setWordWrap(True)
            self._param_form.addRow(hint)
            self.param_grp.setVisible(bool(model_key))
            return
        self.param_grp.setVisible(True)
        for spec in specs:
            key = str(spec["key"])
            label = str(spec.get("label") or key)
            kind = str(spec.get("kind") or "float")
            tip = str(spec.get("tooltip") or "")
            widget: QWidget
            if kind == "bool":
                widget = QCheckBox()
                widget.setChecked(bool(spec.get("default", False)))
            elif kind == "choice":
                combo = QComboBox()
                default = spec.get("default")
                for value, choice_label in spec.get("choices") or []:
                    combo.addItem(str(choice_label), value)
                idx = combo.findData(default)
                if idx >= 0:
                    combo.setCurrentIndex(idx)
                widget = combo
            elif kind == "int":
                spin = QSpinBox()
                spin.setRange(int(spec.get("min", 0)), int(spec.get("max", 1000)))
                spin.setValue(int(spec.get("default", 0)))
                widget = spin
            else:
                spin_f = QDoubleSpinBox()
                spin_f.setDecimals(int(spec.get("decimals", 4)))
                spin_f.setRange(float(spec.get("min", 0.0)), float(spec.get("max", 1e6)))
                spin_f.setValue(float(spec.get("default", 0.0)))
                widget = spin_f
            if tip:
                widget.setToolTip(tip)
            self._param_widgets[key] = widget
            self._param_form.addRow(f"{label}:", widget)

    def _collect_model_params(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key, widget in self._param_widgets.items():
            if isinstance(widget, QDoubleSpinBox):
                out[key] = float(widget.value())
            elif isinstance(widget, QSpinBox):
                out[key] = int(widget.value())
            elif isinstance(widget, QComboBox):
                out[key] = widget.currentData()
            elif isinstance(widget, QCheckBox):
                out[key] = bool(widget.isChecked())
        return out

    def _scoped_dataframe_and_oids(self) -> tuple:
        app = self.parent_app
        assert app is not None
        vis = self.chk_visible.isChecked()
        only_sel = selection_scope_checked(self)
        df, source_rows = table_to_dataframe(app, visible_only=vis, only_selected=only_sel)
        oids: list[int] = []
        for r in source_rows:
            t0 = app._table_model.cell_text(r, 0)
            oids.append(int(t0) if t0.isdigit() else int(r))
        return df, oids

    def _reload_columns(self) -> None:
        prev_act = self.activity_combo.currentText().strip()
        self.activity_combo.clear()
        self.column_list.clear()
        if self.parent_app is None:
            return
        self.struct_src_combo.clear()
        self.struct_src_combo.addItems(self.parent_app.chemistry_tool_structure_sources())
        df, _oids = self._scoped_dataframe_and_oids()
        num = numeric_subset(df, exclude_id=True)
        for col in num.columns:
            self.activity_combo.addItem(col)
            item = QListWidgetItem(col)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if num.shape[1] <= 10 else Qt.Unchecked)
            self.column_list.addItem(item)
        if self.activity_combo.count() <= 0:
            return
        if prev_act:
            idx = self.activity_combo.findText(prev_act)
            if idx >= 0:
                self.activity_combo.setCurrentIndex(idx)
            else:
                select_preferred_activity_column(self.activity_combo)
        else:
            select_preferred_activity_column(self.activity_combo)
        act = self.activity_combo.currentText()
        for i in range(self.column_list.count()):
            item = self.column_list.item(i)
            if item.text() == act:
                item.setCheckState(Qt.Unchecked)

    def _select_all_columns(self) -> None:
        act = self.activity_combo.currentText()
        for i in range(self.column_list.count()):
            item = self.column_list.item(i)
            if item.text() != act:
                item.setCheckState(Qt.Checked)

    def _clear_column_checks(self) -> None:
        for i in range(self.column_list.count()):
            self.column_list.item(i).setCheckState(Qt.Unchecked)

    def _selected_feature_columns(self) -> list[str]:
        act = self.activity_combo.currentText()
        cols: list[str] = []
        for i in range(self.column_list.count()):
            item = self.column_list.item(i)
            name = item.text()
            if name == act:
                continue
            if item.checkState() == Qt.Checked:
                cols.append(name)
        return cols

    def _on_fp_toggled(self, *_args) -> None:
        use_fp = self.include_fp_cb.isChecked()
        self.fp_combo.setEnabled(use_fp)
        self.struct_src_combo.setEnabled(use_fp)
        if use_fp and not self._selected_feature_columns():
            self.standardize_cb.setEnabled(False)
            self.standardize_cb.setChecked(False)
        else:
            self.standardize_cb.setEnabled(True)

    def _task_mode_key(self) -> str:
        t = self.task_combo.currentText().strip().lower()
        if t == "regression":
            return "regression"
        if t == "classification":
            return "classification"
        return "auto"

    def _on_task_changed(self, _index: int) -> None:
        mode = self._task_mode_key()
        self.model_combo.blockSignals(True)
        self.model_combo.clear()
        if mode == "classification":
            items = CLASSIFICATION_MODELS
        else:
            items = REGRESSION_MODELS
        for key, label in items.items():
            self.model_combo.addItem(label, key)
        if self.model_combo.count():
            self.model_combo.setCurrentIndex(0)
        self.model_combo.blockSignals(False)
        self._rebuild_model_params()

    def _collect_mols(self) -> list:
        app = self.parent_app
        assert app is not None
        return app.collect_scoped_table_mols(
            self.struct_src_combo.currentText(),
            only_selected=selection_scope_checked(self),
            only_visible=self.chk_visible.isChecked(),
        )

    def _validate_train_inputs(self) -> dict | None:
        app = self.parent_app
        if app is None:
            return None
        act = self.activity_combo.currentText().strip()
        if not act:
            QMessageBox.warning(self, "QSAR", "Select an activity column (Y).")
            return None
        use_fp = self.include_fp_cb.isChecked()
        feature_columns = self._selected_feature_columns()
        if not use_fp and not feature_columns:
            QMessageBox.warning(
                self,
                "QSAR",
                "Select at least one numeric feature column (X) and/or enable 2D fingerprints.",
            )
            return None
        mol_rows = self._collect_mols() if use_fp else None
        if use_fp and len(mol_rows or []) < 8 and not feature_columns:
            QMessageBox.information(
                self,
                "QSAR",
                "Need at least 8 rows with parseable structures when using fingerprints alone.",
            )
            return None
        df, oids = self._scoped_dataframe_and_oids()
        model_key = self.model_combo.currentData()
        if not model_key:
            QMessageBox.warning(self, "QSAR", "Select a model algorithm.")
            return None
        return {
            "dataframe": df,
            "oids": oids,
            "activity_column": act,
            "use_fingerprints": use_fp,
            "feature_columns": feature_columns or None,
            "fp_choice": self.fp_combo.currentText() if use_fp else None,
            "mol_rows": mol_rows,
            "model_key": str(model_key),
            "task_mode": self._task_mode_key(),
            "train_fraction": float(self.train_frac_spin.value()),
            "cv_folds": int(self.cv_folds_spin.value()),
            "standardize": bool(self.standardize_cb.isChecked()),
            "model_params": self._collect_model_params(),
        }

    def _set_job_running(self, running: bool) -> None:
        self._job_running = running
        self.train_btn.setEnabled(not running)
        self.predict_btn.setEnabled(not running and self._fit_result is not None)

    def _on_train(self) -> None:
        if self._job_running or self.parent_app is None:
            return
        params = self._validate_train_inputs()
        if params is None:
            return
        n = len(params["oids"])
        self._active_progress_label = "QSAR"
        self.results_text.setPlainText("Training…")
        self._set_job_running(True)
        self._fit_result = None
        self._disconnect_process_queue_thread_finished()
        self._active_qsar_job_id = enqueue_process_queue_job(
            self.parent_app,
            "QSAR",
            n,
            lambda ev, ps, p=params, sigs=self._signals: QSARTrainWorker(
                p, sigs, cancel_event=ev, progress_state=ps
            ),
            queue_label=f"QSAR train ({n} rows)",
        )
        self.parent_app.process_queue.thread_finished.connect(
            self._on_process_queue_thread_finished
        )

    def _on_predict(self) -> None:
        if self._job_running or self._fit_result is None or self.parent_app is None:
            return
        bundle = self._fit_result.bundle
        use_fp = bool(bundle.fp_choice)
        df, oids = self._scoped_dataframe_and_oids()
        out_col = self.pred_column_edit.text().strip() or f"QSAR_{self._fit_result.activity_column}"
        params = {
            "bundle": bundle,
            "dataframe": df,
            "oids": oids,
            "mol_rows": self._collect_mols() if use_fp else None,
            "output_column": out_col,
        }
        n = len(oids)
        self._active_progress_label = "QSAR predictions"
        self._set_job_running(True)
        self._disconnect_process_queue_thread_finished()
        self._active_qsar_job_id = enqueue_process_queue_job(
            self.parent_app,
            "QSAR predictions",
            n,
            lambda ev, ps, p=params, sigs=self._signals: QSARPredictWorker(
                p, sigs, cancel_event=ev, progress_state=ps
            ),
            queue_label=f"QSAR predict ({n} rows)",
        )
        self.parent_app.process_queue.thread_finished.connect(
            self._on_process_queue_thread_finished
        )

    def closeEvent(self, event: QCloseEvent) -> None:
        self._disconnect_process_queue_thread_finished()
        super().closeEvent(event)

    def _disconnect_process_queue_thread_finished(self) -> None:
        pa = self.parent_app
        if pa is None:
            return
        with suppress(TypeError):
            pa.process_queue.thread_finished.disconnect(self._on_process_queue_thread_finished)

    def _on_process_queue_thread_finished(self, job_id: str) -> None:
        if job_id != self._active_qsar_job_id or not self._job_running:
            return
        self._active_qsar_job_id = None
        self._reset_after_job_failure("Cancelled.")

    def _reset_after_job_failure(self, msg: str) -> None:
        if self.parent_app is not None:
            self.parent_app._finish_tool_progress(self._active_progress_label)
        self._set_job_running(False)
        self._disconnect_process_queue_thread_finished()
        if msg and msg != "Cancelled.":
            self.results_text.append(f"\n\nError: {msg}")
        if msg:
            QMessageBox.warning(self, "QSAR", msg)

    def _on_train_finished(self, result: object) -> None:
        self._active_qsar_job_id = None
        self._disconnect_process_queue_thread_finished()
        self.parent_app._finish_tool_progress("QSAR", status_message=None)
        self._set_job_running(False)
        if not isinstance(result, QSARFitResult):
            return
        self._fit_result = result
        self.results_text.setPlainText(result.metrics_text)
        pred_name = self.pred_column_edit.text().strip() or f"QSAR_{result.activity_column}"
        self.pred_column_edit.setText(pred_name)
        self.predict_btn.setEnabled(True)
        if self.parent_app is not None:
            self.parent_app.status_label.setText(
                f"QSAR: trained {result.model_key} on {result.n_train} rows "
                f"({result.n_features} features)."
            )

    def _on_predict_finished(self, rows: list) -> None:
        self._active_qsar_job_id = None
        self._disconnect_process_queue_thread_finished()
        self.parent_app._finish_tool_progress("QSAR predictions", status_message=None)
        self._set_job_running(False)
        if not rows or self.parent_app is None or self._fit_result is None:
            QMessageBox.information(
                self,
                "QSAR",
                "No rows received predictions (missing features or structures).",
            )
            return
        col = self.pred_column_edit.text().strip() or f"QSAR_{self._fit_result.activity_column}"
        res = [(int(oid), {col: next(iter(vals.values()), "N/A")}) for oid, vals in rows]
        self.parent_app.on_calc_finished(res, [col], progress_label="QSAR")
        QMessageBox.information(
            self,
            "QSAR",
            f"Added column “{col}” with predictions for {len(res):,} row(s).",
        )

    def _on_failed(self, msg: str) -> None:
        self._active_qsar_job_id = None
        self._reset_after_job_failure(msg or "QSAR failed.")
