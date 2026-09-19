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

"""Tests for file logging and crash-message helpers."""

from __future__ import annotations

import logging
from pathlib import Path

from molmanager.platform_support.app_logging import (
    active_log_file,
    configure_app_logging,
    default_log_dir,
    format_crash_message,
)


def test_default_log_dir_respects_env(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("MOLMANAGER_LOG_DIR", str(tmp_path / "custom_logs"))
    assert default_log_dir() == tmp_path / "custom_logs"


def test_configure_app_logging_writes_file(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("MOLMANAGER_LOG_DIR", str(tmp_path))
    monkeypatch.setenv("MOLMANAGER_LOG_TO_FILE", "1")
    monkeypatch.setenv("MOLMANAGER_LOG_LEVEL", "INFO")
    # Reset handlers so configure attaches fresh ones in this process.
    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)
        h.close()

    path = configure_app_logging()
    assert path is not None
    assert path == tmp_path / "mctoolkit.log"
    assert active_log_file() == path

    from molmanager.platform_support.session_log import SessionLogHandler, session_log_buffer

    session_log_buffer().clear()
    logging.getLogger("molmanager.platform_support.app_logging.test").info("hello-log")
    for h in root.handlers:
        if hasattr(h, "flush"):
            h.flush()
    text = path.read_text(encoding="utf-8")
    assert "hello-log" in text
    assert any(isinstance(h, SessionLogHandler) for h in root.handlers)
    entries, _seq, _gen = session_log_buffer().snapshot()
    assert any("hello-log" in e.message for e in entries)


def test_configure_app_logging_can_disable_file(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("MOLMANAGER_LOG_DIR", str(tmp_path))
    monkeypatch.setenv("MOLMANAGER_LOG_TO_FILE", "0")
    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)
        h.close()

    path = configure_app_logging()
    assert path is None
    assert active_log_file() is None


def test_format_crash_message_includes_log_path(tmp_path: Path):
    msg = format_crash_message(ValueError, ValueError("boom"), tmp_path / "mctoolkit.log")
    assert "ValueError: boom" in msg
    assert "mctoolkit.log" in msg
    assert "MCToolkit" in msg
