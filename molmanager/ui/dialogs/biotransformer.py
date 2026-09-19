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
# along with MolManager. If not, see <https://www.gnu.org/licenses/>.

from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from rdkit import Chem

from ...predictions.biotransformer_metabolites import (
    DEFAULT_CYP_MODE,
    DEFAULT_MAX_METABOLITES,
    DEFAULT_NSTEPS,
    METABOLISM_OPTIONS,
    install_ready_message,
    uses_cyp_mode,
)
from ...platform_support.bundled_paths import (
    biotransformer_models_dir,
    resolve_biotransformer_jar,
    set_configured_biotransformer_jar,
)
from ...platform_support.memory_guards import check_product_enumeration, clamp_max_products_ui
from ...chem.molecule_conversion import parse_molecule_from_cell_text
from ...workers import BiotransformerWorker
from ..analysis_job_support import enqueue_process_queue_job, prepare_scoped_structure_mols
from ..qt_widget_utils import make_window_minimizable
from ..strings import TOOL_PREDICT_METABOLITES
from .scope import selection_scope_checked


class BiotransformerDialog(QDialog):
    """Predict BioTransformer metabolites from a structure column or a SMILES string."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_app = parent
        self.setWindowTitle(TOOL_PREDICT_METABOLITES)
        self.setMinimumWidth(380)
        n_sel = len(parent._selected_logical_rows()) if parent is not None else 0
        self._have_selection = n_sel > 0

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 6)
        root.setSpacing(4)

        self._install_lbl = QLabel("")
        self._install_lbl.setWordWrap(True)
        self._install_lbl.setStyleSheet("color: palette(mid);")
        root.addWidget(self._install_lbl)

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
        for value, label in METABOLISM_OPTIONS:
            self.subset_combo.addItem(label, value)
        self.subset_combo.setToolTip(
            "BioTransformer module. AllHuman covers host plus gut reactions at each step."
        )
        self.subset_combo.currentIndexChanged.connect(self._sync_cyp_mode)
        sub_row.addWidget(self.subset_combo, 1)
        root.addLayout(sub_row)

        step_row = QHBoxLayout()
        step_row.setSpacing(6)
        step_row.addWidget(QLabel("Steps:"))
        self.steps_spin = QSpinBox()
        self.steps_spin.setRange(1, 3)
        self.steps_spin.setValue(DEFAULT_NSTEPS)
        self.steps_spin.setToolTip("Maximum biotransformation generations (1–3).")
        step_row.addWidget(self.steps_spin)
        step_row.addWidget(QLabel("CYP mode:"))
        self.cyp_combo = QComboBox()
        self.cyp_combo.addItem("CypReact + rules", 1)
        self.cyp_combo.addItem("CyProduct only", 2)
        self.cyp_combo.addItem("Combined", 3)
        self.cyp_combo.setCurrentIndex(max(0, int(DEFAULT_CYP_MODE) - 1))
        step_row.addWidget(self.cyp_combo, 1)
        root.addLayout(step_row)

        cap_row = QHBoxLayout()
        cap_row.setSpacing(6)
        cap_row.addWidget(QLabel("Max metabolites:"))
        self.max_spin = QSpinBox()
        self.max_spin.setRange(1, clamp_max_products_ui(10_000))
        self.max_spin.setValue(min(DEFAULT_MAX_METABOLITES, clamp_max_products_ui(10_000)))
        self.max_spin.setToolTip("Cap products kept per parent molecule.")
        cap_row.addWidget(self.max_spin)
        cap_row.addStretch()
        root.addLayout(cap_row)

        self.add_rows_cb = QCheckBox("Add metabolites as new table rows")
        self.add_rows_cb.setToolTip(
            "Append each product as a new row with parent SMILES, reaction, and generation."
        )
        root.addWidget(self.add_rows_cb)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)
        self.browse_btn = QPushButton("Browse JAR…")
        self.browse_btn.setToolTip(
            "Point at an existing BioTransformer JAR. supportfiles/ and btkb/ (or database/) "
            "must sit next to it."
        )
        self.browse_btn.clicked.connect(self._browse_jar)
        btn_row.addWidget(self.browse_btn)
        self.install_btn = QPushButton("Install…")
        self.install_btn.setToolTip(
            "Download the official BioTransformer 3 package from Bitbucket (~120 MB)."
        )
        self.install_btn.clicked.connect(self._install_from_bitbucket)
        btn_row.addWidget(self.install_btn)
        btn_row.addStretch()
        self.predict_btn = QPushButton("Predict")
        self.predict_btn.clicked.connect(self._on_predict)
        btn_row.addWidget(self.predict_btn)
        root.addLayout(btn_row)

        self._refresh_structure_sources()
        self._sync_cyp_mode()
        self._refresh_install_state()
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

    def _sync_cyp_mode(self) -> None:
        metabolism = str(self.subset_combo.currentData() or "allHuman")
        self.cyp_combo.setEnabled(uses_cyp_mode(metabolism))

    def _refresh_install_state(self) -> None:
        msg = install_ready_message()
        jar = resolve_biotransformer_jar()
        if msg:
            self._install_lbl.setText(msg)
            self._install_lbl.setVisible(True)
            self.predict_btn.setEnabled(False)
        else:
            found = f"Using {jar}" if jar is not None else ""
            self._install_lbl.setText(found)
            self._install_lbl.setVisible(bool(found))
            self.predict_btn.setEnabled(True)
        need_package = msg is not None and (
            "JAR not found" in msg or "knowledge-base" in msg or "supportfiles" in msg
        )
        self.install_btn.setEnabled(need_package)

    def _browse_jar(self) -> None:
        start = biotransformer_models_dir()
        start.mkdir(parents=True, exist_ok=True)
        path, _ = QFileDialog.getOpenFileName(
            self,
            "BioTransformer JAR",
            str(start),
            "JAR files (*.jar);;All files (*.*)",
        )
        if not path:
            return
        set_configured_biotransformer_jar(path)
        self._refresh_install_state()

    def _install_from_bitbucket(self) -> None:
        dest = biotransformer_models_dir()
        reply = QMessageBox.question(
            self,
            TOOL_PREDICT_METABOLITES,
            "Download BioTransformer 3 (~120 MB) from Bitbucket into:\n\n"
            f"{dest}\n\n"
            "The files are LGPL-3 and are not stored in git. Continue?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if reply != QMessageBox.Yes:
            return
        from ...predictions.biotransformer_install import install_biotransformer

        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            jar = install_biotransformer(dest, progress=None)
        except Exception as exc:
            QMessageBox.warning(
                self,
                TOOL_PREDICT_METABOLITES,
                f"Could not install BioTransformer:\n{exc}\n\n"
                "Run: python scripts/bootstrap_biotransformer.py",
            )
            return
        finally:
            QApplication.restoreOverrideCursor()
        set_configured_biotransformer_jar(jar)
        self._refresh_install_state()
        still = install_ready_message()
        if still:
            QMessageBox.warning(self, TOOL_PREDICT_METABOLITES, still)
        else:
            QMessageBox.information(self, TOOL_PREDICT_METABOLITES, f"Installed:\n{jar}")

    def _on_predict(self) -> None:
        if self.parent_app is None:
            return
        missing = install_ready_message()
        if missing:
            QMessageBox.warning(self, TOOL_PREDICT_METABOLITES, missing)
            self._refresh_install_state()
            return
        metabolism = str(self.subset_combo.currentData() or "allHuman")
        nsteps = int(self.steps_spin.value())
        cyp_mode = int(self.cyp_combo.currentData() or DEFAULT_CYP_MODE)
        max_mets = int(self.max_spin.value())
        guard = check_product_enumeration(max_mets)
        if not guard.ok:
            QMessageBox.warning(self, TOOL_PREDICT_METABOLITES, guard.message)
            return
        add_as_rows = bool(self.add_rows_cb.isChecked())
        if self.mode_combo.currentIndex() == 1:
            smi = (self.smiles_edit.text() or "").strip()
            if not smi:
                QMessageBox.warning(self, TOOL_PREDICT_METABOLITES, "Enter a SMILES string.")
                return
            mol = parse_molecule_from_cell_text(smi)
            if mol is None:
                QMessageBox.warning(self, TOOL_PREDICT_METABOLITES, "Could not parse SMILES.")
                return
            rows: list[tuple[int | None, Chem.Mol | None]] = [(None, mol)]
        else:
            only_selected = selection_scope_checked(self)
            src = self.src_combo.currentText()
            rows_m = prepare_scoped_structure_mols(
                self.parent_app,
                tool_label=TOOL_PREDICT_METABOLITES,
                structure_source=src,
                only_selected=only_selected,
                empty_message="No valid structures were found for this scope and source.",
            )
            if not rows_m:
                return
            rows = list(rows_m)

        bt_signals = self.parent_app._ensure_biotransformer_signals()
        n = len(rows)
        prog = self.parent_app._tool_progress_state
        enqueue_process_queue_job(
            self.parent_app,
            TOOL_PREDICT_METABOLITES,
            n,
            lambda ev, r=rows, ws=self.parent_app.signals, ps=bt_signals, met=metabolism, st=nsteps, cm=cyp_mode, mx=max_mets, add=add_as_rows, prog_st=prog: (
                BiotransformerWorker(
                    r,
                    ws,
                    ps,
                    cancel_event=ev,
                    metabolism=met,
                    nsteps=st,
                    cyp_mode=cm,
                    max_metabolites=mx,
                    add_as_rows=add,
                    progress_state=prog_st,
                )
            ),
            queue_label=f"{TOOL_PREDICT_METABOLITES} ({n} molecules)",
        )
        self.close()
