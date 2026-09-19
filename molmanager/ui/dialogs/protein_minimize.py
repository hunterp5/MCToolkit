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

"""Protein Viewer Minimize dialog: OpenMM restrained complex minimization."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
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
    QVBoxLayout,
)

from ...workers.protein_minimize import (
    ProteinMinimizeRequest,
    ProteinMinimizeSignals,
    ProteinMinimizeWorker,
)
from ..qt_widget_utils import append_viewer_log, make_window_minimizable
from .protein_prepare import _browse_path_row, add_openmm_platform_combo
from .protein_source_picker import ProteinStructureSourceMixin

_MINIMIZE_FMTS = frozenset({"pdb", "pqr", "cif"})


class ProteinMinimizeDialog(ProteinStructureSourceMixin, QDialog):
    """Options for Protein Viewer → Tools → Prepare → Minimize."""

    minimized = Signal(str)
    _source_output_tag = "minimized"
    _source_tmp_prefix = "molmanager_minimize_in_"
    _source_tool_title = "Minimize Complex"
    _source_empty_message = "Choose a Manager structure or a PDB/mmCIF file."

    def __init__(self, viewer, parent=None) -> None:
        super().__init__(parent or viewer)
        self._viewer = viewer
        self.setWindowTitle("Minimize Complex")
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
        self.edit_out.setPlaceholderText("receptor_minimized.cif")
        io_form.addRow("Output:", _browse_path_row(self.edit_out, self._browse_output))
        self.combo_out_fmt = QComboBox()
        self.combo_out_fmt.addItem("mmCIF (.cif)", "cif")
        self.combo_out_fmt.addItem("PDB (.pdb)", "pdb")
        self.combo_out_fmt.setToolTip("mmCIF keeps ligand bond orders in _chem_comp_bond.")
        self.combo_out_fmt.currentIndexChanged.connect(self._sync_output_suffix)
        io_form.addRow("Format:", self.combo_out_fmt)
        self.chk_keep_water = QCheckBox("Keep waters already in the structure")
        self.chk_keep_water.setChecked(True)
        self.chk_keep_water.setToolTip(
            "Leave crystallographic or prepared waters in the OpenMM system. "
            "Uncheck to drop them before minimization."
        )
        io_form.addRow(self.chk_keep_water)
        root.addWidget(io_gb)

        lig_gb = QGroupBox("Ligand")
        lig_form = QFormLayout(lig_gb)
        lig_form.setContentsMargins(8, 6, 8, 6)
        lig_form.setSpacing(4)
        self.combo_ligand = QComboBox()
        self.combo_ligand.setToolTip(
            "Ligand minimized with the protein. All ligands is the default when "
            "more than one is loaded."
        )
        lig_form.addRow("Ligand:", self.combo_ligand)
        self.combo_ligand_ff = QComboBox()
        self.combo_ligand_ff.addItem("GAFF2", "gaff2")
        self.combo_ligand_ff.addItem("GAFF", "gaff")
        self.combo_ligand_ff.addItem("Protein only", "none")
        self.combo_ligand_ff.setToolTip(
            "GAFF2 (recommended) parameterizes the ligand with AmberTools (WSL on "
            "Windows) so the complex is minimized together. Protein only holds the "
            "ligand out of OpenMM and restores it afterward."
        )
        lig_form.addRow("Ligand force field:", self.combo_ligand_ff)
        self.edit_ligand_smiles = QLineEdit()
        self.edit_ligand_smiles.setPlaceholderText("Optional if mmCIF has _chem_comp_bond")
        self.edit_ligand_smiles.setToolTip(
            "Bond-order template for GAFF/GAFF2 when the file has no mmCIF ligand bonds."
        )
        lig_form.addRow("SMILES:", self.edit_ligand_smiles)
        self.edit_ligand_ref = QLineEdit()
        self.edit_ligand_ref.setPlaceholderText("SDF or MOL2")
        lig_form.addRow(
            "Bond-order file:",
            _browse_path_row(self.edit_ligand_ref, self._browse_ligand_ref),
        )
        root.addWidget(lig_gb)

        min_gb = QGroupBox("Minimization")
        min_form = QFormLayout(min_gb)
        min_form.setContentsMargins(8, 6, 8, 6)
        min_form.setSpacing(4)
        self.combo_protein_ff = QComboBox()
        self.combo_protein_ff.addItem("AMBER ff14SB", "amber14")
        self.combo_protein_ff.addItem("AMBER ff99SB-ILDN", "amber99sbildn")
        self.combo_protein_ff.setToolTip("Protein force field for OpenMM minimization.")
        min_form.addRow("Protein force field:", self.combo_protein_ff)
        self.combo_solvent = QComboBox()
        self.combo_solvent.addItem("GBn2 GBSA (recommended)", "gbn2")
        self.combo_solvent.addItem("OBC2 GBSA", "obc2")
        self.combo_solvent.addItem("Vacuum", "vacuum")
        self.combo_solvent.setToolTip(
            "GBn2 is the usual implicit solvent. Vacuum over-attracts charges."
        )
        min_form.addRow("Solvation:", self.combo_solvent)
        self.combo_openmm_platform = QComboBox()
        add_openmm_platform_combo(self.combo_openmm_platform)
        min_form.addRow("Compute:", self.combo_openmm_platform)
        self.spin_salt = QDoubleSpinBox()
        self.spin_salt.setRange(0.0, 2.0)
        self.spin_salt.setDecimals(2)
        self.spin_salt.setSingleStep(0.05)
        self.spin_salt.setValue(0.15)
        self.spin_salt.setSuffix(" M")
        self.spin_salt.setToolTip("1:1 salt for GB Debye screening (ignored in vacuum).")
        min_form.addRow("Salt:", self.spin_salt)
        self.combo_restraint = QComboBox()
        self.combo_restraint.addItem("Backbone + ligand heavy atoms", "backbone_ligand")
        self.combo_restraint.addItem("Backbone heavy atoms", "backbone")
        self.combo_restraint.addItem("Cα only", "ca")
        self.combo_restraint.setToolTip(
            "Backbone + ligand keeps the fold and crystal pose. Backbone lets the "
            "ligand relax more. Cα-only lets side chains move more."
        )
        min_form.addRow("Restrain:", self.combo_restraint)
        self.spin_k = QDoubleSpinBox()
        self.spin_k.setRange(0.5, 50.0)
        self.spin_k.setDecimals(1)
        self.spin_k.setSingleStep(1.0)
        self.spin_k.setValue(10.0)
        self.spin_k.setSuffix(" kcal/mol/Å²")
        min_form.addRow("Restraint k:", self.spin_k)
        self.spin_iters = QSpinBox()
        self.spin_iters.setRange(50, 5000)
        self.spin_iters.setSingleStep(50)
        self.spin_iters.setValue(400)
        min_form.addRow("Max iterations:", self.spin_iters)
        root.addWidget(min_gb)

        self.combo_ligand_ff.currentIndexChanged.connect(self._sync_ligand_options)
        self.combo_solvent.currentIndexChanged.connect(self._sync_min_options)
        self._sync_ligand_options()
        self._sync_min_options()

        btn_row = QHBoxLayout()
        self.btn_run = QPushButton("Minimize")
        self.btn_run.clicked.connect(self._on_run)
        btn_row.addWidget(self.btn_run)
        btn_row.addStretch()
        self.btn_close = QPushButton("Close")
        self.btn_close.clicked.connect(self.close)
        btn_row.addWidget(self.btn_close)
        root.addLayout(btn_row)

        self._signals = ProteinMinimizeSignals(self)
        self._signals.finished.connect(self._on_finished)
        self._signals.failed.connect(self._on_failed)
        self._input_tmp: Path | None = None

        make_window_minimizable(self)

    def prefill_from_viewer(self) -> None:
        self._refresh_structure_source()
        self._sync_ligand_options()

    def _refresh_ligand_combo(self) -> None:
        self.combo_ligand.clear()
        self.combo_ligand.addItem("All ligands", None)
        options = list(self.chosen_ligand_options())
        selected_index = 0
        for i, item in enumerate(options):
            label, key, selected = item[0], item[1], item[2]
            self.combo_ligand.addItem(label, key)
            if selected:
                selected_index = i + 1
        if options:
            self.combo_ligand.setCurrentIndex(selected_index)
        self.combo_ligand.setEnabled(bool(options))

    def _ligand_keys(self) -> tuple[tuple[str, str, str], ...]:
        data = self.combo_ligand.currentData()
        if data is None:
            return ()
        if isinstance(data, (tuple, list)) and len(data) >= 3:
            return ((str(data[0]), str(data[1]), str(data[2])),)
        return ()

    def _source_has_ligand(self, text: str, fmt: str) -> bool:
        from ...protein.structure_components import parse_structure_components

        try:
            comps = parse_structure_components(text or "", fmt or "pdb")
        except Exception:
            return False
        return any(c.kind == "ligand" for c in comps)

    def _source_has_cif_ligand_bonds(self, text: str, fmt: str) -> bool:
        from ...protein.structure_components import (
            cif_has_component_bonds,
            parse_structure_components,
        )

        if (fmt or "").lower() not in {"cif", "mmcif"}:
            return False
        try:
            comps = parse_structure_components(text or "", fmt)
        except Exception:
            return False
        resns = {c.resn for c in comps if c.kind == "ligand"}
        return cif_has_component_bonds(text or "", resns)

    def _sync_ligand_options(self) -> None:
        has_ligand = self.combo_ligand.count() > 1
        self.combo_ligand_ff.setEnabled(has_ligand)
        gaff = has_ligand and (self.combo_ligand_ff.currentData() or "gaff2") in {
            "gaff",
            "gaff2",
        }
        self.edit_ligand_smiles.setEnabled(gaff)
        self.edit_ligand_ref.setEnabled(gaff)
        self._sync_min_options()

    def _sync_min_options(self) -> None:
        gb = (self.combo_solvent.currentData() or "gbn2") != "vacuum"
        self.spin_salt.setEnabled(gb)

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

    def _browse_ligand_ref(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Ligand bond-order file",
            self.edit_ligand_ref.text().strip(),
            "Ligand files (*.sdf *.sd *.mol *.mol2);;All files (*.*)",
        )
        if path:
            self.edit_ligand_ref.setText(path)

    def _browse_output(self) -> None:
        fmt = self.combo_out_fmt.currentData() or "cif"
        if fmt == "pdb":
            title = "Minimized PDB"
            filt = "PDB (*.pdb);;All files (*.*)"
        else:
            title = "Minimized mmCIF"
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
            QMessageBox.warning(self, "Minimize Complex", str(exc))
            return
        if not (text or "").strip():
            QMessageBox.information(self, "Minimize Complex", self._source_empty_message)
            return
        fmt = fmt or "pdb"
        if fmt not in _MINIMIZE_FMTS:
            QMessageBox.warning(
                self,
                "Minimize Complex",
                "Minimize supports PDB and mmCIF. Convert or reload as PDB first.",
            )
            return
        out_path = (self.edit_out.text() or "").strip()
        if not out_path:
            QMessageBox.information(self, "Minimize Complex", "Set an output path.")
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
        ligand_ff = self.combo_ligand_ff.currentData() or "gaff2"
        has_ligand = self._source_has_ligand(text, fmt)
        if not has_ligand:
            ligand_ff = "none"
        if (
            has_ligand
            and ligand_ff in {"gaff", "gaff2"}
            and not self.edit_ligand_smiles.text().strip()
            and not self.edit_ligand_ref.text().strip()
            and not self._source_has_cif_ligand_bonds(text, fmt)
        ):
            QMessageBox.information(
                self,
                "Minimize Complex",
                "GAFF/GAFF2 minimization needs SMILES, an SDF/MOL2, or mmCIF "
                "_chem_comp_bond so AmberTools can assign ligand atom types. Add one, "
                "or set Ligand force field to Protein only.",
            )
            return
        try:
            in_path = self._write_input_snapshot()
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Minimize Complex", str(exc))
            return

        req = ProteinMinimizeRequest(
            input_path=str(in_path),
            output_path=out_path,
            protein_ff=self.combo_protein_ff.currentData() or "amber14",
            ligand_ff=ligand_ff,
            solvent=self.combo_solvent.currentData() or "gbn2",
            openmm_platform=self.combo_openmm_platform.currentData() or "auto",
            salt_m=float(self.spin_salt.value()),
            restraint_set=self.combo_restraint.currentData() or "backbone_ligand",
            restraint_k_kcal_per_ang2=float(self.spin_k.value()),
            max_iterations=int(self.spin_iters.value()),
            ligand_smiles=self.edit_ligand_smiles.text().strip(),
            ligand_ref_path=self.edit_ligand_ref.text().strip(),
            ligand_keys=self._ligand_keys(),
            keep_water=self.chk_keep_water.isChecked(),
            output_format=out_fmt,
        )
        self.btn_run.setEnabled(False)
        self._append_log("Starting OpenMM restrained minimization…")
        host = self._process_host()
        if host is not None:
            host.process_queue.enqueue(
                "Minimize Complex",
                lambda ev, r=req, sig=self._signals: ProteinMinimizeWorker(
                    r, signals=sig, cancel_event=ev
                ),
            )
            return
        from PySide6.QtCore import QThreadPool

        QThreadPool.globalInstance().start(ProteinMinimizeWorker(req, signals=self._signals))

    def _on_finished(self, path: str) -> None:
        self.btn_run.setEnabled(True)
        self._append_log(f"Minimized file written: {path}")
        self.minimized.emit(path)
        self.close()

    def _on_failed(self, msg: str) -> None:
        self.btn_run.setEnabled(True)
        self._append_log(msg or "Complex minimization failed.")
