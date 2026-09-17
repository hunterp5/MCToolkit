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

"""Settings → WSL: path to ``wsl.exe`` for Linux-only tools."""

from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ...wsl import (
    default_wsl_executable,
    load_wsl_executable,
    resolve_wsl_executable,
    run_wsl,
    save_wsl_executable,
)
from ..qt_widget_utils import make_window_minimizable


class WslSettingsDialog(QDialog):
    """Choose the Windows Subsystem for Linux executable used by Linux-only tools."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("WSL")
        self.setMinimumWidth(480)

        root = QVBoxLayout(self)
        blurb = QLabel(
            "MolManager can run Linux-only tools (AmberTools / GAFF parameterization "
            "for OpenMM, and similar) through Windows Subsystem for Linux. Point to "
            "the <code>wsl.exe</code> executable this installation should use."
        )
        blurb.setWordWrap(True)
        blurb.setTextFormat(Qt.RichText)
        root.addWidget(blurb)

        form = QFormLayout()
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        self.path_edit = QLineEdit(load_wsl_executable())
        self.path_edit.setPlaceholderText(default_wsl_executable() or "wsl.exe")
        self.path_edit.setToolTip("Path to wsl.exe. Leave as the default to use System32 or PATH.")
        row.addWidget(self.path_edit, 1)
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse)
        row.addWidget(browse)
        detect = QPushButton("Detect")
        detect.setToolTip("Fill the usual Windows wsl.exe location from PATH or System32.")
        detect.clicked.connect(self._detect)
        row.addWidget(detect)
        wrap = QWidget()
        wrap.setLayout(row)
        form.addRow("Executable:", wrap)
        root.addLayout(form)

        test_row = QHBoxLayout()
        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setStyleSheet("color: palette(mid);")
        test_row.addWidget(self.status, 1)
        test_btn = QPushButton("Test")
        test_btn.setToolTip("Run `uname -s` inside WSL to confirm the executable works.")
        test_btn.clicked.connect(self._test)
        test_row.addWidget(test_btn)
        root.addLayout(test_row)

        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        root.addWidget(box)
        make_window_minimizable(self)

    def selected_path(self) -> str:
        return (self.path_edit.text() or "").strip()

    def _browse(self) -> None:
        start = self.selected_path() or default_wsl_executable()
        path, _filt = QFileDialog.getOpenFileName(
            self,
            "WSL executable",
            start,
            "Executables (wsl.exe);;All files (*.*)",
        )
        if path:
            self.path_edit.setText(path)

    def _detect(self) -> None:
        found = default_wsl_executable()
        if not found:
            QMessageBox.information(
                self,
                "WSL",
                "WSL is a Windows feature. No default wsl.exe was found on this system.",
            )
            return
        self.path_edit.setText(found)
        self.status.setText(f"Detected {found}")

    def _test(self) -> None:
        path = self.selected_path() or default_wsl_executable()
        exe = resolve_wsl_executable(path)
        if not exe:
            QMessageBox.warning(
                self,
                "WSL",
                "That path is not an existing executable. Browse to wsl.exe or click Detect.",
            )
            return
        try:
            proc = run_wsl(["uname", "-s"], user_path=exe, timeout=20.0, check=False)
        except FileNotFoundError as exc:
            QMessageBox.warning(self, "WSL", str(exc))
            return
        except Exception as exc:
            QMessageBox.warning(self, "WSL", f"Could not run WSL: {exc}")
            return
        out = ((proc.stdout or "") + (proc.stderr or "")).strip()
        if proc.returncode == 0 and out:
            self.status.setText(f"OK ({exe}): {out.splitlines()[0]}")
            return
        detail = out or f"exit code {proc.returncode}"
        QMessageBox.warning(
            self,
            "WSL",
            f"WSL ran but the test command failed:\n{detail}",
        )
        self.status.setText(f"Failed: {detail}")

    def accept(self) -> None:
        save_wsl_executable(self.selected_path())
        super().accept()
