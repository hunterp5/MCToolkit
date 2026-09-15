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
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from rdkit import Chem

from ...science_citations import protomer_dialog_footer_html
from ...services.column_labels import COLUMN_PARENT_OID, COLUMN_PROTOMER_SOURCE_OID_LEGACY
from ...utils import parse_molecule_from_cell_text
from ...workers import ProtomerGeneratorSignals, ProtomerGeneratorWorker
from ..analysis_job_support import enqueue_process_queue_job, prepare_scoped_structure_mols
from ..qt_widget_utils import make_window_minimizable
from .scope import selection_scope_checked


class ProtomerGeneratorDialog(QDialog):
    """Enumerate protomers from a Uni-pKa ionization ensemble and estimate populations at a target pH."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_app = parent
        self.setWindowTitle("Generate Protomers")
        self.setMinimumWidth(420)
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
        self.smiles_edit = QLineEdit()
        self.smiles_edit.setPlaceholderText("SMILES")
        sm_lyt.addWidget(self.smiles_edit)
        self._smiles_cfg.setVisible(False)
        root.addWidget(self._smiles_cfg)

        ph_row = QHBoxLayout()
        ph_row.setSpacing(6)
        ph_row.addWidget(QLabel("pH:"))
        self.ph_spin = QDoubleSpinBox()
        self.ph_spin.setRange(0.0, 14.0)
        self.ph_spin.setDecimals(2)
        self.ph_spin.setSingleStep(0.1)
        self.ph_spin.setValue(7.40)
        self.ph_spin.setToolTip("Target pH for approximate protomer population weights.")
        ph_row.addWidget(self.ph_spin)
        ph_row.addStretch()
        root.addLayout(ph_row)

        ref_lbl = QLabel(protomer_dialog_footer_html())
        ref_lbl.setWordWrap(True)
        ref_lbl.setTextFormat(Qt.RichText)
        ref_lbl.setOpenExternalLinks(True)
        ref_lbl.setStyleSheet("color: palette(mid); font-size: 11px;")
        root.addWidget(ref_lbl)

        gen_row = QHBoxLayout()
        gen_row.setSpacing(6)
        self.generate_btn = QPushButton("Generate")
        self.generate_btn.clicked.connect(self._on_generate)
        gen_row.addWidget(self.generate_btn)
        gen_row.addStretch()
        root.addLayout(gen_row)

        self.results_table = QTableWidget()
        self.results_table.setColumnCount(3)
        self.results_table.setHorizontalHeaderLabels(["Source OID", "SMILES", "% (approx.)"])
        self.results_table.horizontalHeader().setStretchLastSection(True)
        self.results_table.setMinimumHeight(160)
        root.addWidget(self.results_table, 1)

        add_row = QHBoxLayout()
        self.add_all_btn = QPushButton("Add all to main table")
        self.add_all_btn.clicked.connect(self._add_all_to_main)
        self.add_sel_btn = QPushButton("Add selected to main table")
        self.add_sel_btn.clicked.connect(self._add_selected_to_main)
        add_row.addWidget(self.add_all_btn)
        add_row.addWidget(self.add_sel_btn)
        add_row.addStretch()
        root.addLayout(add_row)

        self._prot_signals = ProtomerGeneratorSignals(self.parent_app)
        self._prot_signals.finished.connect(self._on_finished)
        self._prot_signals.failed.connect(self._on_failed)

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

    def _on_generate(self) -> None:
        if self.parent_app is None:
            return
        if self.mode_combo.currentIndex() == 1:
            smi = (self.smiles_edit.text() or "").strip()
            if not smi:
                QMessageBox.warning(self, "Generate Protomers", "Enter a SMILES string.")
                return
            mol = parse_molecule_from_cell_text(smi)
            if mol is None:
                QMessageBox.warning(self, "Generate Protomers", "Could not parse SMILES.")
                return
            rows: list[tuple[int | None, Chem.Mol | None]] = [(None, mol)]
        else:
            only_selected = selection_scope_checked(self)
            src = self.src_combo.currentText()
            rows_m = prepare_scoped_structure_mols(
                self.parent_app,
                tool_label="Generate Protomers",
                structure_source=src,
                only_selected=only_selected,
                empty_message="No valid structures were found for this scope and source.",
            )
            if not rows_m:
                return
            rows = list(rows_m)

        self.generate_btn.setEnabled(False)
        pH = float(self.ph_spin.value())
        n = len(rows)
        prog = self.parent_app._tool_progress_state
        enqueue_process_queue_job(
            self.parent_app,
            "Generate protomers",
            n,
            lambda ev, r=rows, ph=pH, ws=self.parent_app.signals, ps=self._prot_signals, st=prog: (
                ProtomerGeneratorWorker(r, ph, ws, ps, cancel_event=ev, progress_state=st)
            ),
            queue_label=f"Generate protomers ({n} molecules)",
        )

    def _on_finished(self, rows: list) -> None:
        self.generate_btn.setEnabled(True)
        self.results_table.setRowCount(0)
        rows_sorted = sorted(rows, key=lambda t: -float(t[2]))
        for src_oid, smi, pct in rows_sorted:
            r = self.results_table.rowCount()
            self.results_table.insertRow(r)
            oid_txt = "" if src_oid is None else str(int(src_oid))
            self.results_table.setItem(r, 0, QTableWidgetItem(oid_txt))
            self.results_table.setItem(r, 1, QTableWidgetItem(smi))
            self.results_table.setItem(r, 2, QTableWidgetItem(f"{pct:.2f}"))
        self.parent_app._finish_tool_progress(
            "Generate protomers",
            status_message=self.parent_app._consume_partial_results_notice() or "Ready.",
        )
        source_oids = {int(oid) for oid, _smi, _pct in rows if oid is not None}
        self._write_unipka_pka_for_oids(source_oids)

    def _on_failed(self, msg: str) -> None:
        self.generate_btn.setEnabled(True)
        self.parent_app._finish_tool_progress("Generate protomers")
        QMessageBox.warning(self, "Generate Protomers", msg or "Generation failed.")

    def _pka_for_source_oid(self, oid: int | None) -> str:
        if oid is None or self.parent_app is None:
            return "N/A"
        from molmanager.ionization import format_pka_values, pka_values_from_states
        from molmanager.microstate_cache import lookup as cache_lookup
        from molmanager.services.structure_grouping import structure_key

        mol = self.parent_app.mols.get(int(oid))
        if mol is None:
            row = self.parent_app._table_model.logical_row_for_oid(int(oid))
            if row >= 0:
                mol = self.parent_app._mol_for_structure_row(row)
        if mol is None:
            return "N/A"
        hit, states = cache_lookup(structure_key(mol))
        if not hit:
            return "N/A"
        return format_pka_values(pka_values_from_states(states))

    def _write_unipka_pka_for_oids(self, source_oids: set[int]) -> None:
        if not source_oids or self.parent_app is None:
            return
        rows = []
        for oid in sorted(source_oids):
            rows.append((int(oid), {"pKa": self._pka_for_source_oid(oid)}))
        if rows:
            self.parent_app.on_calc_finished(
                rows, ["pKa"], finish_progress=False, progress_label=None
            )

    def _unique_col(self, base: str) -> str:
        name = base
        i = 1
        while name in self.parent_app.headers:
            i += 1
            name = f"{base} ({i})"
        return name

    def _parent_oid_column(self) -> str:
        """Reuse existing lineage column when present (incl. legacy protomer header)."""
        headers = self.parent_app.headers
        if COLUMN_PARENT_OID in headers:
            return COLUMN_PARENT_OID
        if COLUMN_PROTOMER_SOURCE_OID_LEGACY in headers:
            return COLUMN_PROTOMER_SOURCE_OID_LEGACY
        return self._unique_col(COLUMN_PARENT_OID)

    def _add_rows_to_main(self, table_rows: set[int]) -> None:
        if not table_rows:
            return
        pct_col = self._unique_col("Protomer %")
        src_col = self._parent_oid_column()
        batch: list[tuple[str, dict[str, str]]] = []
        for r in sorted(table_rows):
            oid_item = self.results_table.item(r, 0)
            smi_item = self.results_table.item(r, 1)
            pct_item = self.results_table.item(r, 2)
            if smi_item is None or pct_item is None:
                continue
            smi = (smi_item.text() or "").strip()
            if not smi:
                continue
            oid_txt = (oid_item.text() if oid_item is not None else "").strip()
            pct_txt = (pct_item.text() or "").strip()
            fields = {pct_col: pct_txt, src_col: oid_txt}
            src_oid = int(oid_txt) if oid_txt.isdigit() else None
            fields["pKa"] = self._pka_for_source_oid(src_oid)
            batch.append((smi, fields))
        if not batch:
            return
        added = self.parent_app.add_rows_from_external_records_batch(batch)
        self.parent_app.status_label.setText(f"Added {added} protomer row(s) to the table.")

    def _add_all_to_main(self) -> None:
        n = self.results_table.rowCount()
        if n == 0:
            return
        self._add_rows_to_main(set(range(n)))

    def _add_selected_to_main(self) -> None:
        sel = {i.row() for i in self.results_table.selectedIndexes()}
        if not sel:
            QMessageBox.information(
                self, "Generate Protomers", "Select one or more rows in the results table."
            )
            return
        self._add_rows_to_main(sel)
