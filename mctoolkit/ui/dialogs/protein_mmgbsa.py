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

"""Protein Viewer MM-GBSA dialog: 1-trajectory OpenMM GBn2 scoring."""

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

from ...reference.method_citations import mmgbsa_dialog_footer_html
from ...workers.protein_mmgbsa import (
    ProteinMMGBSARequest,
    ProteinMMGBSASignals,
    ProteinMMGBSAWorker,
)
from ..qt_widget_utils import append_viewer_log, make_window_minimizable
from .conformer_output import citation_footer_label
from .protein_prepare import _browse_path_row, add_openmm_platform_combo
from .protein_source_picker import ProteinStructureSourceMixin

_SOURCE_FMTS = frozenset({"pdb", "pqr", "cif"})


class ProteinMMGBSADialog(ProteinStructureSourceMixin, QDialog):
    """Options for Protein Viewer → Tools → Simulate → MM-GBSA."""

    scored = Signal(object)
    _source_output_tag = "mmgbsa"
    _source_output_suffix = ".txt"
    _source_tmp_prefix = "mctoolkit_mmgbsa_in_"
    _source_tool_title = "MM-GBSA"
    _source_empty_message = "Choose a Manager structure or a PDB/mmCIF file."

    def __init__(self, viewer, parent=None) -> None:
        super().__init__(parent or viewer)
        self._viewer = viewer
        self.setWindowTitle("MM-GBSA")
        self.setMinimumWidth(520)
        self.resize(560, 640)

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 6)
        root.setSpacing(6)

        io_gb = QGroupBox("Structure")
        io_form = QFormLayout(io_gb)
        io_form.setContentsMargins(8, 6, 8, 6)
        io_form.setSpacing(4)
        self._add_structure_source_rows(io_form)
        self.edit_out = QLineEdit()
        self.edit_out.setPlaceholderText("complex_mmgbsa.txt")
        io_form.addRow("Report:", _browse_path_row(self.edit_out, self._browse_report))
        self.edit_structure = QLineEdit()
        self.edit_structure.setPlaceholderText("Optional minimized mmCIF")
        io_form.addRow(
            "Minimized complex:",
            _browse_path_row(self.edit_structure, self._browse_structure),
        )
        self.chk_keep_water = QCheckBox("Keep waters already in the structure")
        self.chk_keep_water.setChecked(False)
        self.chk_keep_water.setToolTip(
            "Standard MM-GBSA strips crystal waters. Check only if you want them "
            "in the receptor (wet MM-GBSA)."
        )
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
        self.combo_ligand_ff.setToolTip(
            "GAFF2 (recommended) parameterizes the ligand with AmberTools (WSL on Windows)."
        )
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

        score_gb = QGroupBox("Scoring")
        score_form = QFormLayout(score_gb)
        score_form.setContentsMargins(8, 6, 8, 6)
        score_form.setSpacing(4)
        self.combo_protein_ff = QComboBox()
        self.combo_protein_ff.addItem("AMBER ff14SB", "amber14")
        self.combo_protein_ff.addItem("AMBER ff99SB-ILDN", "amber99sbildn")
        score_form.addRow("Protein force field:", self.combo_protein_ff)
        self.combo_solvent = QComboBox()
        self.combo_solvent.addItem("GBn2 GBSA (recommended)", "gbn2")
        self.combo_solvent.addItem("OBC2 GBSA", "obc2")
        self.combo_solvent.setToolTip(
            "1-trajectory MM-GBSA with OpenMM implicit solvent. Not experimental ΔG."
        )
        score_form.addRow("Solvation:", self.combo_solvent)
        self.combo_openmm_platform = QComboBox()
        add_openmm_platform_combo(self.combo_openmm_platform)
        score_form.addRow("Compute:", self.combo_openmm_platform)
        self.spin_salt = QDoubleSpinBox()
        self.spin_salt.setRange(0.0, 2.0)
        self.spin_salt.setDecimals(2)
        self.spin_salt.setSingleStep(0.05)
        self.spin_salt.setValue(0.15)
        self.spin_salt.setSuffix(" M")
        score_form.addRow("Salt:", self.spin_salt)
        self.chk_minimize = QCheckBox("Minimize complex before scoring")
        self.chk_minimize.setChecked(True)
        score_form.addRow(self.chk_minimize)
        self.combo_restraint = QComboBox()
        self.combo_restraint.addItem("Backbone + ligand heavy atoms", "backbone_ligand")
        self.combo_restraint.addItem("Backbone heavy atoms", "backbone")
        self.combo_restraint.addItem("Cα only", "ca")
        score_form.addRow("Restrain:", self.combo_restraint)
        self.spin_k = QDoubleSpinBox()
        self.spin_k.setRange(0.5, 50.0)
        self.spin_k.setDecimals(1)
        self.spin_k.setSingleStep(1.0)
        self.spin_k.setValue(10.0)
        self.spin_k.setSuffix(" kcal/mol/Å²")
        score_form.addRow("Restraint k:", self.spin_k)
        self.spin_iters = QSpinBox()
        self.spin_iters.setRange(50, 5000)
        self.spin_iters.setSingleStep(50)
        self.spin_iters.setValue(400)
        score_form.addRow("Max iterations:", self.spin_iters)
        root.addWidget(score_gb)

        self.results = QPlainTextEdit()
        self.results.setReadOnly(True)
        self.results.setPlaceholderText("MM-GBSA table (kcal/mol) appears here after a run.")
        self.results.setMinimumHeight(140)
        root.addWidget(self.results)
        root.addWidget(citation_footer_label(mmgbsa_dialog_footer_html(), self))

        self.chk_minimize.toggled.connect(self._sync_min_options)
        self._sync_min_options()

        btn_row = QHBoxLayout()
        self.btn_run = QPushButton("Score")
        self.btn_run.clicked.connect(self._on_run)
        btn_row.addWidget(self.btn_run)
        btn_row.addStretch()
        self.btn_close = QPushButton("Close")
        self.btn_close.clicked.connect(self.close)
        btn_row.addWidget(self.btn_close)
        root.addLayout(btn_row)

        self._signals = ProteinMMGBSASignals(self)
        self._signals.finished.connect(self._on_finished)
        self._signals.failed.connect(self._on_failed)
        self._signals.progress.connect(self._append_log)
        self._input_tmp: Path | None = None
        make_window_minimizable(self)

    def prefill_from_viewer(self) -> None:
        self._refresh_structure_source()
        self._sync_min_options()

    def _suggest_output_from_source(self) -> None:
        super()._suggest_output_from_source()
        report = (self.edit_out.text() or "").strip()
        if not report:
            return
        rec = Path(report)
        stem = rec.stem.removesuffix("_mmgbsa")
        self.edit_structure.setText(str(rec.with_name(f"{stem}_mmgbsa_min.cif")))

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

    def _sync_min_options(self) -> None:
        on = self.chk_minimize.isChecked()
        self.combo_restraint.setEnabled(on)
        self.spin_k.setEnabled(on)
        self.spin_iters.setEnabled(on)
        self.edit_structure.setEnabled(on)

    def _browse_ligand_ref(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Ligand bond-order file",
            self.edit_ligand_ref.text().strip(),
            "Ligand files (*.sdf *.sd *.mol *.mol2);;All files (*.*)",
        )
        if path:
            self.edit_ligand_ref.setText(path)

    def _browse_report(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "MM-GBSA report",
            self.edit_out.text().strip(),
            "Text (*.txt);;All files (*.*)",
        )
        if path:
            self.edit_out.setText(path)

    def _browse_structure(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Minimized complex",
            self.edit_structure.text().strip(),
            "mmCIF (*.cif *.mmcif *.mcif);;PDB (*.pdb);;All files (*.*)",
        )
        if path:
            self.edit_structure.setText(path)

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
            QMessageBox.warning(self, "MM-GBSA", str(exc))
            return
        if not (text or "").strip():
            QMessageBox.information(self, "MM-GBSA", self._source_empty_message)
            return
        fmt = fmt or "pdb"
        if fmt not in _SOURCE_FMTS:
            QMessageBox.warning(self, "MM-GBSA", "MM-GBSA supports PDB and mmCIF.")
            return
        if not self._source_has_ligand(text, fmt):
            QMessageBox.information(
                self,
                "MM-GBSA",
                "MM-GBSA needs a protein–ligand complex. Load a holo structure.",
            )
            return
        report_path = (self.edit_out.text() or "").strip()
        if not report_path:
            QMessageBox.information(self, "MM-GBSA", "Set a report path.")
            return
        rec = Path(report_path)
        if rec.suffix.lower() != ".txt":
            rec = rec.with_suffix(".txt")
            report_path = str(rec)
            self.edit_out.setText(report_path)
        if (
            not self.edit_ligand_smiles.text().strip()
            and not self.edit_ligand_ref.text().strip()
            and not self._source_has_cif_ligand_bonds(text, fmt)
        ):
            QMessageBox.information(
                self,
                "MM-GBSA",
                "GAFF/GAFF2 needs SMILES, an SDF/MOL2, or mmCIF _chem_comp_bond "
                "so AmberTools can assign ligand atom types.",
            )
            return
        try:
            in_path = self._write_input_snapshot()
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "MM-GBSA", str(exc))
            return
        struct_out = (
            (self.edit_structure.text() or "").strip() if self.chk_minimize.isChecked() else ""
        )
        out_fmt = "cif"
        if struct_out and Path(struct_out).suffix.lower() == ".pdb":
            out_fmt = "pdb"
        req = ProteinMMGBSARequest(
            input_path=str(in_path),
            report_path=report_path,
            protein_ff=self.combo_protein_ff.currentData() or "amber14",
            ligand_ff=self.combo_ligand_ff.currentData() or "gaff2",
            solvent=self.combo_solvent.currentData() or "gbn2",
            openmm_platform=self.combo_openmm_platform.currentData() or "auto",
            salt_m=float(self.spin_salt.value()),
            ligand_smiles=self.edit_ligand_smiles.text().strip(),
            ligand_ref_path=self.edit_ligand_ref.text().strip(),
            ligand_keys=self._ligand_keys(),
            keep_water=self.chk_keep_water.isChecked(),
            minimize_first=self.chk_minimize.isChecked(),
            restraint_set=self.combo_restraint.currentData() or "backbone_ligand",
            restraint_k_kcal_per_ang2=float(self.spin_k.value()),
            max_iterations=int(self.spin_iters.value()),
            structure_output_path=struct_out,
            output_format=out_fmt,
        )
        self.btn_run.setEnabled(False)
        self.results.setPlainText("")
        self._append_log("Starting 1-trajectory MM-GBSA…")
        host = self._process_host()
        if host is not None:
            host.process_queue.enqueue(
                "MM-GBSA",
                lambda ev, r=req, sig=self._signals: ProteinMMGBSAWorker(
                    r, signals=sig, cancel_event=ev
                ),
            )
            return
        from PySide6.QtCore import QThreadPool

        QThreadPool.globalInstance().start(ProteinMMGBSAWorker(req, signals=self._signals))

    def _on_finished(self, result) -> None:
        self.btn_run.setEnabled(True)
        summary = getattr(result, "summary", "") or ""
        report_path = getattr(result, "report_path", "") or ""
        if summary:
            self.results.setPlainText(summary)
        elif report_path and Path(report_path).is_file():
            self.results.setPlainText(Path(report_path).read_text(encoding="utf-8"))
        delta = getattr(result, "delta_total", None)
        if delta is not None:
            self._append_log(f"MM-GBSA ΔG = {float(delta):.2f} kcal/mol (no entropy)")
        if report_path:
            self._append_log(f"Report written: {report_path}")
        self.scored.emit(result)

    def _on_failed(self, msg: str) -> None:
        self.btn_run.setEnabled(True)
        self._append_log(msg or "MM-GBSA failed.")
        QMessageBox.warning(self, "MM-GBSA", msg or "MM-GBSA failed.")
