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

"""Protein Viewer pdb2pqr dialog: protonate the currently loaded structure."""

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
    QVBoxLayout,
)

from ...workers.protein_prepare import (
    ProteinPrepareRequest,
    ProteinPrepareSignals,
    ProteinPrepareWorker,
)
from ..qt_widget_utils import append_viewer_log, make_window_minimizable
from .protein_prepare import _PREPARE_FMTS, _browse_path_row
from .protein_source_picker import ProteinStructureSourceMixin


class ProteinPdb2pqrDialog(ProteinStructureSourceMixin, QDialog):
    """Options for Protein Viewer → Tools → Prepare → pdb2pqr."""

    prepared = Signal(str)
    _source_output_tag = "protonated"
    _source_tmp_prefix = "molmanager_pdb2pqr_in_"
    _source_tool_title = "pdb2pqr"
    _source_empty_message = "Choose a Manager structure or a PDB/mmCIF file."

    def __init__(self, viewer, parent=None) -> None:
        super().__init__(parent or viewer)
        self._viewer = viewer
        self.setWindowTitle("pdb2pqr")
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
        self.edit_out.setPlaceholderText("receptor_protonated.cif")
        io_form.addRow("Output:", _browse_path_row(self.edit_out, self._browse_output))
        self.combo_out_fmt = QComboBox()
        self.combo_out_fmt.addItem("mmCIF (.cif)", "cif")
        self.combo_out_fmt.addItem("PDB (.pdb)", "pdb")
        self.combo_out_fmt.setToolTip("mmCIF keeps ligand bond orders in _chem_comp_bond.")
        self.combo_out_fmt.currentIndexChanged.connect(self._sync_output_suffix)
        io_form.addRow("Format:", self.combo_out_fmt)
        root.addWidget(io_gb)

        pqr_gb = QGroupBox("pdb2pqr")
        pqr_form = QFormLayout(pqr_gb)
        pqr_form.setContentsMargins(8, 6, 8, 6)
        pqr_form.setSpacing(4)

        self.spin_ph = QDoubleSpinBox()
        self.spin_ph.setRange(0.0, 14.0)
        self.spin_ph.setDecimals(1)
        self.spin_ph.setSingleStep(0.1)
        self.spin_ph.setValue(7.4)
        self.spin_ph.setToolTip(
            "pH for PROPKA protein titration and Uni-pKa ligand protomer selection."
        )
        pqr_form.addRow("pH:", self.spin_ph)

        self.chk_include_ligand = QCheckBox("Include ligand in PROPKA protonation")
        self.chk_include_ligand.setChecked(True)
        self.chk_include_ligand.setToolTip(
            "Keep organic HETATM in the structure while PROPKA assigns protein "
            "titration states (holo protonation). Recommended before docking."
        )
        pqr_form.addRow(self.chk_include_ligand)

        self.chk_keep_ligand = QCheckBox("Keep ligand in output mmCIF")
        self.chk_keep_ligand.setChecked(True)
        self.chk_keep_ligand.setToolTip(
            "Leave the ligand in the protonated file. Uncheck for an apo receptor "
            "(ligand can still be present during PROPKA)."
        )
        pqr_form.addRow(self.chk_keep_ligand)

        self.chk_protonate_ligand = QCheckBox("Protonate ligand (Uni-pKa at pH)")
        self.chk_protonate_ligand.setChecked(True)
        self.chk_protonate_ligand.setToolTip(
            "Pick the aqueous-dominant protomer at the same pH as PROPKA, then place it "
            "on the crystal coordinates. Needs SMILES, an SDF/MOL2, or mmCIF "
            "_chem_comp_bond. Requires the pka extra."
        )
        pqr_form.addRow(self.chk_protonate_ligand)

        self.chk_pocket_ligand = QCheckBox("Reweight ligand protomer in the pocket")
        self.chk_pocket_ligand.setChecked(True)
        self.chk_pocket_ligand.setToolTip(
            "After protein protonation, shift Uni-pKa microstate free energies by a Coulomb "
            "term from pdb2pqr charges (distance-dependent dielectric). This is a pocket "
            "electrostatic estimate, not Poisson–Boltzmann or GBSA. Only protomers that are "
            "already populated in water (≥5%) are considered."
        )
        pqr_form.addRow(self.chk_pocket_ligand)

        self.edit_ligand_smiles = QLineEdit()
        self.edit_ligand_smiles.setPlaceholderText(
            "SMILES, or empty when mmCIF has ligand _chem_comp_bond"
        )
        self.edit_ligand_smiles.setToolTip(
            "Used for Uni-pKa and to copy bond orders onto crystal coordinates. "
            "Leave empty if the mmCIF already has _chem_comp_bond for the ligand, "
            "or if ligand protonation is off (orders guessed from geometry)."
        )
        pqr_form.addRow("Ligand SMILES:", self.edit_ligand_smiles)

        self.edit_ligand_ref = QLineEdit()
        self.edit_ligand_ref.setPlaceholderText("Optional SDF or MOL2")
        pqr_form.addRow(
            "Bond-order file:",
            _browse_path_row(self.edit_ligand_ref, self._browse_ligand_ref),
        )

        self.chk_keep_water = QCheckBox("Keep waters already in the structure")
        self.chk_keep_water.setChecked(True)
        self.chk_keep_water.setToolTip(
            "Leave crystallographic or prepared waters in the protonated file. "
            "Uncheck to drop them with pdb2pqr --drop-water."
        )
        pqr_form.addRow(self.chk_keep_water)
        root.addWidget(pqr_gb)

        btn_row = QHBoxLayout()
        self.btn_run = QPushButton("pdb2pqr")
        self.btn_run.clicked.connect(self._on_run)
        btn_row.addWidget(self.btn_run)
        btn_row.addStretch()
        self.btn_close = QPushButton("Close")
        self.btn_close.clicked.connect(self.close)
        btn_row.addWidget(self.btn_close)
        root.addLayout(btn_row)

        self.chk_include_ligand.toggled.connect(self._sync_ligand_options)
        self.chk_protonate_ligand.toggled.connect(self._sync_ligand_options)
        self._sync_ligand_options()

        self._signals = ProteinPrepareSignals(self)
        self._signals.finished.connect(self._on_finished)
        self._signals.failed.connect(self._on_failed)
        self._signals.progress.connect(self._append_log)
        self._input_tmp: Path | None = None

        make_window_minimizable(self)

    def prefill_from_viewer(self) -> None:
        self._refresh_structure_source()

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
            title = "Protonated PDB"
            filt = "PDB (*.pdb);;All files (*.*)"
        else:
            title = "Protonated mmCIF"
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
            QMessageBox.warning(self, "pdb2pqr", str(exc))
            return
        if not (text or "").strip():
            QMessageBox.information(self, "pdb2pqr", self._source_empty_message)
            return
        fmt = fmt or "pdb"
        if fmt not in _PREPARE_FMTS:
            QMessageBox.warning(
                self,
                "pdb2pqr",
                "pdb2pqr supports PDB and mmCIF. Convert or reload as PDB first.",
            )
            return
        out_path = (self.edit_out.text() or "").strip()
        if not out_path:
            QMessageBox.information(self, "pdb2pqr", "Set an output path.")
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
                "pdb2pqr",
                "Ligand protonation needs SMILES, an SDF/MOL2, or mmCIF _chem_comp_bond "
                "so Uni-pKa can pick the protomer at this pH. Add one, or uncheck "
                "Protonate ligand (Uni-pKa).",
            )
            return
        try:
            in_path = self._write_input_snapshot()
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "pdb2pqr", str(exc))
            return

        req = ProteinPrepareRequest(
            input_path=str(in_path),
            output_pdb_path=out_path,
            ph=float(self.spin_ph.value()),
            rebuild_missing_loops=False,
            replace_nonstandard=False,
            include_ligand=self.chk_include_ligand.isChecked(),
            keep_ligand=self.chk_keep_ligand.isChecked(),
            keep_waters=self.chk_keep_water.isChecked(),
            remove_other_heterogens=False,
            strip_additives=False,
            repair=False,
            protonate=True,
            minimize=False,
            ligand_smiles=self.edit_ligand_smiles.text().strip(),
            ligand_ref_path=self.edit_ligand_ref.text().strip(),
            protonate_ligand=self.chk_protonate_ligand.isChecked(),
            pocket_ligand_protonation=self.chk_pocket_ligand.isChecked(),
            output_format=out_fmt,
            write_smina=False,
        )
        self.btn_run.setEnabled(False)
        steps = ["pdb2pqr/PROPKA"]
        if self.chk_include_ligand.isChecked() and self.chk_protonate_ligand.isChecked():
            steps.insert(0, "Uni-pKa")
        self._append_log("Starting pdb2pqr: " + " → ".join(steps))
        host = self._process_host()
        if host is not None:
            host.process_queue.enqueue(
                "pdb2pqr",
                lambda ev, r=req, sig=self._signals: ProteinPrepareWorker(
                    r, signals=sig, cancel_event=ev
                ),
            )
            return
        from PySide6.QtCore import QThreadPool

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
        self._append_log(f"Protonated file written: {path}")
        self.prepared.emit(path)
        self.close()

    def _on_failed(self, msg: str) -> None:
        self.btn_run.setEnabled(True)
        self._append_log(msg or "pdb2pqr failed.")
