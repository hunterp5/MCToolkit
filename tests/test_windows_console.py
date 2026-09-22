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

"""GUI launcher must not allocate a second console window on Windows."""

from __future__ import annotations

from pathlib import Path

from mctoolkit.platform_support.windows_console import (
    ensure_stdio,
    hide_owned_windows_console,
)


def test_pyproject_launches_mctoolkit_as_gui_script() -> None:
    text = Path("pyproject.toml").read_text(encoding="utf-8")
    assert "[project.gui-scripts]" in text
    assert "[project.scripts]\nmctoolkit =" not in text
    assert 'mctoolkit = "mctoolkit.app:main"' in text


def test_ensure_stdio_fills_missing_streams(monkeypatch) -> None:
    monkeypatch.setattr("sys.stdout", None)
    monkeypatch.setattr("sys.stderr", None)
    ensure_stdio()
    import sys

    assert sys.stdout is not None
    assert sys.stderr is not None
    sys.stdout.write("ok")
    sys.stderr.write("ok")


def test_hide_owned_console_skips_non_windows(monkeypatch) -> None:
    monkeypatch.setattr("sys.platform", "linux")
    assert hide_owned_windows_console() is False
