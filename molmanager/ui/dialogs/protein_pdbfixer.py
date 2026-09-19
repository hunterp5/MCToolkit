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

"""Protein Viewer PDBFixer dialog: repair missing atoms and strip clutter."""

from __future__ import annotations

from pathlib import Path

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from ...workers.protein_prepare import (
    ProteinPrepareRequest,
    ProteinPrepareSignals,
    ProteinPrepareWorker,
)
from ..qt_widget_utils import append_viewer_log, make_window_minimizable
from .protein_fixer_options import (
    add_fixer_extra_options,
    fixer_extra_request_kwargs,
    populate_fixer_chain_list,
)
from .protein_prepare import _PREPARE_FMTS, _browse_path_row
from .protein_source_picker import ProteinStructureSourceMixin


class ProteinPdbFixerDialog(ProteinStructureSourceMixin, QDialog):
    """Options for Protein Viewer → Tools → Prepare → PDBFixer."""

    prepared = pyqtSignal(str)
    _source_output_tag = "fixed"
    _source_tmp_prefix = "molmanager_pdbfixer_in_"
    _source_tool_title = "PDBFixer"
    _source_empty_message = "Choose a Manager structure or a PDB/mmCIF file."

    def __init__(self, viewer, parent=None) -> None:
        super().__init__(parent or viewer)
        self._viewer = viewer
        self.setWindowTitle("PDBFixer")
        self.setMinimumWidth(480)
        self.resize(520, 480)

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 6)
        root.setSpacing(6)

        io_gb = QGroupBox("Structure")
        io_form = QFormLayout(io_gb)
        io_form.setContentsMargins(8, 6, 8, 6)
        io_form.setSpacing(4)
        self._add_structure_source_rows(io_form)
        self.edit_out = QLineEdit()
        self.edit_out.setPlaceholderText("receptor_fixed.cif")
        io_form.addRow("Output:", _browse_path_row(self.edit_out, self._browse_output))
        self.combo_out_fmt = QComboBox()
        self.combo_out_fmt.addItem("mmCIF (.cif)", "cif")
        self.combo_out_fmt.addItem("PDB (.pdb)", "pdb")
        self.combo_out_fmt.setToolTip("mmCIF keeps ligand bond orders in _chem_comp_bond.")
        self.combo_out_fmt.currentIndexChanged.connect(self._sync_output_suffix)
        io_form.addRow("Format:", self.combo_out_fmt)
        root.addWidget(io_gb)

        opt_gb = QGroupBox("Repair / clean")
        opt_form = QFormLayout(opt_gb)
        opt_form.setContentsMargins(8, 6, 8, 6)
        opt_form.setSpacing(4)

        self.chk_rebuild_loops = QCheckBox("Rebuild missing loops from SEQRES")
        self.chk_rebuild_loops.setChecked(True)
        self.chk_rebuild_loops.setToolTip(
            "Model internal sequence gaps. Uncheck to skip internal loops. Long "
            "terminal tags are skipped separately (Skip long missing stretches)."
        )
        opt_form.addRow(self.chk_rebuild_loops)

        self.chk_skip_pocket_loops = QCheckBox("Skip loop rebuild near the ligand")
        self.chk_skip_pocket_loops.setChecked(True)
        self.chk_skip_pocket_loops.setToolTip(
            "Do not fill SEQRES gaps whose flanking residues sit within 8 Å of the ligand. "
            "Rebuilt loops next to the site are models, not crystal coordinates."
        )
        opt_form.addRow(self.chk_skip_pocket_loops)

        add_fixer_extra_options(opt_form, self)

        self.chk_replace_nonstandard = QCheckBox("Replace non-standard residues (e.g. MSE → MET)")
        self.chk_replace_nonstandard.setChecked(True)
        self.chk_replace_nonstandard.setToolTip(
            "Convert modified amino acids such as selenomethionine to standard residues."
        )
        opt_form.addRow(self.chk_replace_nonstandard)

        self.chk_include_ligand = QCheckBox("Keep ligand during repair")
        self.chk_include_ligand.setChecked(True)
        self.chk_include_ligand.setToolTip(
            "Leave organic HETATM in the structure while PDBFixer rebuilds protein atoms."
        )
        opt_form.addRow(self.chk_include_ligand)

        self.chk_keep_ligand = QCheckBox("Keep ligand in output mmCIF")
        self.chk_keep_ligand.setChecked(True)
        self.chk_keep_ligand.setToolTip(
            "Leave the ligand in the repaired file. Uncheck for an apo receptor."
        )
        opt_form.addRow(self.chk_keep_ligand)

        self.chk_keep_selected_waters = QCheckBox("Keep Manager-selected waters")
        self.chk_keep_selected_waters.setChecked(False)
        self.chk_keep_selected_waters.setToolTip(
            "Keep water groups currently selected in the Manager. Other waters are "
            "stripped unless bridging waters are also kept."
        )
        opt_form.addRow(self.chk_keep_selected_waters)

        self.chk_keep_bridging_waters = QCheckBox("Keep waters near ligand")
        self.chk_keep_bridging_waters.setChecked(False)
        self.chk_keep_bridging_waters.setToolTip(
            "Keep crystallographic waters whose oxygen is within the water cutoff of a "
            "ligand heavy atom, occupancy ≥ 0.5, and B-factor ≤ 80."
        )
        opt_form.addRow(self.chk_keep_bridging_waters)
        root.addWidget(opt_gb)

        btn_row = QHBoxLayout()
        self.btn_run = QPushButton("PDBFixer")
        self.btn_run.clicked.connect(self._on_run)
        btn_row.addWidget(self.btn_run)
        btn_row.addStretch()
        self.btn_close = QPushButton("Close")
        self.btn_close.clicked.connect(self.close)
        btn_row.addWidget(self.btn_close)
        root.addLayout(btn_row)

        self.chk_rebuild_loops.toggled.connect(self._sync_loop_options)
        self.chk_include_ligand.toggled.connect(self._sync_ligand_options)
        self.chk_keep_bridging_waters.toggled.connect(self._sync_water_cutoff)
        self._sync_loop_options()
        self._sync_ligand_options()
        self._sync_water_cutoff()

        self._signals = ProteinPrepareSignals(self)
        self._signals.finished.connect(self._on_finished)
        self._signals.failed.connect(self._on_failed)
        self._signals.progress.connect(self._append_log)
        self._input_tmp: Path | None = None

        make_window_minimizable(self)

    def prefill_from_viewer(self) -> None:
        self._refresh_structure_source()

    def _refresh_water_label(self) -> None:
        keys = self.chosen_water_keys()
        if keys:
            self.chk_keep_selected_waters.setText(
                f"Keep Manager-selected waters ({len(keys)} residue{'s' if len(keys) != 1 else ''})"
            )
        else:
            self.chk_keep_selected_waters.setText("Keep Manager-selected waters")

    def _refresh_chain_list(self) -> None:
        populate_fixer_chain_list(self, self.chosen_chain_ids())

    def _sync_loop_options(self) -> None:
        loops = self.chk_rebuild_loops.isChecked()
        self.chk_skip_pocket_loops.setEnabled(loops)
        if not loops:
            self.chk_skip_pocket_loops.setChecked(False)

    def _sync_ligand_options(self) -> None:
        include = self.chk_include_ligand.isChecked()
        self.chk_keep_ligand.setEnabled(include)
        self.chk_keep_bridging_waters.setEnabled(include)
        if not include:
            self.chk_keep_bridging_waters.setChecked(False)
        self._sync_water_cutoff()

    def _sync_water_cutoff(self, *_args) -> None:
        self.spin_water_cutoff.setEnabled(
            self.chk_include_ligand.isChecked() and self.chk_keep_bridging_waters.isChecked()
        )

    def _sync_output_suffix(self) -> None:
        path = (self.edit_out.text() or "").strip()
        if not path:
            return
        rec = Path(path)
        fmt = self.combo_out_fmt.currentData() or "cif"
        if fmt == "pdb":
            if rec.suffix.lower() != ".pdb":
                self.edit_out.setText(str(rec.with_suffix(".pdb")))
        elif rec.suffix.lower() not in {".cif", ".mmcif", ".mcif"}:
            self.edit_out.setText(str(rec.with_suffix(".cif")))

    def _browse_output(self) -> None:
        fmt = self.combo_out_fmt.currentData() or "cif"
        if fmt == "pdb":
            title = "Repaired PDB"
            filt = "PDB (*.pdb);;All files (*.*)"
        else:
            title = "Repaired mmCIF"
            filt = "mmCIF (*.cif *.mmcif *.mcif);;All files (*.*)"
        path, _ = QFileDialog.getSaveFileName(
            self,
            title,
            self.edit_out.text().strip(),
            filt,
        )
        if path:
            self.edit_out.setText(path)

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
            QMessageBox.warning(self, "PDBFixer", str(exc))
            return
        if not (text or "").strip():
            QMessageBox.information(self, "PDBFixer", self._source_empty_message)
            return
        fmt = fmt or "pdb"
        if fmt not in _PREPARE_FMTS:
            QMessageBox.warning(
                self,
                "PDBFixer",
                "PDBFixer supports PDB and mmCIF. Convert or reload as PDB first.",
            )
            return
        out_path = (self.edit_out.text() or "").strip()
        if not out_path:
            QMessageBox.information(self, "PDBFixer", "Set an output path.")
            return
        out_rec = Path(out_path)
        out_fmt = self.combo_out_fmt.currentData() or "cif"
        if out_fmt == "pdb":
            if out_rec.suffix.lower() != ".pdb":
                out_rec = out_rec.with_suffix(".pdb")
        elif out_rec.suffix.lower() not in {".cif", ".mmcif", ".mcif"}:
            out_rec = out_rec.with_suffix(".cif")
        out_path = str(out_rec)
        self.edit_out.setText(out_path)
        keep_water_keys: tuple[tuple[str, str, str], ...] = ()
        if self.chk_keep_selected_waters.isChecked():
            keep_water_keys = self.chosen_water_keys()
            if not keep_water_keys:
                QMessageBox.information(
                    self,
                    "PDBFixer",
                    "Select water groups in the Manager (a Chain row or its Water row), "
                    "then try again — or uncheck Keep Manager-selected waters.",
                )
                return
        try:
            in_path = self._write_input_snapshot()
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "PDBFixer", str(exc))
            return

        req = ProteinPrepareRequest(
            input_path=str(in_path),
            output_pdb_path=out_path,
            rebuild_missing_loops=self.chk_rebuild_loops.isChecked(),
            replace_nonstandard=self.chk_replace_nonstandard.isChecked(),
            include_ligand=self.chk_include_ligand.isChecked(),
            keep_ligand=self.chk_keep_ligand.isChecked(),
            keep_water_keys=keep_water_keys,
            keep_bridging_waters=self.chk_keep_bridging_waters.isChecked(),
            protonate=False,
            minimize=False,
            protonate_ligand=False,
            pocket_ligand_protonation=False,
            skip_pocket_loops=self.chk_skip_pocket_loops.isChecked(),
            output_format=out_fmt,
            write_smina=False,
            **fixer_extra_request_kwargs(self),
        )
        self.btn_run.setEnabled(False)
        self._append_log("Starting PDBFixer: repair / clean")
        host = self._process_host()
        if host is not None:
            host.process_queue.enqueue(
                "PDBFixer",
                lambda ev, r=req, sig=self._signals: ProteinPrepareWorker(
                    r, signals=sig, cancel_event=ev
                ),
            )
            return
        from PyQt5.QtCore import QThreadPool

        QThreadPool.globalInstance().start(ProteinPrepareWorker(req, signals=self._signals))

    def _on_finished(self, result) -> None:
        from ...workers.protein_prepare_smina import ProteinPrepareResult

        self.btn_run.setEnabled(True)
        if isinstance(result, str):
            path = result
        elif isinstance(result, ProteinPrepareResult):
            path = result.output_path
        else:
            path = str(getattr(result, "output_path", "") or result)
        self._append_log(f"Repaired file written: {path}")
        self.prepared.emit(path)
        self.close()

    def _on_failed(self, msg: str) -> None:
        self.btn_run.setEnabled(True)
        self._append_log(msg or "PDBFixer failed.")
