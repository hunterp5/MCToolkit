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

from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ...platform_support.session_log import record_ui_log
from ...workers.pdb_fixer import PdbFixerRequest, PdbFixerSignals, PdbFixerWorker
from ..qt_widget_utils import apply_monospace_to_text_edit, make_window_minimizable


def _browse_path_row(edit: QLineEdit, on_browse) -> QWidget:
    row = QHBoxLayout()
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(4)
    row.addWidget(edit, 1)
    btn = QPushButton("Browse…")
    btn.setFixedWidth(76)
    btn.clicked.connect(on_browse)
    row.addWidget(btn)
    wrap = QWidget()
    wrap.setLayout(row)
    return wrap


class PdbFixerDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.parent_app = parent
        self.setWindowTitle("Dock — Prepare PDB")
        self.setMinimumWidth(460)
        self.resize(500, 400)

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 6)
        root.setSpacing(6)

        io_gb = QGroupBox("Receptor PDB")
        io_form = QFormLayout(io_gb)
        io_form.setContentsMargins(8, 6, 8, 6)
        io_form.setSpacing(4)

        self.edit_in = QLineEdit()
        self.edit_in.setPlaceholderText("receptor.pdb")
        io_form.addRow("Input:", _browse_path_row(self.edit_in, self._browse_input))

        self.edit_out = QLineEdit()
        self.edit_out.setPlaceholderText("receptor_prepared.pdb")
        io_form.addRow("Output:", _browse_path_row(self.edit_out, self._browse_output))
        root.addWidget(io_gb)

        opt_gb = QGroupBox("Options")
        opt_form = QFormLayout(opt_gb)
        opt_form.setContentsMargins(8, 6, 8, 6)
        opt_form.setSpacing(4)
        self.chk_remove_heterogens = QCheckBox("Remove heterogens (ligands, ions, buffers)")
        self.chk_remove_heterogens.setChecked(True)
        self.chk_remove_heterogens.toggled.connect(self._sync_water_enabled)
        opt_form.addRow(self.chk_remove_heterogens)

        self.chk_keep_water = QCheckBox("Keep crystallographic waters")
        self.chk_keep_water.setChecked(False)
        opt_form.addRow(self.chk_keep_water)

        self.chk_replace_nonstandard = QCheckBox("Replace non-standard residues (e.g. MSE → MET)")
        self.chk_replace_nonstandard.setChecked(True)
        opt_form.addRow(self.chk_replace_nonstandard)

        self.chk_add_missing_atoms = QCheckBox("Add missing heavy atoms in existing residues")
        self.chk_add_missing_atoms.setChecked(True)
        opt_form.addRow(self.chk_add_missing_atoms)

        self.chk_skip_long_gaps = QCheckBox("Skip long missing stretches")
        self.chk_skip_long_gaps.setChecked(True)
        self.chk_skip_long_gaps.setToolTip(
            "Do not rebuild SEQRES gaps longer than the residue limit (N-terminal "
            "tags and disordered loops). PDBFixer cannot place those stretches well."
        )
        self.spin_max_gap = QSpinBox()
        self.spin_max_gap.setRange(0, 80)
        self.spin_max_gap.setValue(8)
        self.spin_max_gap.setSuffix(" res")
        gap_row = QWidget()
        gap_l = QHBoxLayout(gap_row)
        gap_l.setContentsMargins(0, 0, 0, 0)
        gap_l.addWidget(self.chk_skip_long_gaps, 1)
        gap_l.addWidget(self.spin_max_gap)
        opt_form.addRow(gap_row)

        self.chk_add_hydrogens = QCheckBox("Add missing hydrogens at pH")
        self.chk_add_hydrogens.setChecked(True)
        self.chk_add_hydrogens.toggled.connect(self._sync_ph_enabled)
        opt_form.addRow(self.chk_add_hydrogens)

        self.spin_ph = QDoubleSpinBox()
        self.spin_ph.setRange(0.0, 14.0)
        self.spin_ph.setDecimals(1)
        self.spin_ph.setSingleStep(0.1)
        self.spin_ph.setValue(7.0)
        opt_form.addRow("pH:", self.spin_ph)
        root.addWidget(opt_gb)

        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(90)
        self.log.setPlaceholderText("Log")
        apply_monospace_to_text_edit(self.log)
        root.addWidget(self.log, 1)

        btn_row = QHBoxLayout()
        self.btn_run = QPushButton("Prepare PDB")
        self.btn_run.clicked.connect(self._on_run)
        btn_row.addWidget(self.btn_run)
        btn_row.addStretch()
        self.btn_close = QPushButton("Close")
        self.btn_close.clicked.connect(self.close)
        btn_row.addWidget(self.btn_close)
        root.addLayout(btn_row)

        self._signals = PdbFixerSignals(self)
        self._signals.finished.connect(self._on_finished)
        self._signals.failed.connect(self._on_failed)

        make_window_minimizable(self)
        self.chk_skip_long_gaps.toggled.connect(self.spin_max_gap.setEnabled)
        self.spin_max_gap.setEnabled(self.chk_skip_long_gaps.isChecked())
        self._sync_water_enabled()
        self._sync_ph_enabled()

    def _sync_water_enabled(self, *_args) -> None:
        self.chk_keep_water.setEnabled(self.chk_remove_heterogens.isChecked())

    def _sync_ph_enabled(self, *_args) -> None:
        self.spin_ph.setEnabled(self.chk_add_hydrogens.isChecked())

    def _suggest_output_path(self, input_path: str) -> None:
        path = Path(input_path)
        if not path.suffix:
            return
        suggested = path.with_name(f"{path.stem}_prepared{path.suffix}")
        if not (self.edit_out.text() or "").strip():
            self.edit_out.setText(str(suggested))

    def _browse_input(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Receptor PDB", "", "PDB (*.pdb);;All files (*.*)"
        )
        if path:
            self.edit_in.setText(path)
            self._suggest_output_path(path)

    def _browse_output(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Prepared receptor PDB", "", "PDB (*.pdb);;All files (*.*)"
        )
        if path:
            self.edit_out.setText(path)

    def _append_log(self, text: str) -> None:
        t = (text or "").rstrip()
        if not t:
            return
        self.log.append(t)
        record_ui_log(t, name="molmanager.ui.pdb_fixer")

    def _populate_open_prepare_paths(self, output_pdb: str) -> None:
        app = self.parent_app
        pdbqt = getattr(app, "_pdbqt_generator_dialog", None) if app is not None else None
        if pdbqt is None:
            return
        try:
            if output_pdb and hasattr(pdbqt, "edit_rec_pdb"):
                pdbqt.edit_rec_pdb.setText(output_pdb)
        except RuntimeError:
            pass

    def _on_run(self) -> None:
        app = self.parent_app
        in_path = (self.edit_in.text() or "").strip()
        out_path = (self.edit_out.text() or "").strip()
        if not in_path:
            QMessageBox.information(self, "Prepare PDB", "Select an input PDB file.")
            return
        if not out_path:
            QMessageBox.information(self, "Prepare PDB", "Set an output PDB path.")
            return
        if app is None:
            QMessageBox.warning(self, "Prepare PDB", "Main window not available.")
            return

        req = PdbFixerRequest(
            input_pdb_path=in_path,
            output_pdb_path=out_path,
            remove_heterogens=self.chk_remove_heterogens.isChecked(),
            keep_water=self.chk_keep_water.isChecked(),
            replace_nonstandard=self.chk_replace_nonstandard.isChecked(),
            add_missing_atoms=self.chk_add_missing_atoms.isChecked(),
            add_hydrogens=self.chk_add_hydrogens.isChecked(),
            ph=float(self.spin_ph.value()),
            skip_long_gaps=self.chk_skip_long_gaps.isChecked(),
            max_missing_gap=int(self.spin_max_gap.value()),
        )

        self.btn_run.setEnabled(False)
        self._append_log("Starting PDB preparation with PDBFixer…")
        begin = getattr(app, "_begin_tool_progress", None)
        if callable(begin):
            begin("Prepare PDB", 1)
        app.process_queue.enqueue(
            "Prepare PDB",
            lambda ev, r=req, sig=self._signals: PdbFixerWorker(r, signals=sig, cancel_event=ev),
        )

    def _on_finished(self, output_pdb: str) -> None:
        self.btn_run.setEnabled(True)
        app = self.parent_app
        if app is not None:
            finish = getattr(app, "_finish_tool_progress", None)
            if callable(finish):
                finish("Prepare PDB", status_message=None)
        self._append_log(f"Prepared PDB written: {output_pdb}")
        self._populate_open_prepare_paths(output_pdb)

    def _on_failed(self, msg: str) -> None:
        self.btn_run.setEnabled(True)
        app = self.parent_app
        if app is not None:
            finish = getattr(app, "_finish_tool_progress", None)
            if callable(finish):
                finish("Prepare PDB", status_message=None)
        self._append_log(msg or "PDB preparation failed.")
