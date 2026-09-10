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

"""Tools → Dock → EasyDock…: EasyDock virtual screening of table ligands."""

from __future__ import annotations

from pathlib import Path

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ...bundled_paths import default_external_executable
from ...easydock_backend import (
    AUTOBOX_LIGAND_FILTER,
    ENGINE_SMINA,
    ENGINE_VINA,
    EasyDockParams,
    default_engine,
    is_autobox_ligand_path,
    smina_executable_ok,
    vina_engine_available,
)
from ...science_citations import easydock_dialog_footer_html
from ..qt_widget_utils import make_window_minimizable
from .scope import selection_scope_checked


class EasyDockDialog(QDialog):
    """Configure receptor PDBQT, search box, engine, and table writeback."""

    def __init__(self, selected_row_count: int = 0, parent=None):
        super().__init__(parent)
        self.parent_app = parent
        self.setWindowTitle("Dock")
        self.setMinimumWidth(520)
        self._have_selection = selected_row_count > 0

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 8)
        root.setSpacing(8)

        form = QFormLayout()
        form.setSpacing(6)
        self.engine_combo = QComboBox()
        self.engine_combo.addItem("Smina", ENGINE_SMINA)
        self.engine_combo.addItem("Vina", ENGINE_VINA)
        self.engine_combo.setToolTip(
            "Smina is the Windows-friendly CLI. Vina uses the EasyDock Python API when "
            "the vina package is installed (typically Linux/macOS)."
        )
        form.addRow("Engine:", self.engine_combo)

        rec_row = QHBoxLayout()
        rec_row.setContentsMargins(0, 0, 0, 0)
        self.receptor_edit = QLineEdit()
        self.receptor_edit.setPlaceholderText("Path to receptor.pdbqt")
        self.receptor_edit.setToolTip(
            "Rigid receptor in PDBQT (Tools → Dock → Prepare → Receptor PDB… then PDBQT…)."
        )
        rec_row.addWidget(self.receptor_edit, 1)
        btn_r = QPushButton("Browse…")
        btn_r.clicked.connect(self._browse_receptor)
        rec_row.addWidget(btn_r)
        rec_w = QWidget()
        rec_w.setLayout(rec_row)
        form.addRow("Receptor:", rec_w)

        exe_row = QHBoxLayout()
        exe_row.setContentsMargins(0, 0, 0, 0)
        self.smina_edit = QLineEdit(default_external_executable("smina"))
        self.smina_edit.setToolTip("Smina executable (bundled resources/bin or PATH).")
        exe_row.addWidget(self.smina_edit, 1)
        btn_e = QPushButton("Browse…")
        btn_e.clicked.connect(self._browse_smina)
        exe_row.addWidget(btn_e)
        self._smina_row = QWidget()
        self._smina_row.setLayout(exe_row)
        form.addRow("Smina executable:", self._smina_row)
        root.addLayout(form)

        box_gb = QGroupBox("Search box (Å)")
        box_form = QFormLayout(box_gb)
        auto_row = QHBoxLayout()
        auto_row.setContentsMargins(0, 0, 0, 0)
        self.autobox_cb = QCheckBox("Autobox")
        self.autobox_cb.setToolTip(
            "Let Smina set the search box from a reference ligand (--autobox_ligand). "
            "Smina only. Center and size are ignored."
        )
        auto_row.addWidget(self.autobox_cb)
        self.edit_autobox_ligand = QLineEdit()
        self.edit_autobox_ligand.setPlaceholderText("ligand.pdb or ligand.pdbqt")
        self.edit_autobox_ligand.setToolTip(
            "Reference ligand whose coordinates define the autobox. PDB or PDBQT. "
            "Used for every table ligand."
        )
        self.btn_autobox_ligand = QPushButton("Browse…")
        self.btn_autobox_ligand.setToolTip("Choose a reference ligand for the autobox.")
        self.btn_autobox_ligand.clicked.connect(self._browse_autobox_ligand)
        lig_row = QHBoxLayout()
        lig_row.setContentsMargins(0, 0, 0, 0)
        lig_row.setSpacing(4)
        lig_row.addWidget(self.edit_autobox_ligand, 1)
        lig_row.addWidget(self.btn_autobox_ligand)
        lig_w = QWidget()
        lig_w.setLayout(lig_row)
        self._autobox_lig_row = lig_w
        auto_row.addWidget(lig_w, 1)
        auto_row.addWidget(QLabel("Padding:"))
        self.spin_autobox_add = QDoubleSpinBox()
        self.spin_autobox_add.setRange(0.0, 50.0)
        self.spin_autobox_add.setDecimals(2)
        self.spin_autobox_add.setSingleStep(0.5)
        self.spin_autobox_add.setValue(4.0)
        self.spin_autobox_add.setSuffix(" Å")
        self.spin_autobox_add.setToolTip(
            "Buffer added around the ligand bounding box (--autobox_add). Smina default is 4 Å."
        )
        auto_row.addWidget(self.spin_autobox_add)
        auto_w = QWidget()
        auto_w.setLayout(auto_row)
        box_form.addRow(auto_w)

        self.spin_cx = QDoubleSpinBox()
        self.spin_cy = QDoubleSpinBox()
        self.spin_cz = QDoubleSpinBox()
        for sp in (self.spin_cx, self.spin_cy, self.spin_cz):
            sp.setRange(-10_000.0, 10_000.0)
            sp.setDecimals(3)
            sp.setSingleStep(0.5)
        box_form.addRow("Center X:", self.spin_cx)
        box_form.addRow("Center Y:", self.spin_cy)
        box_form.addRow("Center Z:", self.spin_cz)
        self.spin_sx = QDoubleSpinBox()
        self.spin_sy = QDoubleSpinBox()
        self.spin_sz = QDoubleSpinBox()
        for sp in (self.spin_sx, self.spin_sy, self.spin_sz):
            sp.setRange(1.0, 500.0)
            sp.setDecimals(2)
            sp.setSingleStep(1.0)
            sp.setValue(20.0)
        box_form.addRow("Size X:", self.spin_sx)
        box_form.addRow("Size Y:", self.spin_sy)
        box_form.addRow("Size Z:", self.spin_sz)
        self.autobox_cb.toggled.connect(self._sync_autobox)
        root.addWidget(box_gb)

        opt_gb = QGroupBox("Search parameters")
        opt_form = QFormLayout(opt_gb)
        self.spin_exhaust = QSpinBox()
        self.spin_exhaust.setRange(1, 64)
        self.spin_exhaust.setValue(8)
        opt_form.addRow("Exhaustiveness:", self.spin_exhaust)
        self.spin_modes = QSpinBox()
        self.spin_modes.setRange(1, 100)
        self.spin_modes.setValue(9)
        opt_form.addRow("Num poses:", self.spin_modes)
        self.spin_energy_range = QDoubleSpinBox()
        self.spin_energy_range.setRange(0.5, 50.0)
        self.spin_energy_range.setDecimals(2)
        self.spin_energy_range.setValue(3.0)
        self.spin_energy_range.setToolTip(
            "Smina maximum energy window (kcal/mol) from the best pose."
        )
        opt_form.addRow("Energy range:", self.spin_energy_range)
        self.spin_seed = QSpinBox()
        self.spin_seed.setRange(0, 2_147_483_647)
        self.spin_seed.setValue(0)
        opt_form.addRow("Seed:", self.spin_seed)
        self.spin_cpu = QSpinBox()
        self.spin_cpu.setRange(0, 128)
        self.spin_cpu.setValue(0)
        self.spin_cpu.setSpecialValueText("auto")
        opt_form.addRow("CPU threads:", self.spin_cpu)
        root.addWidget(opt_gb)

        out_gb = QGroupBox("Table output")
        out_form = QFormLayout(out_gb)
        self.score_col_edit = QLineEdit("Dock score")
        out_form.addRow("Score column:", self.score_col_edit)
        self.write_poses_cb = QCheckBox("Write poses to confs column")
        self.write_poses_cb.setChecked(True)
        self.write_poses_cb.setToolTip("Packed 3D poses for View Conformers / 3D viewer.")
        out_form.addRow(self.write_poses_cb)
        sdf_row = QHBoxLayout()
        sdf_row.setContentsMargins(0, 0, 0, 0)
        self.sdf_edit = QLineEdit()
        self.sdf_edit.setPlaceholderText("Optional SDF of poses")
        sdf_row.addWidget(self.sdf_edit, 1)
        btn_sdf = QPushButton("Browse…")
        btn_sdf.clicked.connect(self._browse_sdf)
        sdf_row.addWidget(btn_sdf)
        sdf_w = QWidget()
        sdf_w.setLayout(sdf_row)
        out_form.addRow("Save SDF:", sdf_w)
        root.addWidget(out_gb)

        self.only_selected_cb = QCheckBox("Selected Rows Only")
        self._only_selected_scope_prefix = "Selected Rows Only"
        if self._have_selection:
            self.only_selected_cb.setText(
                f"{self._only_selected_scope_prefix} ({selected_row_count} row(s))"
            )
        else:
            self.only_selected_cb.setEnabled(False)
        root.addWidget(self.only_selected_cb)

        ref_lbl = QLabel(easydock_dialog_footer_html())
        ref_lbl.setWordWrap(True)
        ref_lbl.setTextFormat(Qt.RichText)
        ref_lbl.setOpenExternalLinks(True)
        ref_lbl.setStyleSheet("color: palette(mid); font-size: 11px;")
        root.addWidget(ref_lbl)

        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        box.accepted.connect(self._try_accept)
        box.rejected.connect(self.reject)
        root.addWidget(box)

        self.engine_combo.currentIndexChanged.connect(self._sync_engine_fields)
        preferred = default_engine()
        idx = self.engine_combo.findData(preferred)
        if idx >= 0:
            self.engine_combo.setCurrentIndex(idx)
        self._sync_engine_fields()
        make_window_minimizable(self)

    def _sync_engine_fields(self) -> None:
        smina = self.engine_combo.currentData() == ENGINE_SMINA
        self._smina_row.setEnabled(smina)
        self.spin_energy_range.setEnabled(smina)
        self.autobox_cb.setEnabled(smina)
        if not smina:
            self.autobox_cb.setChecked(False)
        self._sync_autobox()

    def _sync_autobox(self) -> None:
        smina = self.engine_combo.currentData() == ENGINE_SMINA
        auto = bool(smina and self.autobox_cb.isChecked())
        self.spin_autobox_add.setEnabled(auto)
        self._autobox_lig_row.setEnabled(auto)
        for sp in (
            self.spin_cx,
            self.spin_cy,
            self.spin_cz,
            self.spin_sx,
            self.spin_sy,
            self.spin_sz,
        ):
            sp.setEnabled(not auto)

    def _browse_receptor(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Receptor PDBQT", self.receptor_edit.text(), "PDBQT (*.pdbqt);;All files (*.*)"
        )
        if path:
            self.receptor_edit.setText(path)

    def _browse_smina(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Smina executable", self.smina_edit.text(), "All files (*.*)"
        )
        if path:
            self.smina_edit.setText(path)

    def _browse_autobox_ligand(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Autobox reference ligand",
            self.edit_autobox_ligand.text() or self.receptor_edit.text(),
            AUTOBOX_LIGAND_FILTER,
        )
        if path:
            self.edit_autobox_ligand.setText(path)

    def _browse_sdf(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save docked poses",
            self.sdf_edit.text() or "docked.sdf",
            "SDF (*.sdf);;All files (*.*)",
        )
        if path:
            self.sdf_edit.setText(path)

    def set_receptor_pdbqt(self, path: str) -> None:
        if path:
            self.receptor_edit.setText(path)

    def only_selected_rows(self) -> bool:
        return selection_scope_checked(self)

    def score_column(self) -> str:
        return (self.score_col_edit.text() or "").strip() or "Dock score"

    def write_poses(self) -> bool:
        return bool(self.write_poses_cb.isChecked())

    def sdf_path(self) -> str | None:
        text = (self.sdf_edit.text() or "").strip()
        return text or None

    def params(self) -> EasyDockParams:
        return EasyDockParams(
            receptor_pdbqt=(self.receptor_edit.text() or "").strip(),
            engine=str(self.engine_combo.currentData() or ENGINE_SMINA),
            center_x=float(self.spin_cx.value()),
            center_y=float(self.spin_cy.value()),
            center_z=float(self.spin_cz.value()),
            size_x=float(self.spin_sx.value()),
            size_y=float(self.spin_sy.value()),
            size_z=float(self.spin_sz.value()),
            exhaustiveness=int(self.spin_exhaust.value()),
            n_poses=int(self.spin_modes.value()),
            energy_range=float(self.spin_energy_range.value()),
            seed=int(self.spin_seed.value()),
            ncpu=int(self.spin_cpu.value()),
            smina_executable=(self.smina_edit.text() or "").strip(),
            autobox=bool(
                self.autobox_cb.isChecked()
                and str(self.engine_combo.currentData() or ENGINE_SMINA) == ENGINE_SMINA
            ),
            autobox_ligand=(self.edit_autobox_ligand.text() or "").strip(),
            autobox_add=float(self.spin_autobox_add.value()),
        )

    def _try_accept(self) -> None:
        rec = (self.receptor_edit.text() or "").strip()
        if not rec or not Path(rec).is_file():
            QMessageBox.warning(self, "Dock", "Choose an existing receptor PDBQT file.")
            return
        engine = str(self.engine_combo.currentData() or ENGINE_SMINA)
        if engine == ENGINE_VINA and not vina_engine_available():
            QMessageBox.warning(
                self,
                "Dock",
                "The Vina Python package is not installed. Use Smina, or pip install vina "
                "(Linux/macOS).",
            )
            return
        if engine == ENGINE_SMINA and not smina_executable_ok(self.smina_edit.text()):
            QMessageBox.warning(
                self,
                "Dock",
                "Smina executable not found. Install smina and set the path, or place it in "
                "molmanager/resources/bin/<platform>/.",
            )
            return
        if engine == ENGINE_SMINA and self.autobox_cb.isChecked():
            ref = (self.edit_autobox_ligand.text() or "").strip()
            if not ref or not Path(ref).is_file() or not is_autobox_ligand_path(ref):
                QMessageBox.warning(
                    self,
                    "Dock",
                    "Choose a reference ligand file for autobox (PDB or PDBQT).",
                )
                return
        self.accept()
