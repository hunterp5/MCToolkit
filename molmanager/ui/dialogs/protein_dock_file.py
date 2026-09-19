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
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with MolManager. If not, see <https://www.gnu.org/licenses/>.

"""Protein Viewer Dock File dialog: write Gnina files and open the docking menu."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from ...workers.protein_dock_file import (
    DockFileRequest,
    DockFileSignals,
    DockFileWorker,
)
from ..qt_widget_utils import append_viewer_log, make_window_minimizable
from .protein_source_picker import (
    ProteinStructureSourceMixin,
    _PREPARE_SOURCE_FMTS,
    _browse_path_row,
)

_PREPARE_FMTS = _PREPARE_SOURCE_FMTS


class ProteinDockFileDialog(ProteinStructureSourceMixin, QDialog):
    """Options for Protein Viewer → Tools → Prepare → Dock File."""

    smina_prepared = Signal(object)
    _source_output_tag = "smina"
    _source_output_suffix = ".pdbqt"
    _source_tmp_prefix = "molmanager_dock_file_in_"
    _source_tool_title = "Dock File"
    _source_empty_message = "Choose a Manager structure or a PDB/mmCIF file."

    def __init__(self, viewer, parent=None) -> None:
        super().__init__(parent or viewer)
        self._viewer = viewer
        self.setWindowTitle("Dock File")
        self.setMinimumWidth(500)
        self.resize(540, 420)

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 6)
        root.setSpacing(6)

        io_gb = QGroupBox("Structure")
        io_form = QFormLayout(io_gb)
        io_form.setContentsMargins(8, 6, 8, 6)
        io_form.setSpacing(4)
        self._add_structure_source_rows(io_form)
        self.edit_out = QLineEdit()
        self.edit_out.setPlaceholderText("receptor_smina.pdbqt")
        self.edit_out.setToolTip(
            "Apo receptor PDBQT written for Gnina (ligand and waters stripped). "
            "Crystal ligand SDF/PDB and the search box are written beside it."
        )
        io_form.addRow("Output:", _browse_path_row(self.edit_out, self._browse_output))
        root.addWidget(io_gb)

        smina_gb = QGroupBox("Gnina docking")
        smina_form = QFormLayout(smina_gb)
        smina_form.setContentsMargins(8, 6, 8, 6)
        smina_form.setSpacing(4)
        self.radio_box_loaded = QRadioButton("Loaded structure")
        self.radio_box_loaded.setToolTip(
            "Build the search box from a ligand already in the Protein Viewer "
            "(the structure being exported, or another loaded file in the same frame)."
        )
        self.radio_box_file = QRadioButton("Ligand file…")
        self.radio_box_file.setToolTip(
            "Build the search box from a separate PDB, SDF, MOL2, or PDBQT. Use this "
            "when the ligand is not in the structure being exported."
        )
        self.radio_box_loaded.setChecked(True)
        box_src_group = QButtonGroup(self)
        box_src_group.addButton(self.radio_box_loaded)
        box_src_group.addButton(self.radio_box_file)
        box_src_row = QWidget()
        box_src_l = QHBoxLayout(box_src_row)
        box_src_l.setContentsMargins(0, 0, 0, 0)
        box_src_l.setSpacing(12)
        box_src_l.addWidget(self.radio_box_loaded)
        box_src_l.addWidget(self.radio_box_file)
        box_src_l.addStretch()
        smina_form.addRow("Box from:", box_src_row)
        self.combo_box_ligand = QComboBox()
        self.combo_box_ligand.setToolTip(
            "Ligand whose coordinates define the search box. Defaults to the Manager "
            "selection, or the largest ligand among loaded structures."
        )
        smina_form.addRow("Ligand in structure:", self.combo_box_ligand)
        self.edit_box_ligand = QLineEdit()
        self.edit_box_ligand.setPlaceholderText("PDB, SDF, MOL2, or PDBQT")
        self.edit_box_ligand.setToolTip(
            "Coordinates must be in the same frame as the receptor. Crystal ligand "
            "or a reference pose both work."
        )
        self.box_ligand_file_row = _browse_path_row(self.edit_box_ligand, self._browse_box_ligand)
        smina_form.addRow("Ligand file:", self.box_ligand_file_row)
        self.spin_box_padding = QDoubleSpinBox()
        self.spin_box_padding.setRange(0.0, 20.0)
        self.spin_box_padding.setDecimals(1)
        self.spin_box_padding.setSingleStep(0.5)
        self.spin_box_padding.setValue(4.0)
        self.spin_box_padding.setSuffix(" Å")
        self.spin_box_padding.setToolTip(
            "Padding added on each side of the ligand bounding box (Gnina --autobox_add)."
        )
        smina_form.addRow("Box padding:", self.spin_box_padding)
        self.lbl_box_preview = QLabel("Box: —")
        self.lbl_box_preview.setWordWrap(True)
        smina_form.addRow(self.lbl_box_preview)
        root.addWidget(smina_gb)
        root.addStretch()

        self.radio_box_loaded.toggled.connect(self._sync_smina_options)
        self.radio_box_file.toggled.connect(self._sync_smina_options)
        self._sync_smina_options()

        btn_row = QHBoxLayout()
        self.btn_run = QPushButton("Write & Open Gnina")
        self.btn_run.setToolTip(
            "Write an apo receptor PDBQT, crystal ligand, and search box, then open "
            "Protein → Dock Ligand → Gnina with the receptor, box, and crystal ligand "
            "for internal validation. The docking ligand field is left empty."
        )
        self.btn_run.clicked.connect(self._on_run)
        btn_row.addWidget(self.btn_run)
        self.btn_open_smina = QPushButton("Open Gnina…")
        self.btn_open_smina.setEnabled(False)
        self.btn_open_smina.setToolTip(
            "Re-open Protein → Dock Ligand → Gnina with the last written receptor, box, "
            "and crystal ligand (internal validation). The docking ligand field is left "
            "empty so you can choose compounds to dock."
        )
        self.btn_open_smina.clicked.connect(self._on_open_smina)
        btn_row.addWidget(self.btn_open_smina)
        btn_row.addStretch()
        self.btn_close = QPushButton("Close")
        self.btn_close.clicked.connect(self.close)
        btn_row.addWidget(self.btn_close)
        root.addLayout(btn_row)

        self._signals = DockFileSignals(self)
        self._signals.finished.connect(self._on_finished)
        self._signals.failed.connect(self._on_failed)
        self._signals.progress.connect(self._append_log)
        self._input_tmp: Path | None = None
        self._smina_result = None

        make_window_minimizable(self)

    def prefill_from_viewer(self) -> None:
        self._refresh_structure_source()

    def _sync_smina_options(self) -> None:
        loaded = self.radio_box_loaded.isChecked()
        self.combo_box_ligand.setEnabled(loaded and self.combo_box_ligand.count() > 0)
        self.box_ligand_file_row.setEnabled(not loaded)

    def _refresh_box_ligand_combo(self) -> None:
        self.combo_box_ligand.clear()
        options = []
        getter = getattr(self._viewer, "prepare_ligand_options", None)
        if callable(getter):
            options = list(getter() or [])
        if not options:
            options = list(self.chosen_ligand_options())
        selected_index = 0
        for i, item in enumerate(options):
            label, key, selected = item[0], item[1], item[2]
            sid = item[3] if len(item) > 3 else ""
            self.combo_box_ligand.addItem(label, {"key": key, "structure_id": sid})
            if selected:
                selected_index = i
        if options:
            self.combo_box_ligand.setCurrentIndex(selected_index)
        self._sync_smina_options()

    def _box_ligand_choice(self) -> tuple[tuple[str, str, str] | None, str]:
        data = self.combo_box_ligand.currentData()
        if isinstance(data, dict):
            key = data.get("key")
            sid = str(data.get("structure_id") or "")
            if isinstance(key, (tuple, list)) and len(key) >= 3:
                return (str(key[0]), str(key[1]), str(key[2])), sid
            return None, sid
        if isinstance(data, (tuple, list)) and len(data) >= 3:
            return (str(data[0]), str(data[1]), str(data[2])), ""
        return None, ""

    def _box_ligand_keys(self) -> tuple[tuple[str, str, str], ...]:
        if not self.radio_box_loaded.isChecked():
            return ()
        key, _sid = self._box_ligand_choice()
        if not key:
            return ()
        return (key,)

    def _box_ligand_path(self) -> str:
        if not self.radio_box_file.isChecked():
            return ""
        return (self.edit_box_ligand.text() or "").strip()

    def _box_source_payload(self) -> tuple[str, str]:
        if not self.radio_box_loaded.isChecked():
            return "", ""
        _key, sid = self._box_ligand_choice()
        if not sid:
            return "", ""
        chosen_sid = self._chosen_manager_id()
        if sid and chosen_sid and sid == chosen_sid:
            return "", ""
        getter = getattr(self._viewer, "prepare_slot_payload", None)
        if callable(getter):
            text, fmt = getter(sid)
            return text or "", fmt or "pdb"
        return "", ""

    def _browse_box_ligand(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Ligand for docking box",
            self.edit_box_ligand.text().strip(),
            "Ligand files (*.pdb *.pdbqt *.sdf *.sd *.mol *.mol2 *.cif);;All files (*.*)",
        )
        if path:
            self.edit_box_ligand.setText(path)
            self.radio_box_file.setChecked(True)

    def _browse_output(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Receptor PDBQT",
            self.edit_out.text().strip(),
            "PDBQT (*.pdbqt);;All files (*.*)",
        )
        if path:
            dest = Path(path)
            if dest.suffix.lower() != ".pdbqt":
                dest = dest.with_suffix(".pdbqt")
            self.edit_out.setText(str(dest))

    def _receptor_output_path(self) -> str:
        text = (self.edit_out.text() or "").strip()
        if not text:
            return ""
        dest = Path(text)
        if dest.suffix.lower() != ".pdbqt":
            dest = dest.with_suffix(".pdbqt")
        return str(dest)

    def _append_log(self, text: str) -> None:
        append_viewer_log(self._viewer, text)

    def _process_host(self):
        parent = self._viewer
        while parent is not None:
            if hasattr(parent, "process_queue"):
                return parent
            parent = parent.parent()
        return None

    def _on_run(self) -> None:
        self._resolved_source = None
        try:
            _name, text, fmt, _path = self.chosen_structure_source()
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Dock File", str(exc))
            return
        if not (text or "").strip():
            QMessageBox.information(self, "Dock File", self._source_empty_message)
            return
        fmt = fmt or "pdb"
        if fmt not in _PREPARE_FMTS:
            QMessageBox.warning(
                self,
                "Dock File",
                "Dock File supports PDB and mmCIF. Convert or reload as PDB first.",
            )
            return
        out_path = self._receptor_output_path()
        if not out_path:
            QMessageBox.information(self, "Dock File", "Set an output path.")
            return
        self.edit_out.setText(out_path)
        if self.radio_box_file.isChecked() and not self._box_ligand_path():
            QMessageBox.information(
                self,
                "Dock File",
                "Choose a ligand file for the search box, or switch Box from to Loaded structure.",
            )
            return
        try:
            in_path = self._write_input_snapshot()
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Dock File", str(exc))
            return
        box_source_text, box_source_fmt = self._box_source_payload()
        req = DockFileRequest(
            input_path=str(in_path),
            output_path=out_path,
            box_ligand_keys=self._box_ligand_keys(),
            box_ligand_path=self._box_ligand_path(),
            box_padding=float(self.spin_box_padding.value()),
            box_source_text=box_source_text,
            box_source_fmt=box_source_fmt,
        )
        self.btn_run.setEnabled(False)
        self.btn_open_smina.setEnabled(False)
        self._smina_result = None
        self.lbl_box_preview.setText("Box: —")
        self._append_log("Starting Dock File: Gnina files")
        host = self._process_host()
        if host is not None:
            host.process_queue.enqueue(
                "Dock File",
                lambda ev, r=req, sig=self._signals: DockFileWorker(
                    r, signals=sig, cancel_event=ev
                ),
            )
            return
        from PySide6.QtCore import QThreadPool

        QThreadPool.globalInstance().start(DockFileWorker(req, signals=self._signals))

    def _on_finished(self, result) -> None:
        from ...workers.protein_prepare_smina import ProteinPrepareResult

        self.btn_run.setEnabled(True)
        if isinstance(result, ProteinPrepareResult):
            smina = result
        else:
            smina = result if getattr(result, "output_path", None) else None
        if smina is None:
            self._append_log("Dock File finished with no Gnina files.")
            return
        if smina.receptor_pdbqt:
            self._append_log(f"Receptor PDBQT: {smina.receptor_pdbqt}")
        if smina.ligand_sdf:
            self._append_log(f"Ligand SDF: {smina.ligand_sdf}")
        if smina.ligand_pdb:
            self._append_log(f"Autobox ligand: {smina.ligand_pdb}")
        if smina.box_path:
            self._append_log(f"Search box: {smina.box_path}")
        if smina.box is not None:
            box = smina.box
            self.lbl_box_preview.setText(
                f"Box: center ({box.center_x:.2f}, {box.center_y:.2f}, {box.center_z:.2f})  "
                f"size ({box.size_x:.1f}, {box.size_y:.1f}, {box.size_z:.1f}) Å"
            )
        if smina.warning:
            self._append_log(smina.warning)
        if not smina.receptor_pdbqt:
            self._append_log(
                "Receptor PDBQT was not written. Gnina needs this file before docking."
            )
        self._smina_result = smina
        pdbqt = smina.receptor_pdbqt_path()
        have_pdbqt = bool(pdbqt) and Path(pdbqt).is_file()
        self.btn_open_smina.setEnabled(have_pdbqt)
        self.smina_prepared.emit(smina)
        if have_pdbqt and self._open_smina(smina):
            self.close()

    def _on_open_smina(self) -> None:
        result = self._smina_result
        if result is None or not result.can_open_smina():
            QMessageBox.information(
                self,
                "Dock File",
                "Write Gnina files first.",
            )
            return
        if self._open_smina(result):
            self.close()

    def _open_smina(self, result) -> bool:
        rec = ""
        getter = getattr(result, "receptor_pdbqt_path", None)
        if callable(getter):
            rec = str(getter() or "").strip()
        if not rec:
            rec = str(getattr(result, "receptor_pdbqt", "") or "").strip()
        if Path(rec).suffix.lower() != ".pdbqt" or not Path(rec).is_file():
            QMessageBox.warning(
                self,
                "Dock File",
                "Dock File did not write a receptor PDBQT. Check the log, then browse "
                "to the .pdbqt in Protein → Dock Ligand → Gnina.",
            )
            return False
        host = self._process_host()
        opener = (
            (getattr(host, "open_gnina_dock", None) or getattr(host, "open_smina_dock", None))
            if host is not None
            else None
        )
        if not callable(opener):
            QMessageBox.information(
                self,
                "Dock File",
                "Open Gnina from Protein → Dock Ligand → Gnina… and browse to the written files.",
            )
            return False
        dlg = opener()
        apply = getattr(dlg, "apply_prepare_result", None)
        if callable(apply):
            apply(result)
        edit = getattr(dlg, "edit_receptor", None)
        if edit is not None:
            edit.setText(rec)
        return True

    def _on_failed(self, msg: str) -> None:
        self.btn_run.setEnabled(True)
        self._append_log(msg or "Dock File failed.")
