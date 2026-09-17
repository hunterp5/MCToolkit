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

"""WSL executable settings and launcher."""

from __future__ import annotations

from pathlib import Path

import pytest

from molmanager.wsl import (
    default_wsl_executable,
    windows_path_to_wsl,
    wsl_argv,
)


def test_windows_path_to_wsl_drive_letter() -> None:
    assert windows_path_to_wsl(r"C:\Users\chem\lig.mol2") == "/mnt/c/Users/chem/lig.mol2"
    assert windows_path_to_wsl(Path(r"D:/tmp/openmm")) == "/mnt/d/tmp/openmm"


def test_wsl_argv_requires_executable(monkeypatch) -> None:
    monkeypatch.setattr("molmanager.wsl.resolve_wsl_executable", lambda _p="": None)
    with pytest.raises(FileNotFoundError, match="Settings → WSL"):
        wsl_argv(["uname", "-s"])


def test_wsl_argv_inserts_distro(monkeypatch, tmp_path) -> None:
    exe = tmp_path / "wsl.exe"
    exe.write_text("", encoding="utf-8")
    monkeypatch.setattr("molmanager.wsl.resolve_wsl_executable", lambda _p="": str(exe))
    argv = wsl_argv(["antechamber", "-i", "lig.mol2"], distro="Ubuntu")
    assert argv[:4] == [str(exe), "-d", "Ubuntu", "--"]
    assert argv[4:] == ["antechamber", "-i", "lig.mol2"]


def test_default_wsl_executable_non_windows(monkeypatch) -> None:
    monkeypatch.setattr("molmanager.wsl.sys.platform", "linux")
    assert default_wsl_executable() == ""


def test_wsl_settings_dialog_saves_path(qapp, monkeypatch, tmp_path):  # noqa: ARG001
    from PyQt5.QtWidgets import QDialogButtonBox

    from molmanager.ui.dialogs.wsl_settings import WslSettingsDialog

    saved: dict[str, str] = {}
    monkeypatch.setattr("molmanager.ui.dialogs.wsl_settings.load_wsl_executable", lambda: "")
    monkeypatch.setattr(
        "molmanager.ui.dialogs.wsl_settings.save_wsl_executable",
        lambda path: saved.setdefault("path", path) or path,
    )
    dlg = WslSettingsDialog()
    box = dlg.findChild(QDialogButtonBox)
    assert box is not None
    assert box.button(QDialogButtonBox.Ok) is not None
    assert box.button(QDialogButtonBox.Cancel) is None
    dlg.path_edit.setText(str(tmp_path / "wsl.exe"))
    dlg.accept()
    assert saved["path"].endswith("wsl.exe")
    dlg.close()


def test_settings_menu_has_wsl(qapp) -> None:  # noqa: ARG001
    from molmanager.ui.main_window import ChemicalTableApp

    w = ChemicalTableApp()
    mb = w.menuBar()
    settings = next(a.menu() for a in mb.actions() if a.text().replace("&", "") == "Settings")
    labels = [a.text().replace("&", "") for a in settings.actions() if not a.isSeparator()]
    assert "WSL…" in labels
    assert labels.index("WSL…") > labels.index("Hotkeys…")
    w.close()
