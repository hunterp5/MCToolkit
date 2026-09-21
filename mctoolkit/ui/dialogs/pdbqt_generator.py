# This file is part of mctoolkit.
# Copyright (C) 2026 Hunter Picard
#
# mctoolkit is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# mctoolkit is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with mctoolkit. If not, see <https://www.gnu.org/licenses/>.

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ...platform_support.session_log import record_ui_log
from ...workers.pdbqt_generator import PdbqtGenRequest, PdbqtGenSignals, PdbqtGeneratorWorker
from ..qt_widget_utils import apply_monospace_to_text_edit, make_window_minimizable

_LIGAND_MODES = (
    ("sdf", "SDF"),
    ("pdb", "PDB"),
    ("smiles", "SMILES"),
    ("rows", "Rows"),
)


def _path_row(edit: QLineEdit, on_browse) -> QWidget:
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


class PdbqtGeneratorDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.parent_app = parent
        self.setWindowTitle("Dock — Prepare PDBQT")
        self.setMinimumWidth(440)
        self.resize(480, 380)

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 6)
        root.setSpacing(6)

        rec_gb = QGroupBox("Receptor")
        rec_form = QFormLayout(rec_gb)
        rec_form.setContentsMargins(8, 4, 8, 4)
        rec_form.setSpacing(3)
        self.edit_rec_pdb = QLineEdit()
        self.edit_rec_pdb.setPlaceholderText("receptor.pdb")
        rec_form.addRow("Input PDB:", _path_row(self.edit_rec_pdb, self._browse_rec_pdb))
        self.edit_rec_out = QLineEdit()
        self.edit_rec_out.setPlaceholderText("receptor.pdbqt")
        rec_form.addRow("Output PDBQT:", _path_row(self.edit_rec_out, self._browse_rec_out))
        self.btn_rec_run = QPushButton("Generate PDBQT")
        self.btn_rec_run.setToolTip("Convert the receptor PDB to PDBQT (Meeko).")
        self.btn_rec_run.clicked.connect(self._on_run_receptor)
        rec_form.addRow("", self.btn_rec_run)
        root.addWidget(rec_gb)

        lig_gb = QGroupBox("Ligand")
        lig_form = QFormLayout(lig_gb)
        lig_form.setContentsMargins(8, 4, 8, 4)
        lig_form.setSpacing(3)

        self.lig_mode = QComboBox()
        for key, label in _LIGAND_MODES:
            self.lig_mode.addItem(label, key)
        self.lig_mode.setToolTip("SDF, ligand PDB, SMILES (one per line), or selected table rows.")
        lig_form.addRow("Input:", self.lig_mode)

        self._lig_stack = QStackedWidget()
        self.edit_lig_file = QLineEdit()
        self._lig_stack.addWidget(_path_row(self.edit_lig_file, self._browse_lig_file))

        self.smiles_edit = QTextEdit()
        self.smiles_edit.setPlaceholderText("One SMILES per line")
        self.smiles_edit.setMaximumHeight(56)
        apply_monospace_to_text_edit(self.smiles_edit)
        self._lig_stack.addWidget(self.smiles_edit)

        self.src_combo = QComboBox()
        if self.parent_app is not None:
            self.src_combo.addItems(self.parent_app.chemistry_tool_structure_sources())
        self._lig_stack.addWidget(self.src_combo)
        lig_form.addRow("", self._lig_stack)

        self.edit_lig_out = QLineEdit()
        self.edit_lig_out.setPlaceholderText("ligand.pdbqt")
        lig_form.addRow("Output PDBQT:", _path_row(self.edit_lig_out, self._browse_lig_out))
        self.btn_lig_run = QPushButton("Generate PDBQT")
        self.btn_lig_run.setToolTip(
            "Convert the ligand (SDF, PDB, SMILES, or table rows) to PDBQT (Meeko)."
        )
        self.btn_lig_run.clicked.connect(self._on_run_ligand)
        lig_form.addRow("", self.btn_lig_run)
        root.addWidget(lig_gb)

        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(80)
        self.log.setPlaceholderText("Log")
        apply_monospace_to_text_edit(self.log)
        root.addWidget(self.log, 1)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self.btn_close = QPushButton("Close")
        self.btn_close.clicked.connect(self.close)
        btn_row.addWidget(self.btn_close)
        root.addLayout(btn_row)

        self._jobs = 0
        self._signals = PdbqtGenSignals(self)
        self._signals.finished.connect(self._on_finished)
        self._signals.failed.connect(self._on_failed)
        self._signals.logged.connect(self._append_log)

        self.lig_mode.currentIndexChanged.connect(self._sync_mode_visibility)
        make_window_minimizable(self)
        self._sync_mode_visibility()

    def ligand_mode_key(self) -> str:
        return str(self.lig_mode.currentData() or "sdf")

    def _sync_mode_visibility(self, *_args) -> None:
        mode = self.ligand_mode_key()
        if mode in ("sdf", "pdb"):
            self._lig_stack.setCurrentIndex(0)
            if mode == "pdb":
                self.edit_lig_file.setPlaceholderText("ligand.pdb")
            else:
                self.edit_lig_file.setPlaceholderText("ligands.sdf")
        elif mode == "smiles":
            self._lig_stack.setCurrentIndex(1)
        else:
            self._lig_stack.setCurrentIndex(2)

    def _browse_rec_pdb(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Receptor PDB", "", "PDB (*.pdb);;All files (*.*)"
        )
        if path:
            self.edit_rec_pdb.setText(path)
            if not (self.edit_rec_out.text() or "").strip():
                self.edit_rec_out.setText(str(Path(path).with_suffix(".pdbqt")))

    def _browse_rec_out(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Receptor PDBQT", "", "PDBQT (*.pdbqt);;All files (*.*)"
        )
        if path:
            self.edit_rec_out.setText(path)

    def _browse_lig_file(self) -> None:
        mode = self.ligand_mode_key()
        if mode == "pdb":
            title, filt = "Ligand PDB", "PDB (*.pdb);;All files (*.*)"
        else:
            title, filt = "Ligand SDF", "SDF (*.sdf);;All files (*.*)"
        path, _ = QFileDialog.getOpenFileName(self, title, "", filt)
        if not path:
            return
        self.edit_lig_file.setText(path)
        if not (self.edit_lig_out.text() or "").strip():
            stem = Path(path).with_suffix(".pdbqt")
            self.edit_lig_out.setText(str(stem))

    def _browse_lig_out(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Ligand PDBQT", "", "PDBQT (*.pdbqt);;All files (*.*)"
        )
        if path:
            self.edit_lig_out.setText(path)

    def _append_log(self, text: str) -> None:
        t = (text or "").rstrip()
        if not t:
            return
        self.log.append(t)
        record_ui_log(t, name="mctoolkit.ui.pdbqt")

    def _selected_rows_mols(self, src: str) -> list[tuple[int, object]]:
        app = self.parent_app
        if app is None:
            return []
        allowed = app._selected_oids_set()
        if not allowed:
            return []
        rows = app.collect_scoped_structure_payloads(src, only_selected=True)
        return [(int(oid), mol) for oid, mol in rows if mol is not None]

    def _set_generate_enabled(self, enabled: bool) -> None:
        self.btn_rec_run.setEnabled(enabled)
        self.btn_lig_run.setEnabled(enabled)

    def _begin_job(self) -> None:
        self._jobs += 1
        self._set_generate_enabled(False)

    def _end_job(self) -> None:
        self._jobs = max(0, int(self._jobs) - 1)
        if self._jobs == 0:
            self._set_generate_enabled(True)

    def _enqueue(self, req: PdbqtGenRequest, title: str) -> None:
        app = self.parent_app
        if app is None:
            QMessageBox.warning(self, "Generate PDBQT", "Main window not available.")
            return
        self._begin_job()
        self._append_log(f"Starting {title}…")
        begin = getattr(app, "_begin_tool_progress", None)
        if callable(begin):
            begin(title, 1)
        app.process_queue.enqueue(
            title,
            lambda ev, r=req, sig=self._signals: PdbqtGeneratorWorker(
                r, signals=sig, cancel_event=ev
            ),
        )

    def _on_run_receptor(self) -> None:
        rec_in = (self.edit_rec_pdb.text() or "").strip()
        rec_out = (self.edit_rec_out.text() or "").strip()
        if rec_in and not rec_out:
            rec_out = str(Path(rec_in).with_suffix(".pdbqt"))
            self.edit_rec_out.setText(rec_out)
        if not rec_in:
            QMessageBox.information(self, "Generate PDBQT", "Choose a receptor PDB file.")
            return
        if not rec_out:
            QMessageBox.information(self, "Generate PDBQT", "Set a receptor PDBQT output path.")
            return
        if not Path(rec_in).is_file():
            QMessageBox.warning(self, "Generate PDBQT", f"Receptor PDB not found:\n{rec_in}")
            return
        req = PdbqtGenRequest(
            receptor_pdb_path=rec_in,
            receptor_pdbqt_out=rec_out,
            ligand_mode="sdf",
            ligand_sdf_path=None,
            ligand_smiles=None,
            ligand_rows=None,
            ligand_pdbqt_out=None,
        )
        self._enqueue(req, "Generate receptor PDBQT")

    def _on_run_ligand(self) -> None:
        ligand_mode = self.ligand_mode_key()
        ligand_rows = None
        ligand_smiles = None
        ligand_sdf = None
        ligand_pdb = None
        file_path = (self.edit_lig_file.text() or "").strip() or None

        if ligand_mode == "sdf":
            ligand_sdf = file_path
            if not ligand_sdf:
                QMessageBox.information(self, "Generate PDBQT", "Choose a ligand SDF file.")
                return
        elif ligand_mode == "pdb":
            ligand_pdb = file_path
            if not ligand_pdb:
                QMessageBox.information(self, "Generate PDBQT", "Choose a ligand PDB file.")
                return
        elif ligand_mode == "smiles":
            ligand_smiles = [
                s.strip() for s in (self.smiles_edit.toPlainText() or "").splitlines() if s.strip()
            ]
            if not ligand_smiles:
                QMessageBox.information(
                    self, "Generate PDBQT", "Enter at least one SMILES for ligand input."
                )
                return
        else:
            src = self.src_combo.currentText()
            ligand_rows = self._selected_rows_mols(src)
            if not ligand_rows:
                QMessageBox.information(
                    self, "Generate PDBQT", "Select ligand rows in the table first."
                )
                return

        lig_out = (self.edit_lig_out.text() or "").strip()
        if not lig_out and file_path:
            lig_out = str(Path(file_path).with_suffix(".pdbqt"))
            self.edit_lig_out.setText(lig_out)
        if not lig_out:
            QMessageBox.information(self, "Generate PDBQT", "Set a ligand PDBQT output path.")
            return

        req = PdbqtGenRequest(
            receptor_pdb_path=None,
            receptor_pdbqt_out=None,
            ligand_mode=ligand_mode,
            ligand_sdf_path=ligand_sdf,
            ligand_smiles=ligand_smiles,
            ligand_rows=ligand_rows,
            ligand_pdbqt_out=lig_out,
            ligand_pdb_path=ligand_pdb,
        )
        self._enqueue(req, "Generate ligand PDBQT")

    def _populate_open_smina_paths(self, receptor_pdbqt: str, ligand_pdbqt: str) -> None:
        """If Dock or Gnina dialogs are open, fill receptor/ligand path fields with generated PDBQT files."""
        app = self.parent_app
        if app is None:
            return
        dock = getattr(app, "_smina_dock_dialog", None)
        if dock is not None:
            try:
                if receptor_pdbqt and hasattr(dock, "edit_receptor"):
                    dock.edit_receptor.setText(receptor_pdbqt)
                if ligand_pdbqt and hasattr(dock, "edit_ligand"):
                    dock.edit_ligand.setText(ligand_pdbqt)
            except RuntimeError:
                pass

    def _finish_progress(self) -> None:
        app = self.parent_app
        if app is None:
            return
        finish = getattr(app, "_finish_tool_progress", None)
        if callable(finish):
            finish(status_message=None)

    def _on_finished(self, receptor_pdbqt: str, ligand_pdbqt: str) -> None:
        self._end_job()
        self._finish_progress()
        if receptor_pdbqt:
            self._append_log(f"Receptor PDBQT written: {receptor_pdbqt}")
        if ligand_pdbqt:
            self._append_log(f"Ligand PDBQT written: {ligand_pdbqt}")
        self._populate_open_smina_paths(receptor_pdbqt, ligand_pdbqt)

    def _on_failed(self, msg: str) -> None:
        self._end_job()
        self._finish_progress()
        self._append_log(msg or "PDBQT generation failed.")
