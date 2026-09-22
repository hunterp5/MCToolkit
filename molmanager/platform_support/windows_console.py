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

"""Windows console helpers for the GUI entry point."""

from __future__ import annotations

import os
import sys


def ensure_stdio() -> None:
    """Give logging a stream when ``pythonw`` / gui-scripts left stdout/stderr ``None``."""
    for name in ("stdout", "stderr"):
        if getattr(sys, name, None) is None:
            setattr(sys, name, open(os.devnull, "w", encoding="utf-8", errors="replace"))


def hide_owned_windows_console() -> bool:
    """Hide a console this process allocated (``molmanager.exe``), not an inherited terminal.

    Legacy console ``[project.scripts]`` wrappers open a terminal; ``[project.gui-scripts]``
    avoids that. Double-clicking an old console launcher still opens a terminal and then
    the workspace — two windows. Leave the console alone when the user launched from
    PowerShell, cmd, or an IDE terminal (more than one process is attached).
    """
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        from ctypes import wintypes
    except (ImportError, OSError, AttributeError):
        return False
    kernel32 = ctypes.windll.kernel32
    user32 = ctypes.windll.user32
    hwnd = kernel32.GetConsoleWindow()
    if not hwnd:
        return False
    buf = (wintypes.DWORD * 8)()
    n = int(kernel32.GetConsoleProcessList(ctypes.byref(buf), 8))
    if n != 1:
        return False
    user32.ShowWindow(hwnd, 0)
    kernel32.FreeConsole()
    return True
