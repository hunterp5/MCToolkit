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
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from rdkit import Chem

from ...science_citations import pka_dialog_footer_html
from ...utils import parse_molecule_from_cell_text
from ...workers import PKaPredictorWorker
from ..qt_widget_utils import make_window_minimizable
from .scope import selection_scope_checked


class PKaPredictorDialog(QDialog):
    """Predict macro pKa values (Uni-pKa) from a structure column or a SMILES string."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_app = parent
        self.setWindowTitle("Predict pKa")
        self.setMinimumWidth(320)
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

        self.most_basic_only_cb = QCheckBox("Only calculate most basic pKa")
        self.most_basic_only_cb.setToolTip(
            "When checked, write a single value: the highest predicted pKa (strongest base / "
            "most basic ionization step). Otherwise all macro pKas are listed."
        )
        self.most_basic_only_cb.toggled.connect(self._on_most_basic_toggled)
        root.addWidget(self.most_basic_only_cb)

        self.most_acidic_only_cb = QCheckBox("Only calculate most acidic pKa")
        self.most_acidic_only_cb.setToolTip(
            "When checked, write a single value: the lowest predicted pKa (strongest acid / "
            "most acidic ionization step)."
        )
        self.most_acidic_only_cb.toggled.connect(self._on_most_acidic_toggled)
        root.addWidget(self.most_acidic_only_cb)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)
        self.predict_btn = QPushButton("Predict")
        self.predict_btn.clicked.connect(self._on_predict)
        btn_row.addWidget(self.predict_btn)
        btn_row.addStretch()
        root.addLayout(btn_row)

        ref_lbl = QLabel(pka_dialog_footer_html())
        ref_lbl.setWordWrap(True)
        ref_lbl.setTextFormat(Qt.RichText)
        ref_lbl.setOpenExternalLinks(True)
        ref_lbl.setStyleSheet("color: palette(mid);")
        root.addWidget(ref_lbl)

        self._refresh_structure_sources()
        self.adjustSize()
        make_window_minimizable(self)

    def _on_most_basic_toggled(self, on: bool) -> None:
        if on:
            self.most_acidic_only_cb.blockSignals(True)
            self.most_acidic_only_cb.setChecked(False)
            self.most_acidic_only_cb.blockSignals(False)

    def _on_most_acidic_toggled(self, on: bool) -> None:
        if on:
            self.most_basic_only_cb.blockSignals(True)
            self.most_basic_only_cb.setChecked(False)
            self.most_basic_only_cb.blockSignals(False)

    def _refresh_structure_sources(self) -> None:
        self.src_combo.clear()
        if self.parent_app is None:
            return
        self.src_combo.addItems(self.parent_app.chemistry_tool_structure_sources())

    def _on_mode_changed(self, idx: int) -> None:
        is_smiles = idx == 1
        self._table_cfg.setVisible(not is_smiles)
        self._smiles_cfg.setVisible(is_smiles)

    def _collect_table_mols(self, src: str, only_selected: bool) -> list[tuple[int, Chem.Mol]]:
        return self.parent_app.collect_scoped_table_mols(src, only_selected=only_selected)

    def _on_predict(self) -> None:
        if self.parent_app is None:
            return
        if self.mode_combo.currentIndex() == 1:
            smi = (self.smiles_edit.text() or "").strip()
            if not smi:
                QMessageBox.warning(self, "Predict pKa", "Enter a SMILES string.")
                return
            mol = parse_molecule_from_cell_text(smi)
            if mol is None:
                QMessageBox.warning(self, "Predict pKa", "Could not parse SMILES.")
                return
            rows: list[tuple[int | None, Chem.Mol | None]] = [(None, mol)]
        else:
            only_selected = selection_scope_checked(self)
            allowed = self.parent_app._selected_oids_set() if only_selected else None
            if only_selected and not allowed:
                QMessageBox.warning(
                    self,
                    "Predict pKa",
                    "\u201cSelected Rows Only\u201d is checked but nothing is selected.",
                )
                return
            src = self.src_combo.currentText()
            rows_m = self._collect_table_mols(src, only_selected)
            if not rows_m:
                QMessageBox.information(
                    self,
                    "Predict pKa",
                    "No valid structures were found for this scope and source.",
                )
                return
            rows = list(rows_m)

        most_basic = bool(self.most_basic_only_cb.isChecked())
        most_acidic = bool(self.most_acidic_only_cb.isChecked())
        pka_signals = self.parent_app._ensure_pka_predictor_signals()
        n = len(rows)
        prog = self.parent_app._tool_progress_state
        self.parent_app._begin_tool_progress("pKa prediction", n)
        self.parent_app.process_queue.enqueue(
            f"pKa prediction ({n} molecules)",
            lambda ev, r=rows, ws=self.parent_app.signals, ps=pka_signals, mb=most_basic, ma=most_acidic, st=prog: (
                PKaPredictorWorker(
                    r,
                    ws,
                    ps,
                    cancel_event=ev,
                    most_basic_only=mb,
                    most_acidic_only=ma,
                    progress_state=st,
                )
            ),
        )
        self.close()
