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

"""Protein Viewer MD dialog (OpenMM Langevin: GBSA or TIP3P PME + optional MM-GBSA)."""

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
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from ...reference.method_citations import md_dialog_footer_html
from ...workers.protein_md import ProteinMDRequest, ProteinMDSignals, ProteinMDWorker
from ..qt_widget_utils import append_viewer_log, make_window_minimizable
from .conformer_output import citation_footer_label
from .protein_prepare import _browse_path_row, add_openmm_platform_combo
from .protein_source_picker import ProteinStructureSourceMixin

_SOURCE_FMTS = frozenset({"pdb", "pqr", "cif"})


class ProteinMDDialog(ProteinStructureSourceMixin, QDialog):
    """Options for Protein Viewer → Tools → Simulate → Molecular Dynamics."""

    finished_md = Signal(object)
    _source_output_tag = "md"
    _source_tmp_prefix = "mctoolkit_md_in_"
    _source_tool_title = "Molecular Dynamics"
    _source_empty_message = "Choose a Manager structure or a PDB/mmCIF file."

    def __init__(self, viewer, parent=None) -> None:
        super().__init__(parent or viewer)
        self._viewer = viewer
        self.setWindowTitle("Molecular Dynamics")
        self.setMinimumWidth(540)
        self.resize(580, 780)

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 6)
        root.setSpacing(6)

        io_gb = QGroupBox("Structure")
        io_form = QFormLayout(io_gb)
        io_form.setContentsMargins(8, 6, 8, 6)
        io_form.setSpacing(4)
        self._add_structure_source_rows(io_form)
        self.edit_out = QLineEdit()
        self.edit_out.setPlaceholderText("complex_md.cif")
        self.combo_out_fmt = QComboBox()
        self.combo_out_fmt.addItem("mmCIF (.cif)", "cif")
        self.combo_out_fmt.addItem("PDB (.pdb)", "pdb")
        self.combo_out_fmt.currentIndexChanged.connect(self._sync_output_suffix)
        io_form.addRow("Last frame:", _browse_path_row(self.edit_out, self._browse_output))
        io_form.addRow("Format:", self.combo_out_fmt)
        self.edit_dcd = QLineEdit()
        self.edit_dcd.setPlaceholderText("complex_md.dcd")
        io_form.addRow("Trajectory DCD:", _browse_path_row(self.edit_dcd, self._browse_dcd))
        self.edit_report = QLineEdit()
        self.edit_report.setPlaceholderText("complex_md_mmgbsa.txt")
        io_form.addRow("MM-GBSA report:", _browse_path_row(self.edit_report, self._browse_report))
        self.edit_csv = QLineEdit()
        self.edit_csv.setPlaceholderText("complex_md_mmgbsa.csv")
        io_form.addRow("MM-GBSA CSV:", _browse_path_row(self.edit_csv, self._browse_csv))
        self.edit_checkpoint = QLineEdit()
        self.edit_checkpoint.setPlaceholderText("complex_md.chk")
        io_form.addRow(
            "Checkpoint:", _browse_path_row(self.edit_checkpoint, self._browse_checkpoint)
        )
        self.chk_resume = QCheckBox("Resume from checkpoint if present")
        self.chk_resume.setChecked(False)
        io_form.addRow(self.chk_resume)
        self.chk_keep_water = QCheckBox("Keep waters already in the structure")
        self.chk_keep_water.setChecked(False)
        io_form.addRow(self.chk_keep_water)
        root.addWidget(io_gb)

        lig_gb = QGroupBox("Ligand")
        lig_form = QFormLayout(lig_gb)
        lig_form.setContentsMargins(8, 6, 8, 6)
        lig_form.setSpacing(4)
        self.combo_ligand = QComboBox()
        lig_form.addRow("Ligand:", self.combo_ligand)
        self.combo_ligand_ff = QComboBox()
        self.combo_ligand_ff.addItem("GAFF2", "gaff2")
        self.combo_ligand_ff.addItem("GAFF", "gaff")
        lig_form.addRow("Ligand force field:", self.combo_ligand_ff)
        self.edit_ligand_smiles = QLineEdit()
        self.edit_ligand_smiles.setPlaceholderText("Optional if mmCIF has _chem_comp_bond")
        lig_form.addRow("SMILES:", self.edit_ligand_smiles)
        self.edit_ligand_ref = QLineEdit()
        self.edit_ligand_ref.setPlaceholderText("SDF or MOL2")
        lig_form.addRow(
            "Bond-order file:",
            _browse_path_row(self.edit_ligand_ref, self._browse_ligand_ref),
        )
        root.addWidget(lig_gb)

        md_gb = QGroupBox("Dynamics")
        md_form = QFormLayout(md_gb)
        md_form.setContentsMargins(8, 6, 8, 6)
        md_form.setSpacing(4)
        self.combo_protein_ff = QComboBox()
        self.combo_protein_ff.addItem("AMBER ff14SB", "amber14")
        self.combo_protein_ff.addItem("AMBER ff99SB-ILDN", "amber99sbildn")
        md_form.addRow("Protein force field:", self.combo_protein_ff)
        self.combo_solvent = QComboBox()
        self.combo_solvent.addItem("GBn2 GBSA (recommended)", "gbn2")
        self.combo_solvent.addItem("OBC2 GBSA", "obc2")
        self.combo_solvent.addItem("TIP3P box (PME, NPT)", "tip3p")
        self.combo_solvent.currentIndexChanged.connect(self._sync_solvent_options)
        md_form.addRow("Solvation:", self.combo_solvent)
        self.spin_padding = QDoubleSpinBox()
        self.spin_padding.setRange(5.0, 20.0)
        self.spin_padding.setDecimals(1)
        self.spin_padding.setValue(10.0)
        self.spin_padding.setSuffix(" Å")
        self.spin_padding.setToolTip(
            "tleap solvateBox padding around the solute. Ignored for implicit GBSA."
        )
        md_form.addRow("Box padding:", self.spin_padding)
        self.combo_openmm_platform = QComboBox()
        add_openmm_platform_combo(self.combo_openmm_platform)
        md_form.addRow("Compute:", self.combo_openmm_platform)
        self.spin_salt = QDoubleSpinBox()
        self.spin_salt.setRange(0.0, 2.0)
        self.spin_salt.setDecimals(2)
        self.spin_salt.setSingleStep(0.05)
        self.spin_salt.setValue(0.15)
        self.spin_salt.setSuffix(" M")
        md_form.addRow("Salt:", self.spin_salt)
        self.spin_temp = QDoubleSpinBox()
        self.spin_temp.setRange(200.0, 400.0)
        self.spin_temp.setDecimals(1)
        self.spin_temp.setValue(300.0)
        self.spin_temp.setSuffix(" K")
        md_form.addRow("Temperature:", self.spin_temp)
        self.spin_dt = QDoubleSpinBox()
        self.spin_dt.setRange(0.5, 4.0)
        self.spin_dt.setDecimals(1)
        self.spin_dt.setValue(2.0)
        self.spin_dt.setSuffix(" fs")
        md_form.addRow("Timestep:", self.spin_dt)
        self.spin_eq = QDoubleSpinBox()
        self.spin_eq.setRange(0.0, 5000.0)
        self.spin_eq.setDecimals(1)
        self.spin_eq.setValue(10.0)
        self.spin_eq.setSuffix(" ps")
        md_form.addRow("Equilibration:", self.spin_eq)
        self.spin_prod = QDoubleSpinBox()
        self.spin_prod.setRange(0.1, 20000.0)
        self.spin_prod.setDecimals(1)
        self.spin_prod.setValue(100.0)
        self.spin_prod.setSuffix(" ps")
        self.spin_prod.setToolTip(
            "Production length. CPU GBSA and explicit water are both slow; keep this "
            "modest unless you have a GPU OpenMM platform (CUDA or OpenCL)."
        )
        md_form.addRow("Production:", self.spin_prod)
        self.spin_snap = QDoubleSpinBox()
        self.spin_snap.setRange(0.1, 1000.0)
        self.spin_snap.setDecimals(1)
        self.spin_snap.setValue(10.0)
        self.spin_snap.setSuffix(" ps")
        md_form.addRow("MM-GBSA interval:", self.spin_snap)
        self.spin_min = QSpinBox()
        self.spin_min.setRange(0, 5000)
        self.spin_min.setSingleStep(50)
        self.spin_min.setValue(400)
        md_form.addRow("Minimize iterations:", self.spin_min)
        self.combo_restraint = QComboBox()
        self.combo_restraint.addItem("Backbone + ligand heavy atoms", "backbone_ligand")
        self.combo_restraint.addItem("Backbone heavy atoms", "backbone")
        self.combo_restraint.addItem("Cα only", "ca")
        md_form.addRow("Eq. restrain:", self.combo_restraint)
        self.spin_k_eq = QDoubleSpinBox()
        self.spin_k_eq.setRange(0.0, 50.0)
        self.spin_k_eq.setDecimals(1)
        self.spin_k_eq.setValue(10.0)
        self.spin_k_eq.setSuffix(" kcal/mol/Å²")
        md_form.addRow("Eq. restraint k:", self.spin_k_eq)
        self.spin_k_prod = QDoubleSpinBox()
        self.spin_k_prod.setRange(0.0, 50.0)
        self.spin_k_prod.setDecimals(1)
        self.spin_k_prod.setValue(0.0)
        self.spin_k_prod.setSuffix(" kcal/mol/Å²")
        self.spin_k_prod.setToolTip("0 turns restraints off during production.")
        md_form.addRow("Prod. restraint k:", self.spin_k_prod)
        self.chk_mmgbsa = QCheckBox("Score MM-GBSA on production snapshots")
        self.chk_mmgbsa.setChecked(True)
        md_form.addRow(self.chk_mmgbsa)
        root.addWidget(md_gb)

        self.results = QPlainTextEdit()
        self.results.setReadOnly(True)
        self.results.setPlaceholderText("MM-GBSA ensemble summary appears here after a run.")
        self.results.setMinimumHeight(120)
        root.addWidget(self.results)
        root.addWidget(citation_footer_label(md_dialog_footer_html(), self))

        self.chk_mmgbsa.toggled.connect(self._sync_score_options)
        self._sync_score_options()
        self._sync_solvent_options()

        btn_row = QHBoxLayout()
        self.btn_run = QPushButton("Run MD")
        self.btn_run.clicked.connect(self._on_run)
        btn_row.addWidget(self.btn_run)
        self.btn_analyze = QPushButton("Analyze…")
        self.btn_analyze.setEnabled(False)
        self.btn_analyze.setToolTip("Open Analyze Trajectory with this run's DCD and sidecar.")
        self.btn_analyze.clicked.connect(self._on_analyze)
        btn_row.addWidget(self.btn_analyze)
        btn_row.addStretch()
        self.btn_close = QPushButton("Close")
        self.btn_close.clicked.connect(self.close)
        btn_row.addWidget(self.btn_close)
        root.addLayout(btn_row)
        self._last_result = None

        self._signals = ProteinMDSignals(self)
        self._signals.finished.connect(self._on_finished)
        self._signals.failed.connect(self._on_failed)
        self._signals.progress.connect(self._append_log)
        self._input_tmp: Path | None = None
        make_window_minimizable(self)

    def prefill_from_viewer(self) -> None:
        self._refresh_structure_source()
        self._sync_score_options()
        self._sync_solvent_options()

    def _suggest_output_from_source(self) -> None:
        super()._suggest_output_from_source()
        last = (self.edit_out.text() or "").strip()
        if not last:
            return
        rec = Path(last)
        stem = rec.stem
        self.edit_dcd.setText(str(rec.with_name(f"{stem}.dcd")))
        self.edit_report.setText(str(rec.with_name(f"{stem}_mmgbsa.txt")))
        self.edit_csv.setText(str(rec.with_name(f"{stem}_mmgbsa.csv")))
        self.edit_checkpoint.setText(str(rec.with_name(f"{stem}.chk")))

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
        except Exception:  # noqa: BLE001
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
        except Exception:  # noqa: BLE001
            return False
        resns = {c.resn for c in comps if c.kind == "ligand"}
        return cif_has_component_bonds(text or "", resns)

    def _sync_score_options(self) -> None:
        on = self.chk_mmgbsa.isChecked()
        self.spin_snap.setEnabled(on)
        self.edit_report.setEnabled(on)
        self.edit_csv.setEnabled(on)

    def _sync_solvent_options(self) -> None:
        explicit = (self.combo_solvent.currentData() or "") == "tip3p"
        self.spin_padding.setEnabled(explicit)
        self.spin_salt.setToolTip(
            "NaCl concentration for tleap addIonsRand (explicit) or GB Debye screening (implicit)."
            if explicit
            else "GB Debye screening (1:1 salt). Default 0.15 M."
        )

    def _sync_output_suffix(self) -> None:
        path = (self.edit_out.text() or "").strip()
        if not path:
            return
        rec = Path(path)
        fmt = self.combo_out_fmt.currentData() or "cif"
        suffix = ".pdb" if fmt == "pdb" else ".cif"
        if rec.suffix.lower() != suffix:
            self.edit_out.setText(str(rec.with_suffix(suffix)))
            self._suggest_output_from_source()

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
            title, filt = "Last-frame PDB", "PDB (*.pdb);;All files (*.*)"
        else:
            title, filt = "Last-frame mmCIF", "mmCIF (*.cif *.mmcif *.mcif);;All files (*.*)"
        path, _ = QFileDialog.getSaveFileName(self, title, self.edit_out.text().strip(), filt)
        if path:
            self.edit_out.setText(path)

    def _browse_dcd(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Trajectory DCD", self.edit_dcd.text().strip(), "DCD (*.dcd);;All files (*.*)"
        )
        if path:
            self.edit_dcd.setText(path)

    def _browse_report(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "MM-GBSA report",
            self.edit_report.text().strip(),
            "Text (*.txt);;All files (*.*)",
        )
        if path:
            self.edit_report.setText(path)

    def _browse_csv(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "MM-GBSA CSV", self.edit_csv.text().strip(), "CSV (*.csv);;All files (*.*)"
        )
        if path:
            self.edit_csv.setText(path)

    def _browse_checkpoint(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "MD checkpoint",
            self.edit_checkpoint.text().strip(),
            "Checkpoint (*.chk);;All files (*.*)",
        )
        if path:
            self.edit_checkpoint.setText(path)

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
            QMessageBox.warning(self, "Molecular Dynamics", str(exc))
            return
        if not (text or "").strip():
            QMessageBox.information(self, "Molecular Dynamics", self._source_empty_message)
            return
        fmt = fmt or "pdb"
        if fmt not in _SOURCE_FMTS:
            QMessageBox.warning(self, "Molecular Dynamics", "MD supports PDB and mmCIF.")
            return
        if not self._source_has_ligand(text, fmt):
            QMessageBox.information(
                self,
                "Molecular Dynamics",
                "MD needs a protein–ligand complex.",
            )
            return
        out_path = (self.edit_out.text() or "").strip()
        if not out_path:
            QMessageBox.information(self, "Molecular Dynamics", "Set a last-frame path.")
            return
        out_fmt = self.combo_out_fmt.currentData() or "cif"
        rec = Path(out_path)
        if out_fmt == "pdb" and rec.suffix.lower() != ".pdb":
            rec = rec.with_suffix(".pdb")
        elif out_fmt != "pdb" and rec.suffix.lower() not in {".cif", ".mmcif", ".mcif"}:
            rec = rec.with_suffix(".cif")
        out_path = str(rec)
        self.edit_out.setText(out_path)
        if (
            not self.edit_ligand_smiles.text().strip()
            and not self.edit_ligand_ref.text().strip()
            and not self._source_has_cif_ligand_bonds(text, fmt)
        ):
            QMessageBox.information(
                self,
                "Molecular Dynamics",
                "GAFF/GAFF2 needs SMILES, an SDF/MOL2, or mmCIF _chem_comp_bond.",
            )
            return
        try:
            in_path = self._write_input_snapshot()
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Molecular Dynamics", str(exc))
            return
        score = self.chk_mmgbsa.isChecked()
        req = ProteinMDRequest(
            input_path=str(in_path),
            output_path=out_path,
            report_path=self.edit_report.text().strip() if score else "",
            dcd_path=self.edit_dcd.text().strip(),
            csv_path=self.edit_csv.text().strip() if score else "",
            protein_ff=self.combo_protein_ff.currentData() or "amber14",
            ligand_ff=self.combo_ligand_ff.currentData() or "gaff2",
            solvent=self.combo_solvent.currentData() or "gbn2",
            openmm_platform=self.combo_openmm_platform.currentData() or "auto",
            salt_m=float(self.spin_salt.value()),
            ligand_smiles=self.edit_ligand_smiles.text().strip(),
            ligand_ref_path=self.edit_ligand_ref.text().strip(),
            ligand_keys=self._ligand_keys(),
            keep_water=self.chk_keep_water.isChecked(),
            output_format=out_fmt,
            temperature_k=float(self.spin_temp.value()),
            timestep_fs=float(self.spin_dt.value()),
            minimize_iterations=int(self.spin_min.value()),
            equilibration_ps=float(self.spin_eq.value()),
            production_ps=float(self.spin_prod.value()),
            snapshot_ps=float(self.spin_snap.value()),
            restraint_set=self.combo_restraint.currentData() or "backbone_ligand",
            restraint_k_eq=float(self.spin_k_eq.value()),
            restraint_k_prod=float(self.spin_k_prod.value()),
            score_mmgbsa=score,
            box_padding_a=float(self.spin_padding.value()),
            checkpoint_path=self.edit_checkpoint.text().strip(),
            checkpoint_ps=20.0,
            resume=self.chk_resume.isChecked(),
        )
        self.btn_run.setEnabled(False)
        self.results.setPlainText("")
        solvent = self.combo_solvent.currentData() or "gbn2"
        kind = "explicit-solvent PME" if solvent == "tip3p" else "implicit-solvent"
        self._append_log(f"Starting {kind} OpenMM MD…")
        host = self._process_host()
        if host is not None:
            host.process_queue.enqueue(
                "Molecular Dynamics",
                lambda ev, r=req, sig=self._signals: ProteinMDWorker(
                    r, signals=sig, cancel_event=ev
                ),
            )
            return
        from PySide6.QtCore import QThreadPool

        QThreadPool.globalInstance().start(ProteinMDWorker(req, signals=self._signals))

    def _on_analyze(self) -> None:
        opener = getattr(self._viewer, "open_md_analysis_dialog", None)
        if opener is None:
            return
        opener(prefill=self._last_result)

    def _on_finished(self, result) -> None:
        self.btn_run.setEnabled(True)
        self._last_result = result
        self.btn_analyze.setEnabled(bool(getattr(result, "dcd_path", "") or ""))
        summary = getattr(result, "summary", "") or ""
        if summary:
            self.results.setPlainText(summary)
        path = getattr(result, "structure_path", "") or ""
        if path:
            self._append_log(f"Last frame written: {path}")
        mean = getattr(result, "delta_mean", None)
        n = getattr(result, "n_snapshots", 0) or 0
        if mean is not None:
            self._append_log(f"MM-GBSA mean ΔG = {float(mean):.2f} kcal/mol (n={int(n)})")
        self.finished_md.emit(result)

    def _on_failed(self, msg: str) -> None:
        self.btn_run.setEnabled(True)
        self._append_log(msg or "Molecular dynamics failed.")
        QMessageBox.warning(self, "Molecular Dynamics", msg or "Molecular dynamics failed.")
