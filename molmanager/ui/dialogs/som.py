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

from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from rdkit import Chem

from ...science_citations import som_dialog_footer_html
from ...som_prediction import (
    DEFAULT_THRESHOLD,
    METABOLISM_SUBSET_OPTIONS,
)
from ...utils import parse_molecule_from_cell_text
from ...workers import SomPredictorWorker
from ..analysis_job_support import enqueue_process_queue_job, prepare_scoped_structure_mols
from ..qt_widget_utils import make_window_minimizable
from ..strings import TOOL_PREDICT_SOM
from .scope import selection_scope_checked


class SomPredictorDialog(QDialog):
    """Predict FAME3R sites of metabolism from a structure column or a SMILES string."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_app = parent
        self.setWindowTitle(TOOL_PREDICT_SOM)
        self.setMinimumWidth(360)
        n_sel = len(parent._selected_logical_rows()) if parent is not None else 0
        self._have_selection = n_sel > 0

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 6)
        root.setSpacing(4)

        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["Table rows", "SMILES string"])
        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        mode_row = QHBoxLayout()
        mode_row.setSpacing(6)
        mode_row.addWidget(QLabel("Input:"))
        mode_row.addWidget(self.mode_combo, 1)
        root.addLayout(mode_row)

        self._table_cfg = QWidget()
        tc_lyt = QVBoxLayout(self._table_cfg)
        tc_lyt.setContentsMargins(0, 0, 0, 0)
        tc_lyt.setSpacing(4)
        src_row = QHBoxLayout()
        src_row.setSpacing(6)
        src_row.addWidget(QLabel("Source:"))
        self.src_combo = QComboBox()
        self.src_combo.setMinimumWidth(160)
        src_row.addWidget(self.src_combo, 1)
        tc_lyt.addLayout(src_row)
        self.only_selected_cb = QCheckBox("Selected Rows Only")
        self._only_selected_scope_prefix = "Selected Rows Only"
        if self._have_selection:
            self.only_selected_cb.setText(f"{self._only_selected_scope_prefix} ({n_sel} row(s))")
        else:
            self.only_selected_cb.setEnabled(False)
        tc_lyt.addWidget(self.only_selected_cb)
        root.addWidget(self._table_cfg)

        self._smiles_cfg = QWidget()
        sm_lyt = QVBoxLayout(self._smiles_cfg)
        sm_lyt.setContentsMargins(0, 0, 0, 0)
        sm_lyt.setSpacing(4)
        self.smiles_edit = QLineEdit()
        self.smiles_edit.setPlaceholderText("SMILES")
        sm_lyt.addWidget(self.smiles_edit)
        self._smiles_cfg.setVisible(False)
        root.addWidget(self._smiles_cfg)

        sub_row = QHBoxLayout()
        sub_row.setSpacing(6)
        sub_row.addWidget(QLabel("Metabolism:"))
        self.subset_combo = QComboBox()
        for value, label in METABOLISM_SUBSET_OPTIONS:
            self.subset_combo.addItem(label, value)
        self.subset_combo.setToolTip(
            "FAME3R model family. Phase 1 and 2 runs two NERDD jobs (slower) "
            "and writes separate Phase 1 and Phase 2 site columns."
        )
        sub_row.addWidget(self.subset_combo, 1)
        root.addLayout(sub_row)

        thr_row = QHBoxLayout()
        thr_row.setSpacing(6)
        thr_row.addWidget(QLabel("SOM threshold:"))
        self.threshold_spin = QDoubleSpinBox()
        self.threshold_spin.setRange(0.05, 0.95)
        self.threshold_spin.setSingleStep(0.05)
        self.threshold_spin.setDecimals(2)
        self.threshold_spin.setValue(DEFAULT_THRESHOLD)
        self.threshold_spin.setToolTip(
            "Atoms with probability above this value are marked as sites of metabolism "
            "(FAME3R default is 0.30)."
        )
        thr_row.addWidget(self.threshold_spin)
        thr_row.addStretch()
        root.addLayout(thr_row)

        self.fame_score_cb = QCheckBox("Compute FAME score (applicability domain)")
        self.fame_score_cb.setToolTip(
            "Optional NERDD extra: similarity of each atom environment to the training set "
            "(0–1; higher is more reliable). Slows the job."
        )
        root.addWidget(self.fame_score_cb)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)
        self.predict_btn = QPushButton("Predict")
        self.predict_btn.clicked.connect(self._on_predict)
        btn_row.addWidget(self.predict_btn)
        btn_row.addStretch()
        root.addLayout(btn_row)

        ref_lbl = QLabel(som_dialog_footer_html())
        ref_lbl.setWordWrap(True)
        ref_lbl.setTextFormat(Qt.RichText)
        ref_lbl.setOpenExternalLinks(True)
        ref_lbl.setStyleSheet("color: palette(mid);")
        root.addWidget(ref_lbl)

        self._refresh_structure_sources()
        self.adjustSize()
        make_window_minimizable(self)

    def _refresh_structure_sources(self) -> None:
        self.src_combo.clear()
        if self.parent_app is None:
            return
        self.src_combo.addItems(self.parent_app.chemistry_tool_structure_sources())

    def _on_mode_changed(self, idx: int) -> None:
        is_smiles = idx == 1
        self._table_cfg.setVisible(not is_smiles)
        self._smiles_cfg.setVisible(is_smiles)

    def _on_predict(self) -> None:
        if self.parent_app is None:
            return
        if self.mode_combo.currentIndex() == 1:
            smi = (self.smiles_edit.text() or "").strip()
            if not smi:
                QMessageBox.warning(self, TOOL_PREDICT_SOM, "Enter a SMILES string.")
                return
            mol = parse_molecule_from_cell_text(smi)
            if mol is None:
                QMessageBox.warning(self, TOOL_PREDICT_SOM, "Could not parse SMILES.")
                return
            rows: list[tuple[int | None, Chem.Mol | None]] = [(None, mol)]
        else:
            only_selected = selection_scope_checked(self)
            src = self.src_combo.currentText()
            rows_m = prepare_scoped_structure_mols(
                self.parent_app,
                tool_label=TOOL_PREDICT_SOM,
                structure_source=src,
                only_selected=only_selected,
                empty_message="No valid structures were found for this scope and source.",
            )
            if not rows_m:
                return
            rows = list(rows_m)

        subset = str(self.subset_combo.currentData() or "all")
        threshold = float(self.threshold_spin.value())
        fame_score = bool(self.fame_score_cb.isChecked())
        som_signals = self.parent_app._ensure_som_predictor_signals()
        n = len(rows)
        prog = self.parent_app._tool_progress_state
        from ...display_constants import structure_depict_height, structure_depict_width

        enqueue_process_queue_job(
            self.parent_app,
            "Predict SOM",
            n,
            lambda ev, r=rows, ws=self.parent_app.signals, ps=som_signals, sub=subset, fs=fame_score, thr=threshold, st=prog, mw=structure_depict_width(), mh=structure_depict_height(): (
                SomPredictorWorker(
                    r,
                    ws,
                    ps,
                    cancel_event=ev,
                    metabolism_subset=sub,
                    fame_score=fs,
                    threshold=thr,
                    map_width=mw,
                    map_height=mh,
                    progress_state=st,
                )
            ),
            queue_label=f"Predict SOM ({n} molecules)",
        )
        self.close()
