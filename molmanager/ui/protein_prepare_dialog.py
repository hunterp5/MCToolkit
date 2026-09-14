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

"""Protein Viewer Prepare dialog: PDBFixer, pdb2pqr, OpenMM restrained min."""

from __future__ import annotations

import tempfile
from pathlib import Path

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..workers.protein_prepare import (
    ProteinPrepareRequest,
    ProteinPrepareSignals,
    ProteinPrepareWorker,
)
from .qt_widget_utils import apply_monospace_to_text_edit, make_window_minimizable

_PREPARE_FMTS = frozenset({"pdb", "pqr", "cif"})


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


class ProteinPrepareDialog(QDialog):
    """Options and log for Protein Viewer → Prepare."""

    prepared = pyqtSignal(str)

    def __init__(self, viewer, parent=None) -> None:
        super().__init__(parent or viewer)
        self._viewer = viewer
        self.setWindowTitle("Prepare Structure")
        self.setMinimumWidth(500)
        self.resize(540, 640)

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 6)
        root.setSpacing(6)

        intro = QLabel(
            "Repair missing residues and side chains (PDBFixer), protonate at pH with "
            "pdb2pqr/PROPKA, then restrained OpenMM minimization. Defaults: AMBER ff14SB, "
            "GAFF2 ligand, GBn2 implicit solvent, backbone restraints. Highest-occupancy "
            "altlocs are kept. Pocket HIS/ASP/GLU states and Cα/pocket RMSD are written "
            "into the output remarks."
        )
        intro.setWordWrap(True)
        root.addWidget(intro)

        io_gb = QGroupBox("Structure")
        io_form = QFormLayout(io_gb)
        io_form.setContentsMargins(8, 6, 8, 6)
        io_form.setSpacing(4)
        self.lbl_source = QLabel("—")
        self.lbl_source.setWordWrap(True)
        io_form.addRow("Current:", self.lbl_source)
        self.edit_out = QLineEdit()
        self.edit_out.setPlaceholderText("receptor_prepared.cif")
        io_form.addRow("Output:", _browse_path_row(self.edit_out, self._browse_output))
        self.combo_out_fmt = QComboBox()
        self.combo_out_fmt.addItem("mmCIF (.cif)", "cif")
        self.combo_out_fmt.addItem("PDB (.pdb)", "pdb")
        self.combo_out_fmt.setToolTip("mmCIF keeps ligand bond orders in _chem_comp_bond.")
        self.combo_out_fmt.currentIndexChanged.connect(self._sync_output_suffix)
        io_form.addRow("Format:", self.combo_out_fmt)
        root.addWidget(io_gb)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        host = QWidget()
        host_l = QVBoxLayout(host)
        host_l.setContentsMargins(0, 0, 0, 0)
        host_l.setSpacing(6)

        opt_gb = QGroupBox("Pipeline")
        opt_form = QFormLayout(opt_gb)
        opt_form.setContentsMargins(8, 6, 8, 6)
        opt_form.setSpacing(4)

        self.chk_rebuild_loops = QCheckBox("Rebuild missing loops from SEQRES")
        self.chk_rebuild_loops.setChecked(True)
        self.chk_rebuild_loops.setToolTip(
            "Model internal sequence gaps, then let restrained minimization relax "
            "the new residues. Uncheck to fill only terminal gaps (safer for large "
            "disordered domains)."
        )
        opt_form.addRow(self.chk_rebuild_loops)

        self.chk_skip_pocket_loops = QCheckBox("Skip loop rebuild near the ligand")
        self.chk_skip_pocket_loops.setChecked(True)
        self.chk_skip_pocket_loops.setToolTip(
            "Do not fill SEQRES gaps whose flanking residues sit within 8 Å of the ligand. "
            "Rebuilt loops next to the site are models, not crystal coordinates."
        )
        opt_form.addRow(self.chk_skip_pocket_loops)

        self.chk_include_ligand = QCheckBox("Include ligand in PROPKA protonation")
        self.chk_include_ligand.setChecked(True)
        self.chk_include_ligand.setToolTip(
            "Keep organic HETATM in the structure while PROPKA assigns protein "
            "titration states (holo protonation). Recommended before docking."
        )
        opt_form.addRow(self.chk_include_ligand)

        self.chk_keep_ligand = QCheckBox("Keep ligand in prepared mmCIF")
        self.chk_keep_ligand.setChecked(True)
        self.chk_keep_ligand.setToolTip(
            "Leave the ligand in the prepared file. Uncheck for an apo receptor "
            "(ligand can still be present during PROPKA). The prepared file is mmCIF "
            "so ligand bond orders are kept in _chem_comp_bond. mmCIF inputs stay mmCIF."
        )
        opt_form.addRow(self.chk_keep_ligand)

        self.chk_protonate_ligand = QCheckBox("Protonate ligand (Uni-pKa at pH)")
        self.chk_protonate_ligand.setChecked(True)
        self.chk_protonate_ligand.setToolTip(
            "Pick the aqueous-dominant protomer at the same pH as PROPKA, then place it "
            "on the crystal coordinates. Needs SMILES, an SDF/MOL2, or mmCIF "
            "_chem_comp_bond. Requires the pka extra."
        )
        opt_form.addRow(self.chk_protonate_ligand)

        self.chk_pocket_ligand = QCheckBox("Reweight ligand protomer in the pocket")
        self.chk_pocket_ligand.setChecked(True)
        self.chk_pocket_ligand.setToolTip(
            "After protein protonation, shift Uni-pKa microstate free energies by a Coulomb "
            "term from pdb2pqr charges (distance-dependent dielectric). This is a pocket "
            "electrostatic estimate, not Poisson–Boltzmann or GBSA. Only protomers that are "
            "already populated in water (≥5%) are considered."
        )
        opt_form.addRow(self.chk_pocket_ligand)

        self.edit_ligand_smiles = QLineEdit()
        self.edit_ligand_smiles.setPlaceholderText(
            "SMILES, or empty when mmCIF has ligand _chem_comp_bond"
        )
        self.edit_ligand_smiles.setToolTip(
            "Used for Uni-pKa and to copy bond orders onto crystal coordinates. "
            "Leave empty if the mmCIF already has _chem_comp_bond for the ligand, "
            "or if ligand protonation is off (orders guessed from geometry)."
        )
        opt_form.addRow("Ligand SMILES:", self.edit_ligand_smiles)

        self.edit_ligand_ref = QLineEdit()
        self.edit_ligand_ref.setPlaceholderText("Optional SDF or MOL2")
        opt_form.addRow(
            "Bond-order file:",
            _browse_path_row(self.edit_ligand_ref, self._browse_ligand_ref),
        )

        self.chk_keep_selected_waters = QCheckBox("Keep Manager-selected waters")
        self.chk_keep_selected_waters.setChecked(False)
        self.chk_keep_selected_waters.setToolTip(
            "Keep water groups currently selected in the Manager through protonation "
            "and into the output. Other waters are stripped unless bridging waters "
            "are also kept. Select a Chain group or its Water row first."
        )
        opt_form.addRow(self.chk_keep_selected_waters)

        self.chk_keep_bridging_waters = QCheckBox("Keep waters near ligand (≤3.5 Å, occ≥0.5)")
        self.chk_keep_bridging_waters.setChecked(False)
        self.chk_keep_bridging_waters.setToolTip(
            "Keep crystallographic waters whose oxygen is within 3.5 Å of a ligand "
            "heavy atom, occupancy ≥ 0.5, and B-factor ≤ 80. Combined with Manager "
            "selection when both are on."
        )
        opt_form.addRow(self.chk_keep_bridging_waters)

        self.chk_remove_other_heterogens = QCheckBox("Strip metals and other non-ligand HETATM")
        self.chk_remove_other_heterogens.setChecked(True)
        self.chk_remove_other_heterogens.setToolTip(
            "Removes ions, cofactors, and crystallization additives. Uncheck to keep "
            "a catalytic metal or tightly bound cofactor."
        )
        opt_form.addRow(self.chk_remove_other_heterogens)

        self.spin_ph = QDoubleSpinBox()
        self.spin_ph.setRange(0.0, 14.0)
        self.spin_ph.setDecimals(1)
        self.spin_ph.setSingleStep(0.1)
        self.spin_ph.setValue(7.4)
        self.spin_ph.setToolTip(
            "pH for PROPKA protein titration and Uni-pKa ligand protomer selection."
        )
        opt_form.addRow("pH:", self.spin_ph)
        host_l.addWidget(opt_gb)

        min_gb = QGroupBox("Minimization")
        min_form = QFormLayout(min_gb)
        min_form.setContentsMargins(8, 6, 8, 6)
        min_form.setSpacing(4)

        self.chk_minimize = QCheckBox("Restrained minimization")
        self.chk_minimize.setChecked(False)
        self.chk_minimize.setToolTip(
            "Harmonic restraints on experimental atoms so rebuilt loops, hydrogens, "
            "and the ligand can relieve clashes without the fold drifting."
        )
        min_form.addRow(self.chk_minimize)

        self.combo_protein_ff = QComboBox()
        self.combo_protein_ff.addItem("AMBER ff14SB", "amber14")
        self.combo_protein_ff.addItem("AMBER ff99SB-ILDN", "amber99sbildn")
        self.combo_protein_ff.setToolTip("Protein force field for OpenMM minimization.")
        min_form.addRow("Protein force field:", self.combo_protein_ff)

        self.combo_ligand_ff = QComboBox()
        self.combo_ligand_ff.addItem("GAFF2", "gaff2")
        self.combo_ligand_ff.addItem("OpenFF Sage", "openff-2.2.0")
        self.combo_ligand_ff.setToolTip(
            "Small-molecule force field paired with AMBER. Sage needs OpenFF Toolkit."
        )
        min_form.addRow("Ligand force field:", self.combo_ligand_ff)

        self.combo_solvent = QComboBox()
        self.combo_solvent.addItem("GBn2 GBSA (recommended)", "gbn2")
        self.combo_solvent.addItem("OBC2 GBSA", "obc2")
        self.combo_solvent.addItem("Vacuum", "vacuum")
        self.combo_solvent.setToolTip(
            "GBn2 is the usual docking-prep implicit solvent. Vacuum over-attracts "
            "charges and can distort the pocket; it is a fallback if GB cannot be built."
        )
        min_form.addRow("Solvation:", self.combo_solvent)

        self.spin_salt = QDoubleSpinBox()
        self.spin_salt.setRange(0.0, 2.0)
        self.spin_salt.setDecimals(2)
        self.spin_salt.setSingleStep(0.05)
        self.spin_salt.setValue(0.15)
        self.spin_salt.setSuffix(" M")
        self.spin_salt.setToolTip("1:1 salt for GB Debye screening (ignored in vacuum).")
        min_form.addRow("Salt:", self.spin_salt)

        self.combo_restraint = QComboBox()
        self.combo_restraint.addItem("Backbone heavy atoms", "backbone")
        self.combo_restraint.addItem("Cα only", "ca")
        self.combo_restraint.addItem("Backbone + ligand heavy atoms", "backbone_ligand")
        self.combo_restraint.setToolTip(
            "Backbone restraints keep the fold and pocket orientation. Cα-only lets "
            "side chains move more. Ligand heavy-atom restraints reduce ligand drift."
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
        host_l.addWidget(min_gb)
        host_l.addStretch()
        scroll.setWidget(host)
        root.addWidget(scroll, 1)

        self.chk_include_ligand.toggled.connect(self._sync_ligand_options)
        self.chk_protonate_ligand.toggled.connect(self._sync_ligand_options)
        self.chk_minimize.toggled.connect(self._sync_min_options)
        self.combo_solvent.currentIndexChanged.connect(self._sync_min_options)
        self.chk_rebuild_loops.toggled.connect(self._sync_min_options)
        self._sync_ligand_options()
        self._sync_min_options()

        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(110)
        self.log.setPlaceholderText("Log")
        apply_monospace_to_text_edit(self.log)
        root.addWidget(self.log)

        btn_row = QHBoxLayout()
        self.btn_run = QPushButton("Prepare")
        self.btn_run.clicked.connect(self._on_run)
        btn_row.addWidget(self.btn_run)
        btn_row.addStretch()
        self.btn_close = QPushButton("Close")
        self.btn_close.clicked.connect(self.close)
        btn_row.addWidget(self.btn_close)
        root.addLayout(btn_row)

        self._signals = ProteinPrepareSignals(self)
        self._signals.finished.connect(self._on_finished)
        self._signals.failed.connect(self._on_failed)
        self._input_tmp: Path | None = None

        make_window_minimizable(self)

    def prefill_from_viewer(self) -> None:
        viewer = self._viewer
        name, _text, _fmt, path = viewer.prepare_source()
        self.lbl_source.setText(name or "—")
        if path is not None and not (self.edit_out.text() or "").strip():
            suggested = path.with_name(f"{path.stem}_prepared.cif")
            self.edit_out.setText(str(suggested))
        self._refresh_water_label()

    def _refresh_water_label(self) -> None:
        keys = self._viewer.prepare_water_keys()
        if keys:
            self.chk_keep_selected_waters.setText(
                f"Keep Manager-selected waters ({len(keys)} residue{'s' if len(keys) != 1 else ''})"
            )
        else:
            self.chk_keep_selected_waters.setText("Keep Manager-selected waters")

    def _source_has_ligand(self, text: str, fmt: str) -> bool:
        from ..structure_components import parse_structure_components

        try:
            comps = parse_structure_components(text or "", fmt or "pdb")
        except Exception:
            return False
        return any(c.kind == "ligand" for c in comps)

    def _source_has_cif_ligand_bonds(self, text: str, fmt: str) -> bool:
        from ..structure_components import cif_has_component_bonds, parse_structure_components

        if (fmt or "").lower() not in {"cif", "mmcif"}:
            return False
        try:
            comps = parse_structure_components(text or "", fmt)
        except Exception:
            return False
        resns = {c.resn for c in comps if c.kind == "ligand"}
        return cif_has_component_bonds(text or "", resns)

    def _sync_ligand_options(self) -> None:
        include = self.chk_include_ligand.isChecked()
        self.chk_keep_ligand.setEnabled(include)
        self.chk_protonate_ligand.setEnabled(include)
        self.edit_ligand_smiles.setEnabled(include)
        self.edit_ligand_ref.setEnabled(include)
        protonate = include and self.chk_protonate_ligand.isChecked()
        pocket_was_enabled = self.chk_pocket_ligand.isEnabled()
        self.chk_pocket_ligand.setEnabled(protonate)
        if protonate and not pocket_was_enabled:
            self.chk_pocket_ligand.setChecked(True)
        elif not protonate:
            self.chk_pocket_ligand.blockSignals(True)
            self.chk_pocket_ligand.setChecked(False)
            self.chk_pocket_ligand.blockSignals(False)
        self.combo_ligand_ff.setEnabled(include)
        self.chk_keep_bridging_waters.setEnabled(include)
        if not include:
            self.chk_keep_bridging_waters.setChecked(False)
        self._sync_min_options()

    def _sync_min_options(self) -> None:
        on = self.chk_minimize.isChecked()
        self.combo_protein_ff.setEnabled(on)
        self.combo_ligand_ff.setEnabled(on and self.chk_include_ligand.isChecked())
        self.combo_solvent.setEnabled(on)
        gb = (self.combo_solvent.currentData() or "gbn2") != "vacuum"
        self.spin_salt.setEnabled(on and gb)
        self.combo_restraint.setEnabled(on)
        self.spin_k.setEnabled(on)
        self.spin_iters.setEnabled(on)
        loops = self.chk_rebuild_loops.isChecked()
        self.chk_skip_pocket_loops.setEnabled(loops)
        if not loops:
            self.chk_skip_pocket_loops.setChecked(False)

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
            title = "Prepared PDB"
            filt = "PDB (*.pdb);;All files (*.*)"
        else:
            title = "Prepared mmCIF"
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
        t = (text or "").rstrip()
        if not t:
            return
        self.log.append(t)

    def _process_host(self):
        parent = self._viewer
        while parent is not None:
            if hasattr(parent, "process_queue"):
                return parent
            parent = parent.parent()
        return None

    def _write_input_snapshot(self) -> Path:
        viewer = self._viewer
        _name, text, fmt, _path = viewer.prepare_source()
        fmt = fmt or "pdb"
        if fmt not in _PREPARE_FMTS:
            raise ValueError("Prepare supports PDB and mmCIF structures.")
        suffix = ".cif" if fmt == "cif" else ".pdb"
        tmp_dir = Path(tempfile.mkdtemp(prefix="molmanager_prepare_in_"))
        path = tmp_dir / f"input{suffix}"
        path.write_text(text, encoding="utf-8")
        self._input_tmp = path
        return path

    def _on_run(self) -> None:
        viewer = self._viewer
        _name, text, fmt, _path = viewer.prepare_source()
        if not (text or "").strip():
            QMessageBox.information(self, "Prepare Structure", "Open a structure first.")
            return
        fmt = fmt or "pdb"
        if fmt not in _PREPARE_FMTS:
            QMessageBox.warning(
                self,
                "Prepare Structure",
                "Prepare supports PDB and mmCIF. Convert or reload as PDB first.",
            )
            return
        out_path = (self.edit_out.text() or "").strip()
        if not out_path:
            QMessageBox.information(self, "Prepare Structure", "Set an output path.")
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
            keep_water_keys = self._viewer.prepare_water_keys()
            if not keep_water_keys:
                QMessageBox.information(
                    self,
                    "Prepare Structure",
                    "Select water groups in the Manager (a Chain row or its Water row), "
                    "then try again — or uncheck Keep Manager-selected waters.",
                )
                return
        if (
            self.chk_include_ligand.isChecked()
            and self.chk_protonate_ligand.isChecked()
            and not self.edit_ligand_smiles.text().strip()
            and not self.edit_ligand_ref.text().strip()
            and self._source_has_ligand(text, fmt)
            and not self._source_has_cif_ligand_bonds(text, fmt)
        ):
            QMessageBox.information(
                self,
                "Prepare Structure",
                "Ligand protonation needs SMILES, an SDF/MOL2, or mmCIF _chem_comp_bond "
                "so Uni-pKa can pick the protomer at this pH. Add one, or uncheck "
                "Protonate ligand (Uni-pKa).",
            )
            return
        try:
            in_path = self._write_input_snapshot()
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Prepare Structure", str(exc))
            return

        req = ProteinPrepareRequest(
            input_path=str(in_path),
            output_pdb_path=out_path,
            ph=float(self.spin_ph.value()),
            rebuild_missing_loops=self.chk_rebuild_loops.isChecked(),
            include_ligand=self.chk_include_ligand.isChecked(),
            keep_ligand=self.chk_keep_ligand.isChecked(),
            keep_water_keys=keep_water_keys,
            keep_bridging_waters=self.chk_keep_bridging_waters.isChecked(),
            remove_other_heterogens=self.chk_remove_other_heterogens.isChecked(),
            minimize=self.chk_minimize.isChecked(),
            ligand_smiles=self.edit_ligand_smiles.text().strip(),
            ligand_ref_path=self.edit_ligand_ref.text().strip(),
            protonate_ligand=self.chk_protonate_ligand.isChecked(),
            pocket_ligand_protonation=self.chk_pocket_ligand.isChecked(),
            restraint_k_kcal_per_ang2=float(self.spin_k.value()),
            max_minimize_iterations=int(self.spin_iters.value()),
            protein_ff=self.combo_protein_ff.currentData() or "amber14",
            ligand_ff=self.combo_ligand_ff.currentData() or "gaff2",
            solvent=self.combo_solvent.currentData() or "gbn2",
            salt_m=float(self.spin_salt.value()),
            restraint_set=self.combo_restraint.currentData() or "backbone",
            skip_pocket_loops=self.chk_skip_pocket_loops.isChecked(),
            output_format=out_fmt,
        )
        self.btn_run.setEnabled(False)
        self._append_log("Starting Prepare (PDBFixer → Uni-pKa/pdb2pqr → OpenMM)…")
        host = self._process_host()
        if host is not None:
            host.process_queue.enqueue(
                "Prepare Structure",
                lambda ev, r=req, sig=self._signals: ProteinPrepareWorker(
                    r, signals=sig, cancel_event=ev
                ),
            )
            return
        from PyQt5.QtCore import QThreadPool

        QThreadPool.globalInstance().start(ProteinPrepareWorker(req, signals=self._signals))

    def _on_finished(self, output_pdb: str) -> None:
        self.btn_run.setEnabled(True)
        self._append_log(f"Prepared file written: {output_pdb}")
        self.prepared.emit(output_pdb)

    def _on_failed(self, msg: str) -> None:
        self.btn_run.setEnabled(True)
        self._append_log(msg or "Structure preparation failed.")
