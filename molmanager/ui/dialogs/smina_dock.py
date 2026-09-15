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

"""Modeless UI to run Smina for rigid receptor–ligand docking."""

from __future__ import annotations

import os
import shlex
import tempfile
import time
from collections.abc import Sequence
from pathlib import Path

from PyQt5.QtCore import QProcess, QProcessEnvironment, Qt, QTimer
from PyQt5.QtGui import QCloseEvent, QKeySequence
from PyQt5.QtWidgets import (
    QCheckBox,
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
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ...bundled_paths import default_external_executable, resolve_user_executable, smina_launch_env
from ...dock_io import AUTOBOX_LIGAND_FILTER
from ..qt_widget_utils import apply_monospace_to_text_edit, make_window_minimizable

_LIGAND_FILE_FILTER = (
    "Ligand (*.sdf *.sd *.mol2 *.mol *.pdbqt);;SDF (*.sdf *.sd);;"
    "MOL2 (*.mol2);;Molfile (*.mol);;PDBQT (*.pdbqt);;All files (*.*)"
)
_OUT_FILE_FILTER = "SDF (*.sdf *.sd);;PDBQT (*.pdbqt);;All files (*.*)"


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

    Smina accepts several ``--ligand`` files in one process. Concatenated Meeko
    PDBQT is invalid as a single file, so split records are passed this way.
    SDF/MOL2 is passed through so Smina never needs a ligand PDBQT file.
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


def _write_smina_config(argv: list[str], dest: Path) -> Path:
    """Write a Smina ``--config`` file from an argv list (no executable).

    Repeated ``--ligand`` flags become repeated ``ligand =`` lines, which Smina
    accepts in one process without a long Windows command line.
    """
    lines: list[str] = []
    i = 0
    n = len(argv)
    while i < n:
        tok = argv[i]
        if not tok.startswith("--"):
            i += 1
            continue
        key = tok[2:]
        if i + 1 < n and not argv[i + 1].startswith("--"):
            val = argv[i + 1]
            if any(ch.isspace() for ch in val):
                val = f'"{val}"'
            lines.append(f"{key} = {val}")
            i += 2
            continue
        lines.append(f"{key} = true")
        i += 1
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return dest


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


class SminaDockDialog(QDialog):
    """
    Front-end for the Smina CLI (Vina-compatible docking with additional scoring options).

    Expects a rigid receptor PDBQT, a ligand SDF (PDBQT is converted first), and a search box.
    Install Smina separately and ensure ``smina`` is on PATH, or set the executable path below.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._main_window = parent
        self.setWindowTitle("Dock — Smina")
        self.setModal(False)
        self.setWindowModality(Qt.NonModal)
        self.setMinimumWidth(480)
        self.resize(540, 500)

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

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 6)
        root.setSpacing(6)

        io_gb = QGroupBox("Input / output")
        io_form = QFormLayout(io_gb)
        io_form.setContentsMargins(8, 6, 8, 6)
        io_form.setSpacing(4)
        self.edit_exe = QLineEdit(default_external_executable("smina"))
        self.edit_exe.setToolTip(
            "Path to the smina binary. Uses molmanager/resources/bin/<platform>/smina when bundled, "
            "otherwise PATH (e.g. C:\\Program Files\\smina\\smina.exe)."
        )
        io_form.addRow("Smina:", _browse_path_row(self.edit_exe, self._browse_exe))

        self.edit_receptor = QLineEdit()
        self.edit_receptor.setPlaceholderText("receptor.pdbqt")
        self.edit_receptor.setToolTip("Rigid receptor in PDBQT format.")
        io_form.addRow("Receptor:", _browse_path_row(self.edit_receptor, self._browse_receptor))

        self.edit_ligand = QLineEdit()
        self.edit_ligand.setPlaceholderText("ligand.sdf")
        self.edit_ligand.setToolTip(
            "Ligand SDF (also MOL/MOL2). PDBQT is accepted but converted to SDF first so "
            "aromatic and double bonds are not guessed from PDBQT. Receptor stays PDBQT."
        )
        io_form.addRow("Ligand:", _browse_path_row(self.edit_ligand, self._browse_ligand))

        self.edit_out = QLineEdit()
        self.edit_out.setPlaceholderText("out.sdf")
        self.edit_out.setToolTip(
            "Smina writes docked poses here. SDF keeps bond orders; PDBQT does not."
        )
        self.save_sdf_cb = QCheckBox("Save as SDF")
        self.save_sdf_cb.setChecked(True)
        self.save_sdf_cb.setToolTip(
            "Write poses as SDF (Smina --out). Uncheck to write PDBQT instead. "
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
        root.addWidget(io_gb)

        box_gb = QGroupBox("Search box (Å)")
        box_form = QFormLayout(box_gb)
        box_form.setContentsMargins(8, 6, 8, 6)
        box_form.setSpacing(4)
        auto_row = QHBoxLayout()
        auto_row.setContentsMargins(0, 0, 0, 0)
        self.autobox_cb = QCheckBox("Autobox")
        self.autobox_cb.setToolTip(
            "Let Smina set the search box from a ligand (--autobox_ligand). "
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
        self.spin_cx.setToolTip("Box center X (same coordinates as receptor PDBQT).")
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
        self.spin_energy_range = QDoubleSpinBox()
        self.spin_energy_range.setRange(0.5, 50.0)
        self.spin_energy_range.setDecimals(2)
        self.spin_energy_range.setValue(3.0)
        self.spin_energy_range.setToolTip(
            "Maximum energy difference (kcal/mol) from best mode to keep."
        )
        self.spin_cpu = QSpinBox()
        self.spin_cpu.setRange(0, 128)
        self.spin_cpu.setValue(0)
        self.spin_cpu.setSpecialValueText("auto")
        self.spin_cpu.setToolTip("CPU threads for Smina; 0 / auto omits --cpu (tool default).")
        opt_form.addRow(
            "Search:",
            _spin_row(
                (
                    ("Exh.", self.spin_exhaust),
                    ("Modes", self.spin_modes),
                    ("ΔE", self.spin_energy_range),
                    ("CPU", self.spin_cpu),
                )
            ),
        )
        self.minimize_poses_cb = QCheckBox("Minimize Docked Poses")
        self.minimize_poses_cb.setChecked(False)
        self.minimize_poses_cb.setToolTip(
            "After docking, energy-minimize all poses in the receptor in one Smina process "
            "(--minimize). Results include both the placement pose and the minimized pose."
        )
        opt_form.addRow(self.minimize_poses_cb)

        self.edit_wd = QLineEdit()
        self.edit_wd.setPlaceholderText("Optional working directory")
        self.edit_wd.setToolTip(
            "If set, Smina starts with this as the current directory (relative paths resolve here)."
        )
        opt_form.addRow("Work dir:", self.edit_wd)

        self.edit_extra = QLineEdit()
        self.edit_extra.setPlaceholderText("Optional extra args (e.g. --seed 42)")
        opt_form.addRow("Extra:", self.edit_extra)
        root.addWidget(opt_gb)

        log_gb = QGroupBox("Log")
        log_v = QVBoxLayout(log_gb)
        log_v.setContentsMargins(6, 4, 6, 4)
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(120)
        apply_monospace_to_text_edit(self.log)
        log_v.addWidget(self.log)
        root.addWidget(log_gb, 1)

        btn_row = QHBoxLayout()
        self.btn_run = QPushButton("Run Smina")
        self.btn_run.clicked.connect(self._run_smina)
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

        QShortcut(QKeySequence("Ctrl+Return"), self, activated=self._run_smina)
        make_window_minimizable(self)

    def is_smina_running(self) -> bool:
        return self._proc.state() != QProcess.NotRunning

    def cancel_smina(self) -> bool:
        if self._proc.state() == QProcess.NotRunning:
            return False
        self._stop_proc()
        return True

    def _notify_activity(self) -> None:
        w = self._main_window
        hub = getattr(w, "background_activity", None) if w is not None else None
        if hub is not None:
            hub.notify_changed()

    def _browse_exe(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Smina executable", self.edit_exe.text(), "All files (*.*)"
        )
        if path:
            self.edit_exe.setText(path)

    def _browse_receptor(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Receptor PDBQT", "", "PDBQT (*.pdbqt);;All files (*.*)"
        )
        if path:
            self.edit_receptor.setText(path)

    def _browse_ligand(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Ligand", "", _LIGAND_FILE_FILTER)
        if path:
            self.edit_ligand.setText(path)

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

    def _smina_executable(self) -> str:
        return (self.edit_exe.text() or "").strip() or default_external_executable("smina")

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
        cfg = self._ensure_batch_tmp("smina_cfg_") / "smina.conf"
        _write_smina_config(argv, cfg)
        return ["--config", str(cfg)]

    def _build_argv(
        self,
        *,
        ligand: str | Sequence[str] | None = None,
        out: str | None = None,
    ) -> list[str]:
        rec = (self.edit_receptor.text() or "").strip()
        lig_src: str | Sequence[str] = (
            ligand if ligand is not None else (self.edit_ligand.text() or "")
        )
        lig_args, first_lig = _ligand_cli_args(lig_src)
        out_path = (out if out is not None else self._effective_out_path()).strip()
        if not rec:
            raise ValueError("Choose a receptor PDBQT file.")
        if not out_path:
            raise ValueError("Set an output path.")

        # Smina uses Vina-compatible flags for common docking parameters.
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
                "--energy_range",
                f"{self.spin_energy_range.value():.2f}",
            ]
        )
        cpu = int(self.spin_cpu.value())
        if cpu > 0:
            argv.extend(["--cpu", str(cpu)])
        extra = (self.edit_extra.text() or "").strip()
        if extra:
            argv.extend(shlex.split(extra))
        return argv

    def _build_minimize_argv(self, ligand: str | Sequence[str], out: str) -> list[str]:
        rec = (self.edit_receptor.text() or "").strip()
        if not rec:
            raise ValueError("Choose a receptor PDBQT file.")
        lig_args, _first = _ligand_cli_args(ligand)
        argv = ["--receptor", rec, *lig_args, "--out", out, "--minimize"]
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
        if n_min:
            self.log.append(
                f"[{stamp}][system] Smina started (PID {pid}) minimizing {n_min} pose(s)."
            )
        elif n_lig > 1:
            self.log.append(f"[{stamp}][system] Smina started (PID {pid}) docking {n_lig} ligands.")
        else:
            self.log.append(f"[{stamp}][system] Smina started (PID {pid}).")
        self._notify_activity()

    def _on_proc_error(self, error: QProcess.ProcessError) -> None:
        if error != QProcess.FailedToStart:
            return
        detail = (self._proc.errorString() or "").strip() or "Smina failed to start."
        stamp = time.strftime("%H:%M:%S")
        self.log.append(f"[{stamp}][system] {detail}")
        if self._minimize_ins:
            self._finish_minimize_keep_placement()
        else:
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
        tmp = self._batch_tmp
        self._batch_tmp = None
        if tmp is not None:
            try:
                tmp.cleanup()
            except Exception:
                pass

    def _write_final_sdf(self, pdbqt_out: str) -> None:
        if self.save_sdf_cb.isChecked():
            self._write_sidecar_sdf(pdbqt_out)

    def _present_dock_results(self, out_path: str) -> None:
        """Load finished poses (all Smina fields) into a new interactive table window."""
        from ...dock_io import is_sdf_path, mols_from_dock_output, write_pose_mols_sdf

        path = str(self._resolve_path(out_path))
        templates = self._ligand_template_mols()
        template = templates[0] if templates else None
        log = f"{self._stdout_buf or ''}\n{self._stderr_buf or ''}"
        try:
            mols = mols_from_dock_output(path, template=template, log_text=log)
        except Exception as exc:
            stamp = time.strftime("%H:%M:%S")
            self.log.append(f"[{stamp}][system] Could not load dock results: {exc}")
            return
        if is_sdf_path(path) and mols:
            try:
                write_pose_mols_sdf(mols, path)
            except Exception:
                pass
        opener = getattr(self._main_window, "open_dock_results_window", None)
        if not callable(opener) or not mols:
            return
        rec = (self.edit_receptor.text() or "").strip()
        opener(mols, title=f"Dock results — {Path(path).name}", receptor_path=rec or None)
        stamp = time.strftime("%H:%M:%S")
        self.log.append(f"[{stamp}][system] Opened {len(mols)} pose(s) in a results table.")

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
        if self.minimize_poses_cb.isChecked() and self._start_minimize_phase(placement_path):
            return
        self._write_final_sdf(placement_path)
        self._present_dock_results(placement_path)
        self._clear_batch()
        self._set_running_ui(False)
        self._notify_activity()

    def _start_minimize_phase(self, placement_path: str) -> bool:
        from ...dock_io import is_sdf_path, load_sdf_mols, split_ligand_pdbqt_records

        src = Path(placement_path)
        if not src.is_file():
            return False
        tmp = self._ensure_batch_tmp("smina_min_")
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
                f"[{stamp}][system] Minimizing {n_poses} docked pose(s) from SDF in one Smina process."
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
            f"[{stamp}][system] Minimizing {len(records)} docked pose(s) in one Smina process."
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
        self._proc.start(self._resolved_exe, launch)

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

    def _on_proc_finished(self, code: int, status: QProcess.ExitStatus) -> None:
        stamp = time.strftime("%H:%M:%S")
        if self._minimize_ins:
            n = self._minimize_n_poses or len(self._minimize_ins)
            self.log.append(
                f"[{stamp}][system] Smina finished minimize of {n} pose(s) (exit code {code})."
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

        self.log.append(f"[{stamp}][system] Smina finished (exit code {code}).")
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

    def _prepare_smina_ligands(self, ligand: str) -> list[Path]:
        """Return ligand files to pass to Smina (SDF when bond orders can be restored)."""
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
        tmp = self._ensure_batch_tmp("smina_ligands_")
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

    def _prepare_ligand_batch(self, ligand: str) -> int:
        paths = self._prepare_smina_ligands(ligand)
        return len(paths)

    def _run_smina(self) -> None:
        if self._proc.state() != QProcess.NotRunning:
            QMessageBox.information(self, "Dock", "A Smina run is already in progress.")
            return
        try:
            exe = self._smina_executable()
        except Exception as e:
            QMessageBox.warning(self, "Dock", str(e))
            return
        resolved = resolve_user_executable(exe)
        if resolved is None:
            QMessageBox.warning(
                self,
                "Dock",
                f"Smina executable not found: {exe}\n\n"
                "Place smina.exe in molmanager/resources/bin/win/ or set the full path.",
            )
            return
        exe = resolved
        self._resolved_exe = exe

        lig = (self.edit_ligand.text() or "").strip()
        try:
            lig_paths = self._prepare_smina_ligands(lig)
            out = self._effective_out_path()
            ligand_arg: str | list[str]
            if len(lig_paths) == 1:
                ligand_arg = str(lig_paths[0])
            else:
                ligand_arg = [str(p) for p in lig_paths]
            argv = self._build_argv(ligand=ligand_arg, out=out)
        except Exception as e:
            self._clear_batch()
            QMessageBox.warning(self, "Dock", str(e))
            return

        env = QProcessEnvironment.systemEnvironment()
        exe_dir = str(Path(exe).parent)
        path = env.value("PATH") or ""
        if exe_dir and exe_dir not in path.split(os.pathsep):
            env.insert("PATH", exe_dir + os.pathsep + path)
        for key, value in smina_launch_env(exe).items():
            env.insert(key, value)
        self._proc.setProcessEnvironment(env)

        wd = (self.edit_wd.text() or "").strip()
        if wd:
            self._proc.setWorkingDirectory(str(Path(wd)))

        stamp = time.strftime("%H:%M:%S")
        out_path = Path(out)
        if lig_paths and self._is_openbabel_ligand(str(lig_paths[0])):
            self.log.append(
                f"[{stamp}][system] Ligand and output are {out_path.suffix.lower() or 'SDF'}; "
                "Smina will not write ligand PDBQT (receptor stays PDBQT)."
            )
        if len(lig_paths) > 1:
            self.log.append(
                f"[{stamp}][system] Ligand PDBQT has {len(lig_paths)} records; "
                "docking them in one Smina process."
            )
        elif self._batch_ligands and self._is_openbabel_ligand(str(self._batch_ligands[0])):
            self.log.append(
                f"[{stamp}][system] Converted ligand PDBQT to SDF so OpenBabel can use bond orders."
            )
        launch = self._launch_argv(argv)
        self.log.append(f"[{stamp}][system] Launch: {exe} {' '.join(launch)}")
        self._notify_activity()
        self._proc.start(exe, launch)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        if self._proc.state() != QProcess.NotRunning:
            self._stop_proc()
        else:
            self._clear_batch()
        self._notify_activity()
        super().closeEvent(event)
