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

"""Modeless UI to run Gnina for receptor–ligand docking (optional flexible side chains)."""

from __future__ import annotations

import os
import re
import shlex
import sys
import tempfile
import time
from collections.abc import Sequence
from pathlib import Path

from PyQt5.QtCore import QProcess, QProcessEnvironment, Qt, QTimer
from PyQt5.QtGui import QCloseEvent, QKeySequence
from PyQt5.QtWidgets import (
    QApplication,
    QCheckBox,
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
    QShortcut,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ...bundled_paths import default_external_executable, gnina_launch_env, resolve_user_executable
from ...confs_codec import is_packed_ensemble_header
from ...dock_io import AUTOBOX_LIGAND_FILTER
from ...pharmacophore import PHARMACOPHORE_FILE_FILTER, load_pharmacophore
from ...gnina_launch import (
    cuda_available,
    gnina_exit_127_message,
    gnina_missing_message,
    gnina_qprocess_spec,
    gnina_uses_wsl,
    resolve_gnina_command,
    write_gnina_config,
)
from ..qt_widget_utils import append_viewer_log, make_window_minimizable

_RECEPTOR_FILE_FILTER = "Receptor (*.pdbqt *.pdb);;PDBQT (*.pdbqt);;PDB (*.pdb);;All files (*.*)"

_LIGAND_FILE_FILTER = (
    "Ligand (*.sdf *.sd *.mol2 *.mol *.pdbqt);;SDF (*.sdf *.sd);;"
    "MOL2 (*.mol2);;Molfile (*.mol);;PDBQT (*.pdbqt);;All files (*.*)"
)
_OUT_FILE_FILTER = "SDF (*.sdf *.sd);;PDBQT (*.pdbqt);;All files (*.*)"
_FLEXRES_TOKEN = re.compile(r"^[A-Za-z0-9]+:-?\d+[A-Za-z]?$")
_LOG_STAMP_RE = re.compile(r"^\[\d{2}:\d{2}:\d{2}\](?:\[system\])?\s*")


class _GninaLogProxy:
    """Forward Gnina log lines to Protein Viewer without a dialog log pane."""

    def __init__(self, dialog: "GninaDockDialog") -> None:
        self._dialog = dialog

    def append(self, text: str) -> None:
        self._dialog._append_log(text)


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


def _ligand_cli_args(ligand: str | Sequence[str]) -> tuple[list[str], str]:
    """Expand one or more ligand paths to repeated ``--ligand`` flags.

    Gnina accepts several ``--ligand`` files in one process. Concatenated Meeko
    PDBQT is invalid as a single file, so split records are passed this way.
    SDF/MOL2 is passed through so Gnina never needs a ligand PDBQT file.
    """
    if isinstance(ligand, (str, Path)):
        paths = [str(ligand).strip()] if str(ligand).strip() else []
    else:
        paths = [str(p).strip() for p in ligand if str(p).strip()]
    if not paths:
        raise ValueError("Choose a ligand file (PDBQT or SDF).")
    args: list[str] = []
    for path in paths:
        args.extend(["--ligand", path])
    return args, paths[0]


def normalize_flexres(text: str) -> str:
    """Comma-separated Gnina ``--flexres`` tokens (``CHAIN:RESNUM``)."""
    parts: list[str] = []
    for raw in (text or "").replace(";", ",").split(","):
        tok = raw.strip().replace(" ", "")
        if not tok:
            continue
        if not _FLEXRES_TOKEN.match(tok):
            raise ValueError(
                f"Invalid flexible residue '{raw.strip()}'. Use CHAIN:RESNUM (e.g. A:123,A:145)."
            )
        parts.append(tok)
    if not parts:
        raise ValueError("Enter flexible residues as CHAIN:RESNUM (e.g. A:123,A:145).")
    return ",".join(parts)


def flex_out_path(out_path: str) -> str:
    """PDB path for Gnina ``--out_flex`` beside the pose output file."""
    p = Path((out_path or "").strip() or "out.sdf")
    stem = p.stem or "out"
    return str(p.with_name(f"{stem}_flex.pdb"))


def ensemble_column_headers(app) -> list[str]:
    """Packed-ensemble table headers (confs / superpose / poses) plus sidecar columns."""
    if app is None:
        return []
    headers = [str(h).strip() for h in (getattr(app, "headers", None) or []) if str(h).strip()]
    names: list[str] = []
    for header in headers:
        if is_packed_ensemble_header(header):
            names.append(header)
    sidecar = getattr(app, "_confs_blocks_sidecar", None)
    if sidecar is None:
        sidecar = {}
    for key in sidecar:
        if not isinstance(key, tuple) or len(key) != 2:
            continue
        col = str(key[1] or "").strip()
        if col and col not in names and col in headers:
            names.append(col)
    return names


def ligand_mol_from_ensemble(mol, oid: int):
    """One 3D ligand per table row. Gnina searches from this start; extra packed confs are not docked."""
    from rdkit import Chem

    if mol is None:
        return None
    clone = Chem.Mol(mol)
    n_conf = int(clone.GetNumConformers())
    if n_conf > 1:
        keep = Chem.Conformer(clone.GetConformer(0))
        clone.RemoveAllConformers()
        clone.AddConformer(keep, assignId=True)
    clone.SetProp("_Name", str(oid))
    from ...services.column_labels import COLUMN_PARENT_OID

    clone.SetProp(COLUMN_PARENT_OID, str(oid))
    return clone


def _write_smina_config(argv: list[str], dest: Path) -> Path:
    """Write a Gnina ``--config`` file (legacy name used by tests)."""
    return write_gnina_config(argv, dest, linux_paths=gnina_uses_wsl())


def _spin_row(pairs: tuple[tuple[str, QWidget], ...]) -> QWidget:
    row = QHBoxLayout()
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(6)
    for label, widget in pairs:
        row.addWidget(QLabel(label))
        row.addWidget(widget, 1)
    wrap = QWidget()
    wrap.setLayout(row)
    return wrap


class GninaDockDialog(QDialog):
    """
    Front-end for the Gnina CLI (Smina/Vina-compatible docking with CNN scoring).

    Expects a receptor PDB or PDBQT, ligands from a file or selected table
    rows (conformations column), and a search box. Optional flexible side chains
    (--flexres / --flexdist); the backbone stays rigid. On Windows Gnina runs
    through Settings → WSL.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._main_window = parent
        self.setWindowTitle("Dock — Gnina")
        self.setModal(False)
        self.setWindowModality(Qt.NonModal)
        self.setMinimumWidth(480)
        self.resize(540, 580)

        self._proc = QProcess(self)
        self._proc.finished.connect(self._on_proc_finished)
        self._proc.readyReadStandardOutput.connect(self._append_stdout)
        self._proc.readyReadStandardError.connect(self._append_stderr)
        self._proc.started.connect(self._on_proc_started)
        self._proc.errorOccurred.connect(self._on_proc_error)
        self._stdout_buf = ""
        self._stderr_buf = ""
        self._resolved_exe = ""
        self._batch_tmp: tempfile.TemporaryDirectory[str] | None = None
        self._batch_ligands: list[Path] = []
        self._batch_cancelled = False
        self._minimize_ins: list[Path] = []
        self._minimize_out: Path | None = None
        self._minimize_n_poses = 0
        self._placement_out = ""
        self._force_no_gpu = False
        self._crystal_ligand_path = ""
        self._prepare_receptor_path = ""
        self._apo_receptor_path = ""
        self._validation_tmp: tempfile.TemporaryDirectory[str] | None = None
        self._validation_phase = False
        self._validation_out = ""
        self._crystal_ref_mol = None
        self._crystal_rmsd: float | None = None
        self._pending_user_ligand: str | list[str] | None = None
        self._pending_user_out = ""
        self._stamp_crystal_on_poses = False
        self._validation_ligand_path = ""
        self._validation_pose_mols: list = []

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 6)
        root.setSpacing(6)

        io_gb = QGroupBox("Input / output")
        io_form = QFormLayout(io_gb)
        io_form.setContentsMargins(8, 6, 8, 6)
        io_form.setSpacing(4)
        self.edit_exe = QLineEdit(default_external_executable("gnina"))
        self.edit_exe.setToolTip(
            "Gnina command. On Windows this is the Linux binary on the WSL PATH (gnina). "
            "On Linux, uses molmanager/resources/bin/<platform>/gnina when bundled, otherwise PATH."
        )
        io_form.addRow("Gnina:", _browse_path_row(self.edit_exe, self._browse_exe))

        self.edit_receptor = QLineEdit()
        self.edit_receptor.setPlaceholderText("receptor.pdbqt")
        self.edit_receptor.setToolTip(
            "Rigid receptor in PDB or PDBQT format. If this file still contains a "
            "ligand, it is stripped to apo for docking. Internal validation (on by "
            "default) redocks that crystal pose and reports RMSD."
        )
        io_form.addRow("Receptor:", _browse_path_row(self.edit_receptor, self._browse_receptor))

        self.combo_ligand_source = QComboBox()
        self.combo_ligand_source.addItem("File", "file")
        self.combo_ligand_source.addItem("Selected rows", "rows")
        self.combo_ligand_source.setToolTip(
            "Dock a ligand file, or every selected table row using a conformations column."
        )
        io_form.addRow("Ligand:", self.combo_ligand_source)

        self.edit_ligand = QLineEdit()
        self.edit_ligand.setPlaceholderText("ligand.sdf")
        self.edit_ligand.setToolTip(
            "Ligand SDF (also MOL/MOL2). PDBQT is accepted but converted to SDF first so "
            "aromatic and double bonds are not guessed from PDBQT."
        )
        self._lig_stack = QStackedWidget()
        self._lig_stack.addWidget(_browse_path_row(self.edit_ligand, self._browse_ligand))
        confs_wrap = QWidget()
        confs_row = QHBoxLayout(confs_wrap)
        confs_row.setContentsMargins(0, 0, 0, 0)
        confs_row.setSpacing(6)
        confs_row.addWidget(QLabel("Conformations:"))
        self.combo_confs = QComboBox()
        self.combo_confs.setToolTip(
            "Packed ensemble column (confs, superpose, …) or Structure for selected rows."
        )
        confs_row.addWidget(self.combo_confs, 1)
        self._lig_stack.addWidget(confs_wrap)
        io_form.addRow("", self._lig_stack)
        self.combo_ligand_source.currentIndexChanged.connect(self._sync_ligand_source)
        self._refresh_confs_columns()
        self._sync_ligand_source()

        self.edit_out = QLineEdit()
        self.edit_out.setPlaceholderText("out.sdf")
        self.edit_out.setToolTip(
            "Gnina writes docked poses here. SDF keeps bond orders; PDBQT does not."
        )
        self.save_sdf_cb = QCheckBox("Save as SDF")
        self.save_sdf_cb.setChecked(True)
        self.save_sdf_cb.setToolTip(
            "Write poses as SDF (Gnina --out). Uncheck to write PDBQT instead. "
            "PDBQT has no bond orders, so aromatics become singles."
        )
        self.save_sdf_cb.toggled.connect(self._sync_out_suffix)
        out_row = QHBoxLayout()
        out_row.setContentsMargins(0, 0, 0, 0)
        out_row.setSpacing(4)
        out_row.addWidget(self.edit_out, 1)
        btn_out = QPushButton("Browse…")
        btn_out.setFixedWidth(76)
        btn_out.clicked.connect(self._browse_out)
        out_row.addWidget(btn_out)
        out_row.addWidget(self.save_sdf_cb)
        out_wrap = QWidget()
        out_wrap.setLayout(out_row)
        io_form.addRow("Output:", out_wrap)

        self.edit_pharmacophore = QLineEdit()
        self.edit_pharmacophore.setPlaceholderText("pharmacophore.json (optional)")
        self.edit_pharmacophore.setToolTip(
            "MolManager pharmacophore JSON from Protein Viewer → Tools → Pharmacophore. "
            "Docking itself is unchanged (CNN/Vina). After poses are written, MolManager "
            "keeps only those whose RDKit feature sites sit in the query spheres "
            "(protein frame). Exclusion spheres reject poses with a heavy atom inside."
        )
        self.spin_pharma_slack = QDoubleSpinBox()
        self.spin_pharma_slack.setRange(0.0, 5.0)
        self.spin_pharma_slack.setDecimals(2)
        self.spin_pharma_slack.setSingleStep(0.1)
        self.spin_pharma_slack.setValue(0.50)
        self.spin_pharma_slack.setSuffix(" Å")
        self.spin_pharma_slack.setToolTip(
            "Extra tolerance (Å) added to each feature radius when matching docked poses. "
            "0 keeps the sphere as drawn."
        )
        ph_row = QHBoxLayout()
        ph_row.setContentsMargins(0, 0, 0, 0)
        ph_row.setSpacing(4)
        ph_row.addWidget(self.edit_pharmacophore, 1)
        btn_pharma = QPushButton("Browse…")
        btn_pharma.setFixedWidth(76)
        btn_pharma.clicked.connect(self._browse_pharmacophore)
        ph_row.addWidget(btn_pharma)
        ph_row.addWidget(QLabel("Slack:"))
        ph_row.addWidget(self.spin_pharma_slack)
        ph_wrap = QWidget()
        ph_wrap.setLayout(ph_row)
        io_form.addRow("Pharmacophore:", ph_wrap)
        root.addWidget(io_gb)

        box_gb = QGroupBox("Search box (Å)")
        box_form = QFormLayout(box_gb)
        box_form.setContentsMargins(8, 6, 8, 6)
        box_form.setSpacing(4)
        auto_row = QHBoxLayout()
        auto_row.setContentsMargins(0, 0, 0, 0)
        self.autobox_cb = QCheckBox("Autobox")
        self.autobox_cb.setToolTip(
            "Let Gnina set the search box from a ligand (--autobox_ligand). "
            "Browse for a reference ligand, or leave empty to use the docking ligand. "
            "Center and size are ignored."
        )
        auto_row.addWidget(self.autobox_cb)
        self.edit_autobox_ligand = QLineEdit()
        self.edit_autobox_ligand.setPlaceholderText("ligand.pdb or ligand.pdbqt (optional)")
        self.edit_autobox_ligand.setToolTip(
            "Ligand file whose coordinates define the autobox (PDB or PDBQT). "
            "Leave empty to use the docking ligand."
        )
        self.btn_autobox_ligand = QPushButton("Browse…")
        self.btn_autobox_ligand.setFixedWidth(76)
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
        auto_row.addWidget(QLabel("Pad:"))
        self.spin_autobox_add = QDoubleSpinBox()
        self.spin_autobox_add.setRange(0.0, 50.0)
        self.spin_autobox_add.setDecimals(2)
        self.spin_autobox_add.setSingleStep(0.5)
        self.spin_autobox_add.setValue(4.0)
        self.spin_autobox_add.setSuffix(" Å")
        self.spin_autobox_add.setToolTip(
            "Buffer added around the ligand bounding box (--autobox_add). Gnina default is 4 Å."
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
        self.spin_cx.setToolTip("Box center X (same coordinates as the receptor).")
        self.spin_cy.setToolTip("Box center Y.")
        self.spin_cz.setToolTip("Box center Z.")
        box_form.addRow(
            "Center:",
            _spin_row((("X", self.spin_cx), ("Y", self.spin_cy), ("Z", self.spin_cz))),
        )

        self.spin_sx = QDoubleSpinBox()
        self.spin_sy = QDoubleSpinBox()
        self.spin_sz = QDoubleSpinBox()
        for sp in (self.spin_sx, self.spin_sy, self.spin_sz):
            sp.setRange(1.0, 500.0)
            sp.setDecimals(2)
            sp.setSingleStep(1.0)
            sp.setValue(20.0)
        self.spin_sx.setToolTip("Box side length along X (default 20 Å).")
        box_form.addRow(
            "Size:",
            _spin_row((("X", self.spin_sx), ("Y", self.spin_sy), ("Z", self.spin_sz))),
        )
        self.autobox_cb.toggled.connect(self._sync_autobox)
        self._sync_autobox()
        root.addWidget(box_gb)

        flex_gb = QGroupBox("Flexible side chains")
        flex_form = QFormLayout(flex_gb)
        flex_form.setContentsMargins(8, 6, 8, 6)
        flex_form.setSpacing(4)
        self.combo_flex_mode = QComboBox()
        self.combo_flex_mode.addItem("Off (rigid receptor)", "off")
        self.combo_flex_mode.addItem("Distance from ligand", "dist")
        self.combo_flex_mode.addItem("Named residues", "res")
        self.combo_flex_mode.setToolTip(
            "Sample pocket side-chain rotamers during docking. The backbone stays rigid. "
            "Slower than a rigid receptor. Distance mode selects residues near a reference "
            "ligand (--flexdist). Named residues use CHAIN:RESNUM (--flexres)."
        )
        flex_form.addRow("Mode:", self.combo_flex_mode)

        self.edit_flexdist_ligand = QLineEdit()
        self.edit_flexdist_ligand.setPlaceholderText("crystal ligand (optional)")
        self.edit_flexdist_ligand.setToolTip(
            "Reference ligand for --flexdist_ligand. Empty uses the Autobox ligand, "
            "then the Prepare crystal ligand, then the docking ligand."
        )
        self.btn_flexdist_ligand = QPushButton("Browse…")
        self.btn_flexdist_ligand.setFixedWidth(76)
        self.btn_flexdist_ligand.setToolTip("Choose a reference ligand for flexible residues.")
        self.btn_flexdist_ligand.clicked.connect(self._browse_flexdist_ligand)
        flex_lig_row = QHBoxLayout()
        flex_lig_row.setContentsMargins(0, 0, 0, 0)
        flex_lig_row.setSpacing(4)
        flex_lig_row.addWidget(self.edit_flexdist_ligand, 1)
        flex_lig_row.addWidget(self.btn_flexdist_ligand)
        flex_lig_w = QWidget()
        flex_lig_w.setLayout(flex_lig_row)
        self.spin_flexdist = QDoubleSpinBox()
        self.spin_flexdist.setRange(0.5, 20.0)
        self.spin_flexdist.setDecimals(2)
        self.spin_flexdist.setSingleStep(0.5)
        self.spin_flexdist.setValue(3.5)
        self.spin_flexdist.setSuffix(" Å")
        self.spin_flexdist.setToolTip(
            "Any residue with a side-chain atom within this distance of the reference "
            "ligand is flexible (--flexdist). Gnina paper default is 3.5 Å."
        )
        dist_row = QHBoxLayout()
        dist_row.setContentsMargins(0, 0, 0, 0)
        dist_row.setSpacing(6)
        dist_row.addWidget(flex_lig_w, 1)
        dist_row.addWidget(QLabel("Dist:"))
        dist_row.addWidget(self.spin_flexdist)
        dist_w = QWidget()
        dist_w.setLayout(dist_row)
        self.edit_flexres = QLineEdit()
        self.edit_flexres.setPlaceholderText("A:123,A:145")
        self.edit_flexres.setToolTip(
            "Comma-separated residues to flex (--flexres), as CHAIN:RESNUM. "
            "Optional insertion code: A:123A."
        )
        self._flex_stack = QStackedWidget()
        self._flex_stack.addWidget(QWidget())
        self._flex_stack.addWidget(dist_w)
        res_w = QWidget()
        res_ly = QHBoxLayout(res_w)
        res_ly.setContentsMargins(0, 0, 0, 0)
        res_ly.addWidget(self.edit_flexres, 1)
        self._flex_stack.addWidget(res_w)
        flex_form.addRow("", self._flex_stack)

        self.spin_flex_max = QSpinBox()
        self.spin_flex_max.setRange(0, 64)
        self.spin_flex_max.setValue(0)
        self.spin_flex_max.setSpecialValueText("all")
        self.spin_flex_max.setToolTip(
            "Keep at most this many closest residues (--flex_max). 0 / all keeps every "
            "residue selected by distance. Ignored for named residues."
        )
        self.chk_full_flex = QCheckBox("Write full receptor")
        self.chk_full_flex.setToolTip(
            "Gnina --full_flex_output: --out_flex is the whole structure, not only "
            "the flexible residues. Off writes the side chains for each pose."
        )
        flex_extra = QHBoxLayout()
        flex_extra.setContentsMargins(0, 0, 0, 0)
        flex_extra.setSpacing(12)
        flex_extra.addWidget(QLabel("Max:"))
        flex_extra.addWidget(self.spin_flex_max)
        flex_extra.addWidget(self.chk_full_flex)
        flex_extra.addStretch()
        self._flex_extra_row = QWidget()
        self._flex_extra_row.setLayout(flex_extra)
        flex_form.addRow(self._flex_extra_row)
        self.combo_flex_mode.currentIndexChanged.connect(self._sync_flex_mode)
        self._sync_flex_mode()
        root.addWidget(flex_gb)

        opt_gb = QGroupBox("Search")
        opt_form = QFormLayout(opt_gb)
        opt_form.setContentsMargins(8, 6, 8, 6)
        opt_form.setSpacing(4)
        self.spin_exhaust = QSpinBox()
        self.spin_exhaust.setRange(1, 32)
        self.spin_exhaust.setValue(8)
        self.spin_exhaust.setToolTip("Exhaustiveness of the global search (typical 8).")
        self.spin_modes = QSpinBox()
        self.spin_modes.setRange(1, 100)
        self.spin_modes.setValue(9)
        self.spin_modes.setToolTip("Maximum number of binding modes to generate.")
        self.spin_cpu = QSpinBox()
        self.spin_cpu.setRange(0, 128)
        self.spin_cpu.setValue(0)
        self.spin_cpu.setSpecialValueText("auto")
        self.spin_cpu.setToolTip("CPU threads for Gnina; 0 / auto omits --cpu (tool default).")
        opt_form.addRow(
            "Search:",
            _spin_row(
                (
                    ("Exh.", self.spin_exhaust),
                    ("Modes", self.spin_modes),
                    ("CPU", self.spin_cpu),
                )
            ),
        )
        self.validate_crystal_cb = QCheckBox("Internal validation")
        self.validate_crystal_cb.setChecked(True)
        self.validate_crystal_cb.setToolTip(
            "When a crystal ligand is available (in the receptor file, or from Dock File / "
            "Fast Prepare), redock it with the same box and search settings and report "
            "heavy-atom RMSD of the top pose versus the crystal coordinates. Uncheck to skip."
        )
        self.minimize_poses_cb = QCheckBox("Minimize Docked Poses")
        self.minimize_poses_cb.setChecked(False)
        self.minimize_poses_cb.setToolTip(
            "After docking, energy-minimize all poses in the receptor in one Gnina process "
            "(--minimize). Results include both the placement pose and the minimized pose."
        )
        chk_row = QHBoxLayout()
        chk_row.setContentsMargins(0, 0, 0, 0)
        chk_row.setSpacing(12)
        chk_row.addWidget(self.validate_crystal_cb)
        chk_row.addWidget(self.minimize_poses_cb)
        chk_row.addStretch()
        chk_wrap = QWidget()
        chk_wrap.setLayout(chk_row)
        opt_form.addRow(chk_wrap)

        self.edit_wd = QLineEdit()
        self.edit_wd.setPlaceholderText("Optional working directory")
        self.edit_wd.setToolTip(
            "If set, Gnina starts with this as the current directory (relative paths resolve here)."
        )
        opt_form.addRow("Work dir:", self.edit_wd)

        self.edit_extra = QLineEdit()
        self.edit_extra.setPlaceholderText("Optional extra args (e.g. --seed 42)")
        self.edit_extra.setToolTip(
            "Additional Gnina flags. Flexible side chains have their own section above."
        )
        opt_form.addRow("Extra:", self.edit_extra)
        root.addWidget(opt_gb)

        cnn_gb = QGroupBox("CNN scoring")
        cnn_form = QFormLayout(cnn_gb)
        cnn_form.setContentsMargins(8, 6, 8, 6)
        cnn_form.setSpacing(4)
        self.combo_cnn_scoring = QComboBox()
        self.combo_cnn_scoring.addItem("Rescore", "rescore")
        self.combo_cnn_scoring.addItem("None (empirical)", "none")
        self.combo_cnn_scoring.addItem("Refinement", "refinement")
        self.combo_cnn_scoring.setToolTip(
            "When CNN scoring is applied. Rescore reranks final poses (Gnina default). "
            "None uses the empirical scoring function only. Refinement is slower."
        )
        cnn_form.addRow("CNN:", self.combo_cnn_scoring)
        self.combo_cnn_model = QComboBox()
        self.combo_cnn_model.addItem("Default ensemble", "")
        self.combo_cnn_model.addItem("dense", "dense")
        self.combo_cnn_model.addItem("fast", "fast")
        self.combo_cnn_model.addItem("crossdock_default2018", "crossdock_default2018")
        self.combo_cnn_model.setToolTip(
            "Built-in CNN. Default omits --cnn so Gnina uses its current ensemble."
        )
        cnn_form.addRow("Model:", self.combo_cnn_model)
        self.combo_pose_sort = QComboBox()
        self.combo_pose_sort.addItem("CNNscore", "CNNscore")
        self.combo_pose_sort.addItem("CNNaffinity", "CNNaffinity")
        self.combo_pose_sort.addItem("Energy", "Energy")
        self.combo_pose_sort.setToolTip("How Gnina sorts output poses (--pose_sort_order).")
        cnn_form.addRow("Sort poses:", self.combo_pose_sort)
        self.combo_emp_scoring = QComboBox()
        self.combo_emp_scoring.addItem("vina", "vina")
        self.combo_emp_scoring.addItem("vinardo", "vinardo")
        self.combo_emp_scoring.setToolTip(
            "Empirical scoring function used when CNN scoring is None (--scoring)."
        )
        cnn_form.addRow("Empirical:", self.combo_emp_scoring)
        self.gpu_cb = QCheckBox("Use GPU")
        self.gpu_cb.setChecked(sys.platform != "darwin")
        self.gpu_cb.setToolTip(
            "Use CUDA when available. Uncheck to pass --no_gpu. On Windows CUDA is probed "
            "inside WSL; if nvidia-smi fails, --no_gpu is added automatically."
        )
        cnn_form.addRow(self.gpu_cb)
        self.combo_cnn_scoring.currentIndexChanged.connect(self._sync_cnn_options)
        self._sync_cnn_options()
        root.addWidget(cnn_gb)

        self.log = _GninaLogProxy(self)

        btn_row = QHBoxLayout()
        self.btn_run = QPushButton("Run Gnina")
        self.btn_run.clicked.connect(self._run_gnina)
        btn_row.addWidget(self.btn_run)
        self.btn_stop = QPushButton("Stop")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self._stop_proc)
        btn_row.addWidget(self.btn_stop)
        btn_row.addStretch()
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.close)
        btn_row.addWidget(close_btn)
        root.addLayout(btn_row)

        QShortcut(QKeySequence("Ctrl+Return"), self, activated=self._run_gnina)
        make_window_minimizable(self)

    def is_gnina_running(self) -> bool:
        return self._proc.state() != QProcess.NotRunning

    is_smina_running = is_gnina_running

    def cancel_gnina(self) -> bool:
        if self._proc.state() == QProcess.NotRunning:
            return False
        self._stop_proc()
        return True

    cancel_smina = cancel_gnina

    def _notify_activity(self) -> None:
        w = self._main_window
        hub = getattr(w, "background_activity", None) if w is not None else None
        if hub is not None:
            hub.notify_changed()

    def _protein_viewer(self):
        w = self._main_window
        finder = getattr(w, "_live_protein_viewer", None) if w is not None else None
        if callable(finder):
            dlg = finder()
            if dlg is not None:
                return dlg
        parent = self.parent()
        if hasattr(parent, "append_log"):
            return parent
        return None

    def _append_log(self, text: str) -> None:
        t = (text or "").rstrip()
        if not t:
            return
        t = _LOG_STAMP_RE.sub("", t, count=1)
        if not t:
            return
        append_viewer_log(self._protein_viewer(), t)

    def _dismiss_for_run(self) -> None:
        """Hide the setup dialog so CUDA/prep work cannot freeze it."""
        if self.isVisible():
            self.hide()
            QApplication.processEvents()

    def _reveal_dock_dialog(self) -> None:
        self.show()
        self.raise_()
        self.activateWindow()

    def _browse_exe(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Gnina executable", self.edit_exe.text(), "All files (*.*)"
        )
        if path:
            self.edit_exe.setText(path)

    def _browse_receptor(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Receptor PDB / PDBQT", "", _RECEPTOR_FILE_FILTER
        )
        if path:
            self.edit_receptor.setText(path)
            prep = (self._prepare_receptor_path or "").strip()
            if prep and not self._same_input_path(path, prep):
                self._crystal_ligand_path = ""
                self._prepare_receptor_path = ""

    def _browse_ligand(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Ligand", "", _LIGAND_FILE_FILTER)
        if path:
            self.edit_ligand.setText(path)

    def _browse_pharmacophore(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Pharmacophore",
            self.edit_pharmacophore.text(),
            PHARMACOPHORE_FILE_FILTER,
        )
        if path:
            self.edit_pharmacophore.setText(path)

    def set_pharmacophore_path(self, path: str) -> None:
        """Fill the pharmacophore field (Protein Viewer → Send to Gnina)."""
        text = (path or "").strip()
        if text:
            self.edit_pharmacophore.setText(text)

    def _ligand_source_key(self) -> str:
        return str(self.combo_ligand_source.currentData() or "file")

    def _sync_ligand_source(self) -> None:
        rows = self._ligand_source_key() == "rows"
        self._lig_stack.setCurrentIndex(1 if rows else 0)
        if rows:
            self._refresh_confs_columns()

    def _refresh_confs_columns(self) -> None:
        current = (self.combo_confs.currentText() or "").strip()
        self.combo_confs.blockSignals(True)
        self.combo_confs.clear()
        for name in ensemble_column_headers(self._main_window):
            self.combo_confs.addItem(name)
        self.combo_confs.addItem("Structure")
        idx = self.combo_confs.findText(current)
        if idx < 0:
            idx = self.combo_confs.findText("confs")
        if idx >= 0:
            self.combo_confs.setCurrentIndex(idx)
        self.combo_confs.blockSignals(False)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if self._ligand_source_key() == "rows":
            self._refresh_confs_columns()

    def _browse_autobox_ligand(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Autobox reference ligand",
            self.edit_autobox_ligand.text() or self.edit_ligand.text(),
            AUTOBOX_LIGAND_FILTER,
        )
        if path:
            self.edit_autobox_ligand.setText(path)

    def _sync_autobox(self) -> None:
        auto = bool(self.autobox_cb.isChecked())
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

    def _browse_flexdist_ligand(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Flexible-residue reference ligand",
            self.edit_flexdist_ligand.text()
            or self.edit_autobox_ligand.text()
            or self.edit_ligand.text(),
            AUTOBOX_LIGAND_FILTER,
        )
        if path:
            self.edit_flexdist_ligand.setText(path)

    def _flex_mode(self) -> str:
        return str(self.combo_flex_mode.currentData() or "off")

    def _sync_flex_mode(self) -> None:
        mode = self._flex_mode()
        on = mode != "off"
        page = {"off": 0, "dist": 1, "res": 2}.get(mode, 0)
        self._flex_stack.setCurrentIndex(page)
        self._flex_stack.setVisible(on)
        self._flex_extra_row.setVisible(on)
        self.spin_flex_max.setEnabled(mode == "dist")
        self.chk_full_flex.setEnabled(on)

    def _flexdist_ligand_path(self, dock_ligand: str) -> str:
        explicit = (self.edit_flexdist_ligand.text() or "").strip()
        if explicit:
            return explicit
        auto = (self.edit_autobox_ligand.text() or "").strip()
        if auto:
            return auto
        crystal = (self._crystal_ligand_path or "").strip()
        if crystal:
            return crystal
        return (dock_ligand or "").strip()

    def _flex_argv(self, *, dock_ligand: str, out_path: str) -> list[str]:
        """Gnina flexible-side-chain flags, or empty when the receptor is rigid."""
        mode = self._flex_mode()
        if mode == "off":
            return []
        argv: list[str] = []
        if mode == "dist":
            lig = self._flexdist_ligand_path(dock_ligand)
            if not lig:
                raise ValueError(
                    "Choose a reference ligand for flexible side chains "
                    "(or set Autobox / a crystal ligand from Prepare)."
                )
            argv.extend(
                [
                    "--flexdist_ligand",
                    lig,
                    "--flexdist",
                    f"{self.spin_flexdist.value():.2f}",
                ]
            )
            nmax = int(self.spin_flex_max.value())
            if nmax > 0:
                argv.extend(["--flex_max", str(nmax)])
        elif mode == "res":
            argv.extend(["--flexres", normalize_flexres(self.edit_flexres.text())])
        else:
            return []
        argv.extend(["--out_flex", flex_out_path(out_path)])
        if self.chk_full_flex.isChecked():
            argv.append("--full_flex_output")
        return argv

    def _sync_cnn_options(self) -> None:
        cnn_none = self.combo_cnn_scoring.currentData() == "none"
        self.combo_emp_scoring.setEnabled(cnn_none)
        self.combo_cnn_model.setEnabled(not cnn_none)
        self.combo_pose_sort.setEnabled(not cnn_none)

    def apply_prepare_result(self, result) -> None:
        """Fill receptor and numeric box from Protein Viewer Prepare; leave ligand empty.

        Crystal ligand SDF/PDB from Dock File / Fast Prepare is kept for internal
        validation (redock + RMSD), not as the docking ligand field.
        """
        from ...dock_validation import existing_crystal_ligand_path

        receptor = ""
        getter = getattr(result, "receptor_pdbqt_path", None)
        if callable(getter):
            receptor = str(getter() or "").strip()
        if not receptor:
            receptor = str(getattr(result, "receptor_pdbqt", "") or "").strip()
        if Path(receptor).suffix.lower() != ".pdbqt":
            output = str(getattr(result, "output_path", "") or "").strip()
            receptor = (
                output if Path(output).suffix.lower() == ".pdbqt" and Path(output).is_file() else ""
            )
        elif receptor and not Path(receptor).is_file():
            receptor = ""
        autobox = str(getattr(result, "ligand_pdb", "") or "").strip()
        sdf = existing_crystal_ligand_path(getattr(result, "ligand_sdf", ""))
        pdb = existing_crystal_ligand_path(getattr(result, "ligand_pdb", ""))
        self._crystal_ligand_path = sdf or pdb
        self._prepare_receptor_path = receptor
        self.combo_ligand_source.setCurrentIndex(self.combo_ligand_source.findData("file"))
        self.edit_ligand.clear()
        if receptor:
            self.edit_receptor.setText(receptor)
            if not (self.edit_out.text() or "").strip():
                rec_path = Path(receptor)
                self.edit_out.setText(str(rec_path.with_name(f"{rec_path.stem}_docked.sdf")))
        if autobox:
            self.edit_autobox_ligand.setText(autobox)
            self.edit_flexdist_ligand.setText(autobox)
        box = getattr(result, "box", None)
        if box is not None:
            self.autobox_cb.setChecked(False)
            self.spin_cx.setValue(float(box.center_x))
            self.spin_cy.setValue(float(box.center_y))
            self.spin_cz.setValue(float(box.center_z))
            self.spin_sx.setValue(float(box.size_x))
            self.spin_sy.setValue(float(box.size_y))
            self.spin_sz.setValue(float(box.size_z))
        self._sync_autobox()

    def _autobox_ligand_path(self, dock_ligand: str) -> str:
        text = (self.edit_autobox_ligand.text() or "").strip()
        return text or dock_ligand

    def _browse_out(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Docked output", "", _OUT_FILE_FILTER)
        if path:
            self.edit_out.setText(path)

    def _sync_out_suffix(self, checked: bool) -> None:
        text = (self.edit_out.text() or "").strip()
        if not text:
            self.edit_out.setPlaceholderText("out.sdf" if checked else "out.pdbqt")
            return
        path = Path(text)
        suf = path.suffix.lower()
        if checked and suf == ".pdbqt":
            self.edit_out.setText(str(path.with_suffix(".sdf")))
        elif not checked and suf in {".sdf", ".sd"}:
            self.edit_out.setText(str(path.with_suffix(".pdbqt")))

    def _effective_out_path(self, out: str | None = None) -> str:
        from ...dock_io import sdf_path_for_pdbqt

        text = (out if out is not None else self.edit_out.text() or "").strip()
        if not text:
            return text
        if self.save_sdf_cb.isChecked():
            return str(sdf_path_for_pdbqt(text))
        return text

    def _gnina_executable(self) -> str:
        return (self.edit_exe.text() or "").strip() or default_external_executable("gnina")

    def _smina_executable(self) -> str:
        return self._gnina_executable()

    def _set_running_ui(self, running: bool) -> None:
        self.btn_run.setEnabled(not running)
        self.btn_stop.setEnabled(running)

    def _ensure_batch_tmp(self, prefix: str) -> Path:
        if self._batch_tmp is None:
            self._batch_tmp = tempfile.TemporaryDirectory(prefix=prefix)
        return Path(self._batch_tmp.name)

    def _launch_argv(self, argv: list[str]) -> list[str]:
        """Use ``--config`` when several ligands would bloat the command line."""
        if argv.count("--ligand") <= 1:
            return argv
        cfg = self._ensure_batch_tmp("gnina_cfg_") / "gnina.conf"
        write_gnina_config(argv, cfg, linux_paths=gnina_uses_wsl())
        return ["--config", str(cfg)]

    def _receptor_for_gnina(self) -> str:
        return (self._apo_receptor_path or self.edit_receptor.text() or "").strip()

    def _build_argv(
        self,
        *,
        ligand: str | Sequence[str] | None = None,
        out: str | None = None,
        receptor: str | None = None,
    ) -> list[str]:
        rec = (receptor if receptor is not None else self._receptor_for_gnina()).strip()
        lig_src: str | Sequence[str] = (
            ligand if ligand is not None else (self.edit_ligand.text() or "")
        )
        lig_args, first_lig = _ligand_cli_args(lig_src)
        out_path = (out if out is not None else self._effective_out_path()).strip()
        if not rec:
            raise ValueError("Choose a receptor PDB or PDBQT file.")
        if not out_path:
            raise ValueError("Set an output path.")

        argv = ["--receptor", rec, *lig_args, "--out", out_path]
        if self.autobox_cb.isChecked():
            box_lig = self._autobox_ligand_path(first_lig)
            if not box_lig:
                raise ValueError("Choose a ligand file, or a box ligand, for autobox.")
            argv.extend(
                [
                    "--autobox_ligand",
                    box_lig,
                    "--autobox_add",
                    f"{self.spin_autobox_add.value():.2f}",
                ]
            )
        else:
            argv.extend(
                [
                    "--center_x",
                    f"{self.spin_cx.value():.3f}",
                    "--center_y",
                    f"{self.spin_cy.value():.3f}",
                    "--center_z",
                    f"{self.spin_cz.value():.3f}",
                    "--size_x",
                    f"{self.spin_sx.value():.2f}",
                    "--size_y",
                    f"{self.spin_sy.value():.2f}",
                    "--size_z",
                    f"{self.spin_sz.value():.2f}",
                ]
            )
        argv.extend(
            [
                "--exhaustiveness",
                str(int(self.spin_exhaust.value())),
                "--num_modes",
                str(int(self.spin_modes.value())),
            ]
        )
        argv.extend(self._cnn_argv())
        cpu = int(self.spin_cpu.value())
        if cpu > 0:
            argv.extend(["--cpu", str(cpu)])
        argv.extend(self._flex_argv(dock_ligand=first_lig, out_path=out_path))
        extra = (self.edit_extra.text() or "").strip()
        if extra:
            argv.extend(shlex.split(extra))
        return argv

    def _require_dock_pharmacophore(self) -> None:
        """Raise if the Pharmacophore field is set but the JSON cannot be used."""
        path = (self.edit_pharmacophore.text() or "").strip()
        if not path:
            return
        dest = Path(path)
        if not dest.is_file():
            raise ValueError(f"Pharmacophore file not found: {path}")
        pharma = load_pharmacophore(dest)
        if not pharma.enabled_features():
            raise ValueError("Pharmacophore file has no enabled features.")

    def _apply_pharmacophore_filter(self, mols: list, *, log: bool = True) -> list:
        """Keep docked poses that occupy the query spheres in the protein frame."""
        path = (self.edit_pharmacophore.text() or "").strip()
        if not path or not mols:
            return list(mols)
        try:
            pharma = load_pharmacophore(path)
        except Exception as exc:
            if log:
                stamp = time.strftime("%H:%M:%S")
                self.log.append(f"[{stamp}][system] Pharmacophore filter skipped: {exc}")
            return list(mols)
        if not pharma.enabled_features():
            return list(mols)
        from ...pharmacophore_screen import DEFAULT_DOCK_SLACK_ANGSTROM, filter_docked_poses

        slack = (
            float(self.spin_pharma_slack.value())
            if getattr(self, "spin_pharma_slack", None) is not None
            else DEFAULT_DOCK_SLACK_ANGSTROM
        )
        kept, dropped = filter_docked_poses(mols, pharma, slack=slack)
        if log:
            stamp = time.strftime("%H:%M:%S")
            n_all = len(kept) + len(dropped)
            if kept:
                self.log.append(
                    f"[{stamp}][system] Pharmacophore: kept {len(kept)} of {n_all} pose(s) "
                    f"(slack {slack:.2f} Å)."
                )
            else:
                self.log.append(
                    f"[{stamp}][system] Pharmacophore: 0 of {n_all} pose(s) matched "
                    f"(slack {slack:.2f} Å); keeping all for inspection."
                )
        return kept if kept else list(mols)

    def _cnn_argv(self, *, no_gpu: bool | None = None) -> list[str]:
        scoring = str(self.combo_cnn_scoring.currentData() or "rescore")
        argv = ["--cnn_scoring", scoring]
        if scoring == "none":
            emp = str(self.combo_emp_scoring.currentData() or "vina")
            argv.extend(["--scoring", emp])
        else:
            argv.extend(
                ["--pose_sort_order", str(self.combo_pose_sort.currentData() or "CNNscore")]
            )
            model = str(self.combo_cnn_model.currentData() or "")
            if model:
                argv.extend(["--cnn", model])
        force_cpu = (
            bool(no_gpu)
            if no_gpu is not None
            else (
                (not self.gpu_cb.isChecked())
                or sys.platform == "darwin"
                or bool(getattr(self, "_force_no_gpu", False))
            )
        )
        if force_cpu:
            argv.append("--no_gpu")
        return argv

    def _build_minimize_argv(self, ligand: str | Sequence[str], out: str) -> list[str]:
        rec = self._receptor_for_gnina()
        if not rec:
            raise ValueError("Choose a receptor PDB or PDBQT file.")
        lig_args, _first = _ligand_cli_args(ligand)
        argv = ["--receptor", rec, *lig_args, "--out", out, "--minimize"]
        argv.extend(self._cnn_argv())
        cpu = int(self.spin_cpu.value())
        if cpu > 0:
            argv.extend(["--cpu", str(cpu)])
        return argv

    def _stop_proc(self) -> None:
        self._batch_cancelled = True
        try:
            self._proc.terminate()
        except Exception:
            pass
        QTimer.singleShot(2500, self._kill_if_running)
        stamp = time.strftime("%H:%M:%S")
        self.log.append(f"[{stamp}][system] Stopping…")

    def _kill_if_running(self) -> None:
        if self._proc.state() != QProcess.NotRunning:
            try:
                self._proc.kill()
            except Exception:
                pass

    def _on_proc_started(self) -> None:
        self._set_running_ui(True)
        if not self._minimize_ins:
            self._stdout_buf = ""
            self._stderr_buf = ""
        pid = self._proc.processId()
        stamp = time.strftime("%H:%M:%S")
        n_min = self._minimize_n_poses or len(self._minimize_ins)
        n_lig = len(self._batch_ligands)
        if self._validation_phase:
            self.log.append(
                f"[{stamp}][system] Gnina started (PID {pid}) internal validation (crystal redock)."
            )
        elif n_min:
            self.log.append(
                f"[{stamp}][system] Gnina started (PID {pid}) minimizing {n_min} pose(s)."
            )
        elif n_lig > 1:
            self.log.append(f"[{stamp}][system] Gnina started (PID {pid}) docking {n_lig} ligands.")
        else:
            self.log.append(f"[{stamp}][system] Gnina started (PID {pid}).")
        if (not self._minimize_ins) and self._flex_mode() != "off":
            self.log.append(
                f"[{stamp}][system] Flexible side chains on (backbone rigid). "
                f"Writing {flex_out_path(self._effective_out_path())}."
            )
        self._notify_activity()

    def _on_proc_error(self, error: QProcess.ProcessError) -> None:
        if error != QProcess.FailedToStart:
            return
        detail = (self._proc.errorString() or "").strip() or "Gnina failed to start."
        stamp = time.strftime("%H:%M:%S")
        self.log.append(f"[{stamp}][system] {detail}")
        self._reveal_dock_dialog()
        if self._minimize_ins:
            self._finish_minimize_keep_placement()
        else:
            self._validation_phase = False
            self._pending_user_ligand = None
            self._clear_batch()
        self._set_running_ui(False)
        self._notify_activity()

    def _write_sidecar_sdf(self, pdbqt_out: str) -> None:
        from ...dock_io import is_sdf_path, write_pdbqt_poses_sdf

        stamp = time.strftime("%H:%M:%S")
        src = Path(pdbqt_out)
        if is_sdf_path(src):
            return
        if not src.is_file():
            self.log.append(f"[{stamp}][system] Output PDBQT not found; skipped SDF.")
            return
        try:
            sdf_path, n_written = write_pdbqt_poses_sdf(src, template=self._ligand_template_mol())
        except Exception as exc:
            self.log.append(f"[{stamp}][system] SDF conversion failed: {exc}")
            return
        if n_written:
            self.log.append(f"[{stamp}][system] Wrote {n_written} pose(s) to {sdf_path}.")
        else:
            self.log.append(f"[{stamp}][system] Could not convert PDBQT poses to SDF.")

    def _clear_batch(self) -> None:
        self._batch_ligands = []
        self._batch_cancelled = False
        self._minimize_ins = []
        self._minimize_out = None
        self._minimize_n_poses = 0
        self._placement_out = ""
        self._apo_receptor_path = ""
        self._validation_phase = False
        self._validation_out = ""
        self._crystal_ref_mol = None
        self._pending_user_ligand = None
        self._pending_user_out = ""
        self._stamp_crystal_on_poses = False
        self._validation_ligand_path = ""
        self._validation_pose_mols = []
        tmp = self._batch_tmp
        self._batch_tmp = None
        if tmp is not None:
            try:
                tmp.cleanup()
            except Exception:
                pass
        vtmp = self._validation_tmp
        self._validation_tmp = None
        if vtmp is not None:
            try:
                vtmp.cleanup()
            except Exception:
                pass

    def _write_final_sdf(self, pdbqt_out: str) -> None:
        if self.save_sdf_cb.isChecked():
            self._write_sidecar_sdf(pdbqt_out)

    def _present_dock_results(self, out_path: str) -> None:
        """Load finished poses (all Gnina fields) into the pose browser."""
        from ...dock_io import (
            is_sdf_path,
            mols_from_dock_output,
            stamp_pose_ff_energies,
            write_pose_mols_sdf,
        )

        path = str(self._resolve_path(out_path))
        templates = self._ligand_template_mols()
        template = templates[0] if templates else None
        if self._stamp_crystal_on_poses and self._crystal_ref_mol is not None:
            template = self._crystal_ref_mol
        log = f"{self._stdout_buf or ''}\n{self._stderr_buf or ''}"
        try:
            mols = mols_from_dock_output(path, template=template, log_text=log)
        except Exception as exc:
            stamp = time.strftime("%H:%M:%S")
            self.log.append(f"[{stamp}][system] Could not load dock results: {exc}")
            return
        from ...dock_validation import (
            crystal_ref_label,
            existing_crystal_ligand_path,
            stamp_crystal_ref,
            stamp_crystal_rmsd,
        )

        if self._stamp_crystal_on_poses and self._crystal_ref_mol is not None:
            top = stamp_crystal_rmsd(mols, self._crystal_ref_mol)
            if top is not None:
                self._crystal_rmsd = top
                stamp = time.strftime("%H:%M:%S")
                self.log.append(
                    f"[{stamp}][system] Internal validation: top pose crystal RMSD = {top:.3f} Å."
                )
        if self._stamp_crystal_on_poses:
            ref_path = (self._validation_ligand_path or "").strip()
            if self._crystal_ref_mol is not None or ref_path:
                stamp_crystal_ref(mols, crystal_ref_label(self._crystal_ref_mol, ref_path))
        stamp_pose_ff_energies(mols)
        mols = self._apply_pharmacophore_filter(mols)
        if is_sdf_path(path) and mols:
            try:
                write_pose_mols_sdf(mols, path)
            except Exception:
                pass
        extra = [m for m in (self._validation_pose_mols or []) if m is not None]
        if extra and not self._stamp_crystal_on_poses:
            extra = self._apply_pharmacophore_filter(extra, log=False)
            mols = extra + list(mols)
        opener = getattr(self._main_window, "open_dock_results_window", None)
        if not callable(opener) or not mols:
            return
        rec = self._receptor_for_gnina() or (self.edit_receptor.text() or "").strip()
        writer = getattr(self._main_window, "write_dock_poses_to_table", None)
        if callable(writer):
            try:
                col = writer(mols)
            except Exception:
                col = None
            if col:
                stamp = time.strftime("%H:%M:%S")
                self.log.append(f"[{stamp}][system] Wrote packed poses to “{col}”.")
        title = f"Pose browser — {Path(path).name}"
        if self._crystal_rmsd is not None:
            title += f"  (crystal RMSD {self._crystal_rmsd:.3f} Å)"
        crystal = existing_crystal_ligand_path(
            self._crystal_ligand_path
        ) or existing_crystal_ligand_path(self._validation_ligand_path)
        opener(mols, title=title, receptor_path=rec or None, crystal_path=crystal or None)
        stamp = time.strftime("%H:%M:%S")
        self.log.append(f"[{stamp}][system] Opened {len(mols)} pose(s) in the pose browser.")

    def _restore_sdf_bonds(self, sdf_path: str) -> None:
        from ...dock_io import is_sdf_path, restore_sdf_bond_orders

        if not is_sdf_path(sdf_path):
            return
        templates = self._ligand_template_mols()
        if not templates:
            return
        stamp = time.strftime("%H:%M:%S")
        try:
            n = restore_sdf_bond_orders(sdf_path, templates)
        except Exception as exc:
            self.log.append(f"[{stamp}][system] Could not restore SDF bond orders: {exc}")
            return
        if n:
            self.log.append(
                f"[{stamp}][system] Restored bond orders on {n} pose(s) from the input ligand."
            )

    def _after_successful_dock(self, placement_path: str) -> None:
        self._restore_sdf_bonds(placement_path)
        self._log_flex_output(placement_path)
        if self.minimize_poses_cb.isChecked() and self._start_minimize_phase(placement_path):
            return
        self._write_final_sdf(placement_path)
        self._present_dock_results(placement_path)
        self._clear_batch()
        self._set_running_ui(False)
        self._notify_activity()

    def _log_flex_output(self, pose_path: str) -> None:
        if self._flex_mode() == "off":
            return
        dest = Path(flex_out_path(str(self._resolve_path(pose_path))))
        stamp = time.strftime("%H:%M:%S")
        if dest.is_file():
            self.log.append(f"[{stamp}][system] Flexible residues: {dest}.")
        else:
            self.log.append(f"[{stamp}][system] Flexible-residue output was not written ({dest}).")

    def _start_minimize_phase(self, placement_path: str) -> bool:
        from ...dock_io import is_sdf_path, load_sdf_mols, split_ligand_pdbqt_records

        src = Path(placement_path)
        if not src.is_file():
            return False
        tmp = self._ensure_batch_tmp("gnina_min_")
        self._placement_out = placement_path
        if is_sdf_path(src):
            n_poses = len(load_sdf_mols(src))
            if n_poses < 1:
                return False
            self._minimize_ins = [src]
            self._minimize_out = tmp / "min_all.sdf"
            self._minimize_n_poses = n_poses
            stamp = time.strftime("%H:%M:%S")
            self.log.append(
                f"[{stamp}][system] Minimizing {n_poses} docked pose(s) from SDF in one Gnina process."
            )
            self._start_minimize_job()
            return True
        try:
            records = split_ligand_pdbqt_records(src.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            return False
        if not records:
            return False
        self._minimize_ins = []
        self._minimize_out = tmp / "min_all.pdbqt"
        for i, rec in enumerate(records, start=1):
            lig = tmp / f"place_{i:03d}.pdbqt"
            lig.write_text(rec, encoding="utf-8")
            self._minimize_ins.append(lig)
        self._minimize_n_poses = len(records)
        stamp = time.strftime("%H:%M:%S")
        self.log.append(
            f"[{stamp}][system] Minimizing {len(records)} docked pose(s) in one Gnina process."
        )
        self._start_minimize_job()
        return True

    def _start_minimize_job(self) -> None:
        min_out = self._minimize_out
        if min_out is None:
            return
        argv = self._build_minimize_argv(
            [str(p) for p in self._minimize_ins],
            str(min_out),
        )
        n = self._minimize_n_poses or len(self._minimize_ins)
        launch = self._launch_argv(argv)
        stamp = time.strftime("%H:%M:%S")
        self.log.append(
            f"[{stamp}][system] Minimize ({n} pose(s)): {self._resolved_exe} {' '.join(launch)}"
        )
        self._notify_activity()
        self._start_gnina_process(launch)

    def _finish_minimize_keep_placement(self) -> None:
        dest = (self._placement_out or (self.edit_out.text() or "").strip()).strip()
        stamp = time.strftime("%H:%M:%S")
        self.log.append(f"[{stamp}][system] Pose minimization stopped; keeping placement poses.")
        if dest:
            self._write_final_sdf(dest)
            self._present_dock_results(dest)
        self._clear_batch()

    def _write_combined_minimize_results(self) -> None:
        from ...dock_io import (
            combine_placement_and_minimized,
            combine_sdf_placement_and_minimized,
            is_sdf_path,
            split_pdbqt_models,
        )

        dest = (self._placement_out or "").strip()
        min_path = self._minimize_out
        if not dest or min_path is None:
            return
        src = Path(dest)
        stamp = time.strftime("%H:%M:%S")
        if is_sdf_path(src):
            _, n_written = combine_sdf_placement_and_minimized(src, min_path, src)
            self._restore_sdf_bonds(dest)
            self.log.append(
                f"[{stamp}][system] Wrote placement and minimized poses ({n_written} record(s)) to {dest}."
            )
            return
        placement = src.read_text(encoding="utf-8", errors="replace")
        if min_path.is_file() and min_path.stat().st_size > 0:
            min_blocks = split_pdbqt_models(min_path.read_text(encoding="utf-8", errors="replace"))
        else:
            min_blocks = []
        combined = combine_placement_and_minimized(placement, min_blocks)
        src.write_text(combined, encoding="utf-8")
        n_min = sum(1 for b in min_blocks if (b or "").strip())
        self.log.append(
            f"[{stamp}][system] Wrote placement and minimized poses ({n_min} minimized) to {dest}."
        )
        self._write_final_sdf(dest)

    def _on_validation_finished(self, code: int, status: QProcess.ExitStatus) -> None:
        stamp = time.strftime("%H:%M:%S")
        self._validation_phase = False
        failed = code != 0 or status == QProcess.CrashExit or self._batch_cancelled
        self.log.append(f"[{stamp}][system] Gnina finished internal validation (exit code {code}).")
        if self._batch_cancelled:
            self._clear_batch()
            self._set_running_ui(False)
            self._notify_activity()
            return
        if failed:
            self.log.append(
                f"[{stamp}][system] Internal validation failed; continuing with docking."
            )
        else:
            self._record_crystal_validation_rmsd()
        pending = self._pending_user_ligand
        pending_out = (self._pending_user_out or "").strip()
        self._pending_user_ligand = None
        self._pending_user_out = ""
        if pending is None:
            out = (self._validation_out or self._effective_out_path() or "").strip()
            if not failed and out:
                self._stamp_crystal_on_poses = True
                self._after_successful_dock(out)
                return
            self._clear_batch()
            self._set_running_ui(False)
            self._notify_activity()
            return
        try:
            argv = self._build_argv(ligand=pending, out=pending_out)
        except Exception as exc:
            self.log.append(f"[{stamp}][system] Could not start docking after validation: {exc}")
            self._clear_batch()
            self._set_running_ui(False)
            self._notify_activity()
            return
        launch = self._launch_argv(argv)
        self.log.append(f"[{stamp}][system] Launch: {self._resolved_exe} {' '.join(launch)}")
        self._notify_activity()
        self._start_gnina_process(launch)

    def _record_crystal_validation_rmsd(self) -> None:
        from ...dock_io import mols_from_dock_output, stamp_pose_ff_energies
        from ...dock_validation import crystal_ref_label, stamp_crystal_ref, stamp_crystal_rmsd

        path = (self._validation_out or "").strip()
        crystal = self._crystal_ref_mol
        stamp = time.strftime("%H:%M:%S")
        if not path or crystal is None:
            return
        try:
            mols = mols_from_dock_output(path, template=crystal)
        except Exception as exc:
            self.log.append(f"[{stamp}][system] Could not read validation poses: {exc}")
            return
        top = stamp_crystal_rmsd(mols, crystal)
        stamp_crystal_ref(mols, crystal_ref_label(crystal, self._validation_ligand_path or path))
        stamp_pose_ff_energies(mols)
        self._validation_pose_mols = [m for m in mols if m is not None]
        if top is None:
            self.log.append(
                f"[{stamp}][system] Internal validation finished; could not compute crystal RMSD."
            )
            return
        self._crystal_rmsd = top
        self.log.append(
            f"[{stamp}][system] Internal validation: top pose crystal RMSD = {top:.3f} Å."
        )

    def _on_proc_finished(self, code: int, status: QProcess.ExitStatus) -> None:
        stamp = time.strftime("%H:%M:%S")
        if self._validation_phase:
            self._on_validation_finished(code, status)
            return
        if self._minimize_ins:
            n = self._minimize_n_poses or len(self._minimize_ins)
            self.log.append(
                f"[{stamp}][system] Gnina finished minimize of {n} pose(s) (exit code {code})."
            )
            if self._batch_cancelled:
                self._finish_minimize_keep_placement()
                self._set_running_ui(False)
                self._notify_activity()
                return
            if code != 0 or status == QProcess.CrashExit:
                self.log.append(f"[{stamp}][system] Minimize failed; keeping the placement poses.")
                self._finish_minimize_keep_placement()
                self._set_running_ui(False)
                self._notify_activity()
                return
            try:
                self._write_combined_minimize_results()
            except Exception as exc:
                self.log.append(f"[{stamp}][system] Could not combine minimized poses: {exc}")
                self._finish_minimize_keep_placement()
            else:
                dest = (self._placement_out or self._effective_out_path() or "").strip()
                if dest:
                    self._present_dock_results(dest)
                self._clear_batch()
            self._set_running_ui(False)
            self._notify_activity()
            return

        self.log.append(f"[{stamp}][system] Gnina finished (exit code {code}).")
        if int(code) == 127:
            self.log.append(
                f"[{stamp}][system] " + gnina_exit_127_message(self._resolved_exe, self._stderr_buf)
            )
        failed = code != 0 or status == QProcess.CrashExit or self._batch_cancelled
        out = self._effective_out_path()
        if not failed and out:
            self._after_successful_dock(out)
            return
        self._clear_batch()
        self._set_running_ui(False)
        self._notify_activity()

    def _append_stdout(self) -> None:
        text = bytes(self._proc.readAllStandardOutput()).decode("utf-8", errors="replace")
        self._stdout_buf += text
        if text:
            self.log.append(text.rstrip("\n"))

    def _append_stderr(self) -> None:
        text = bytes(self._proc.readAllStandardError()).decode("utf-8", errors="replace")
        self._stderr_buf += text
        if text:
            self.log.append(text.rstrip("\n"))

    def _resolve_path(self, path: str) -> Path:
        p = Path(path)
        if p.is_absolute():
            return p
        wd = (self.edit_wd.text() or "").strip()
        if wd:
            return Path(wd) / p
        return p

    def _is_openbabel_ligand(self, path: str) -> bool:
        from ...dock_io import ligand_is_openbabel_format

        return ligand_is_openbabel_format(self._resolve_path(path))

    def _ligand_template_mols(self):
        """Input ligand molecules used to restore Kekulé/aromatic bonds on SDF poses."""
        from rdkit import Chem

        from ...dock_io import load_sdf_mols

        mols: list = []
        seen: set[str] = set()
        paths: list[Path] = []
        paths.extend(self._batch_ligands)
        lig = (self.edit_ligand.text() or "").strip()
        if lig:
            paths.append(self._resolve_path(lig))
        for path in paths:
            key = str(path)
            if key in seen or not path.is_file():
                continue
            seen.add(key)
            suf = path.suffix.lower()
            try:
                if suf in {".sdf", ".sd"}:
                    mols.extend(load_sdf_mols(path))
                elif suf == ".mol":
                    mol = Chem.MolFromMolFile(str(path), removeHs=False)
                    if mol is not None:
                        mols.append(mol)
            except Exception:
                continue
        return mols

    def _ligand_template_mol(self):
        """First input ligand molecule, used to restore bond orders."""
        mols = self._ligand_template_mols()
        return mols[0] if mols else None

    def _prepare_gnina_ligands(self, ligand: str) -> list[Path]:
        """Return ligand files to pass to Gnina (SDF when bond orders can be restored)."""
        if self._ligand_source_key() == "rows":
            return self._prepare_table_row_ligands()
        from ...dock_io import (
            ligand_is_openbabel_format,
            split_ligand_pdbqt_records,
            write_ligand_pdbqt_as_sdf,
        )

        if not (ligand or "").strip():
            raise ValueError("Choose a ligand file (PDBQT or SDF).")
        lig_path = self._resolve_path(ligand)
        if ligand_is_openbabel_format(lig_path):
            return [lig_path]
        raw = lig_path.read_text(encoding="utf-8", errors="replace")
        records = split_ligand_pdbqt_records(raw)
        self._clear_batch()
        tmp = self._ensure_batch_tmp("gnina_ligands_")
        dest = tmp / f"{lig_path.stem}.sdf"
        _, n_written = write_ligand_pdbqt_as_sdf(lig_path, dest)
        if n_written:
            self._batch_ligands = [dest]
            return [dest]
        if len(records) <= 1:
            return [lig_path]
        self._batch_cancelled = False
        for i, rec in enumerate(records, start=1):
            lp = tmp / f"lig_{i:03d}.pdbqt"
            lp.write_text(rec, encoding="utf-8")
            self._batch_ligands.append(lp)
        return list(self._batch_ligands)

    def _prepare_table_row_ligands(self) -> list[Path]:
        """Write selected-row ensembles to a temp SDF for one Gnina process."""
        from ...dock_io import write_pose_mols_sdf

        mols = self._mols_from_selected_rows()
        if not mols:
            col = (self.combo_confs.currentText() or "").strip() or "the chosen column"
            raise ValueError(f"No 3D ligands in the selected rows for “{col}”.")
        self._clear_batch()
        tmp = self._ensure_batch_tmp("gnina_table_")
        dest = tmp / "table_ligands.sdf"
        n_written = write_pose_mols_sdf(mols, dest)
        if n_written < 1:
            raise ValueError("Could not write selected-row ligands as SDF.")
        self._batch_ligands = [dest]
        stamp = time.strftime("%H:%M:%S")
        self.log.append(
            f"[{stamp}][system] Docking {n_written} ligand(s) from "
            f"{len(self._selected_row_indices())} selected row(s) "
            f"({self.combo_confs.currentText() or 'Structure'})."
        )
        return [dest]

    def _selected_row_indices(self) -> list[int]:
        app = self._main_window
        getter = getattr(app, "_selected_logical_rows", None) if app is not None else None
        if not callable(getter):
            return []
        try:
            return [int(r) for r in getter()]
        except Exception:
            return []

    def _mols_from_selected_rows(self) -> list:
        from ...ui.main_window.conformer_writeback import mol_for_ensemble_column

        app = self._main_window
        if app is None:
            raise ValueError("Open Gnina from the main window to dock selected table rows.")
        rows = self._selected_row_indices()
        if not rows:
            raise ValueError("Select one or more table rows to dock.")
        column = (self.combo_confs.currentText() or "").strip()
        if not column:
            raise ValueError("Choose a conformations column.")
        out: list = []
        if column == "Structure":
            collect = getattr(app, "collect_scoped_table_mols", None)
            if not callable(collect):
                raise ValueError("The table is not available for selected-row docking.")
            for oid, mol in collect("Structure", only_selected=True):
                if mol is None:
                    continue
                ligand = ligand_mol_from_ensemble(mol, int(oid))
                if ligand is not None:
                    out.append(ligand)
            return out
        model = getattr(app, "_table_model", None)
        if model is None:
            raise ValueError("The table is not available for selected-row docking.")
        for row in rows:
            try:
                oid = int(model.row_oid(row))
            except Exception:
                continue
            packed = mol_for_ensemble_column(app, oid, column, min_conformers=1)
            if packed is None:
                continue
            ligand = ligand_mol_from_ensemble(packed, oid)
            if ligand is not None:
                out.append(ligand)
        return out

    def _prepare_ligand_batch(self, ligand: str) -> int:
        paths = self._prepare_gnina_ligands(ligand)
        return len(paths)

    def _start_gnina_process(self, launch: list[str]) -> None:
        self._dismiss_for_run()
        exe = self._resolved_exe or self._gnina_executable()
        wd = (self.edit_wd.text() or "").strip()
        if gnina_uses_wsl():
            program, args = gnina_qprocess_spec(exe, launch, work_dir=wd)
            self._proc.start(program, args)
            return
        env = QProcessEnvironment.systemEnvironment()
        exe_dir = str(Path(exe).parent)
        path = env.value("PATH") or ""
        if exe_dir and exe_dir not in path.split(os.pathsep):
            env.insert("PATH", exe_dir + os.pathsep + path)
        for key, value in gnina_launch_env(exe).items():
            env.insert(key, value)
        self._proc.setProcessEnvironment(env)
        if wd:
            self._proc.setWorkingDirectory(str(Path(wd)))
        self._proc.start(exe, launch)

    def _same_input_path(self, left: str, right: str) -> bool:
        a = str(left or "").strip()
        b = str(right or "").strip()
        if not a or not b:
            return False
        pa = self._resolve_path(a)
        pb = self._resolve_path(b)
        try:
            if pa.is_file() and pb.is_file():
                return pa.resolve() == pb.resolve()
        except OSError:
            pass
        return str(pa) == str(pb)

    def _ensure_validation_tmp(self) -> Path:
        if self._validation_tmp is None:
            self._validation_tmp = tempfile.TemporaryDirectory(prefix="gnina_valid_")
        return Path(self._validation_tmp.name)

    def _ligand_arg(self, lig_paths: list[Path]) -> str | list[str]:
        if len(lig_paths) == 1:
            return str(lig_paths[0])
        return [str(p) for p in lig_paths]

    def _sidecar_for_receptor(self, rec: str) -> str:
        sidecar = (self._crystal_ligand_path or "").strip()
        prep = (self._prepare_receptor_path or "").strip()
        if sidecar and prep and not self._same_input_path(rec, prep):
            return ""
        return sidecar

    def _setup_crystal_validation(
        self,
        rec: str,
        *,
        durable_dir: Path | None = None,
        validate: bool = True,
    ) -> None:
        from ...dock_validation import load_crystal_mol, prepare_crystal_ligand

        dest = self._ensure_validation_tmp()
        rec_path = str(self._resolve_path(rec)) if rec else rec
        sidecar = self._sidecar_for_receptor(rec) if validate else ""
        prep = prepare_crystal_ligand(rec_path, dest, crystal_ligand_path=sidecar)
        self._validation_ligand_path = ""
        if prep is None:
            return
        self._apo_receptor_path = prep.apo_receptor_path
        if prep.stripped_from_receptor and durable_dir is not None:
            src = Path(prep.apo_receptor_path)
            durable = Path(durable_dir) / src.name
            try:
                durable.parent.mkdir(parents=True, exist_ok=True)
                if not durable.exists() or durable.resolve() != src.resolve():
                    durable.write_bytes(src.read_bytes())
                    self._apo_receptor_path = str(durable)
            except OSError:
                pass
        if not validate:
            stamp = time.strftime("%H:%M:%S")
            if prep.stripped_from_receptor:
                self.log.append(f"[{stamp}][system] Receptor ligand stripped for apo docking.")
            return
        self._validation_ligand_path = prep.crystal_ligand_path
        self._crystal_ref_mol = load_crystal_mol(prep.crystal_ligand_path)
        stamp = time.strftime("%H:%M:%S")
        if prep.stripped_from_receptor:
            self.log.append(
                f"[{stamp}][system] Internal validation: ligand found in the receptor; "
                "docking into an apo copy."
            )
        else:
            self.log.append(
                f"[{stamp}][system] Internal validation: redocking crystal ligand "
                f"{Path(prep.crystal_ligand_path).name}."
            )

    def _run_gnina(self) -> None:
        if self._proc.state() != QProcess.NotRunning:
            QMessageBox.information(self, "Dock", "A Gnina run is already in progress.")
            return
        try:
            exe = self._gnina_executable()
        except Exception as e:
            QMessageBox.warning(self, "Dock", str(e))
            return
        if gnina_uses_wsl():
            from ...wsl import wsl_available

            if not wsl_available():
                QMessageBox.warning(
                    self,
                    "Dock",
                    "WSL was not found. Set the WSL executable under Settings → WSL, "
                    "then install Gnina in that distro so `gnina` is on PATH.",
                )
                return
            resolved = resolve_gnina_command(exe)
            if resolved is None:
                QMessageBox.warning(self, "Dock", gnina_missing_message(exe))
                return
            exe = resolved
        else:
            resolved = resolve_gnina_command(exe) or resolve_user_executable(exe)
            if resolved is None:
                QMessageBox.warning(self, "Dock", gnina_missing_message(exe))
                return
            exe = resolved
        self._resolved_exe = exe
        self._dismiss_for_run()
        self._force_no_gpu = False
        self._crystal_rmsd = None
        self._apo_receptor_path = ""
        self._validation_phase = False
        self._stamp_crystal_on_poses = False
        self._pending_user_ligand = None
        self._pending_user_out = ""
        self._validation_ligand_path = ""
        self._validation_pose_mols = []
        stamp = time.strftime("%H:%M:%S")
        if self.gpu_cb.isChecked() and sys.platform != "darwin":
            if not cuda_available():
                self._force_no_gpu = True
                self.log.append(f"[{stamp}][system] CUDA not found (nvidia-smi); using --no_gpu.")
        elif not self.gpu_cb.isChecked() or sys.platform == "darwin":
            self._force_no_gpu = True

        rec = (self.edit_receptor.text() or "").strip()
        lig = (self.edit_ligand.text() or "").strip()
        rows = self._ligand_source_key() == "rows"
        lig_paths: list[Path] = []
        try:
            if rows or lig:
                lig_paths = self._prepare_gnina_ligands(lig)
            out = self._effective_out_path()
            if not rec:
                raise ValueError("Choose a receptor PDB or PDBQT file.")
            rec_path = self._resolve_path(rec)
            if not rec_path.is_file():
                raise ValueError(f"Receptor file not found:\n{rec_path}")
            self._require_dock_pharmacophore()
            if not out:
                raise ValueError("Set an output path.")
            self._setup_crystal_validation(
                rec,
                durable_dir=self._resolve_path(out).parent,
                validate=self.validate_crystal_cb.isChecked(),
            )
            crystal_lig = (self._validation_ligand_path or "").strip()
            if not lig_paths and not crystal_lig:
                raise ValueError("Choose a ligand file (PDBQT or SDF).")
            extra_validation = False
            if not lig_paths and crystal_lig:
                lig_paths = [Path(crystal_lig)]
                self._stamp_crystal_on_poses = True
                self.log.append(
                    f"[{stamp}][system] No docking ligand; redocking the crystal ligand."
                )
            elif crystal_lig and (
                len(lig_paths) != 1 or not self._same_input_path(str(lig_paths[0]), crystal_lig)
            ):
                extra_validation = True
            elif crystal_lig:
                self._stamp_crystal_on_poses = True
            ligand_arg = self._ligand_arg(lig_paths)
            if extra_validation:
                vout = str(self._ensure_validation_tmp() / "crystal_redock.sdf")
                self._validation_out = vout
                self._pending_user_ligand = ligand_arg
                self._pending_user_out = out
                self._validation_phase = True
                argv = self._build_argv(ligand=crystal_lig, out=vout)
            else:
                argv = self._build_argv(ligand=ligand_arg, out=out)
        except Exception as e:
            self._clear_batch()
            self._reveal_dock_dialog()
            QMessageBox.warning(self, "Dock", str(e))
            return

        out_path = Path(out)
        if lig_paths and self._is_openbabel_ligand(str(lig_paths[0])):
            self.log.append(
                f"[{stamp}][system] Ligand and output are {out_path.suffix.lower() or 'SDF'}."
            )
        if len(lig_paths) > 1:
            self.log.append(
                f"[{stamp}][system] Ligand PDBQT has {len(lig_paths)} records; "
                "docking them in one Gnina process."
            )
        elif self._batch_ligands and self._is_openbabel_ligand(str(self._batch_ligands[0])):
            self.log.append(
                f"[{stamp}][system] Converted ligand PDBQT to SDF so OpenBabel can use bond orders."
            )
        launch = self._launch_argv(argv)
        self.log.append(f"[{stamp}][system] Launch: {exe} {' '.join(launch)}")
        self._notify_activity()
        self._start_gnina_process(launch)

    _run_smina = _run_gnina
    _prepare_smina_ligands = _prepare_gnina_ligands

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        if self._proc.state() != QProcess.NotRunning:
            self._stop_proc()
        else:
            self._clear_batch()
        self._notify_activity()
        super().closeEvent(event)


SminaDockDialog = GninaDockDialog
