# This file is part of MCToolkit.
# Copyright (C) 2026 Hunter Picard
#
# MCToolkit is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# MCToolkit is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with MCToolkit.  If not, see <https://www.gnu.org/licenses/>.
"""Application logging setup and uncaught-exception reporting."""

from __future__ import annotations

import logging
import os
import sys
import traceback
from logging.handlers import RotatingFileHandler
from pathlib import Path

from ..app_identity import APP_DISPLAY_NAME, LOG_DIR_NAME, LOG_DIR_SLUG, LOG_FILE_NAME, window_title
from .config import load_config
from .env import env_get
from .session_log import ensure_session_log_handler

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
LOG_DATEFMT = "%Y-%m-%d %H:%M:%S"
_LOG_FILE_NAME = LOG_FILE_NAME

logger = logging.getLogger(__name__)

# Set by configure_app_logging for crash dialogs / support.
_active_log_file: Path | None = None


def active_log_file() -> Path | None:
    """Path to the session log file, if file logging was configured."""
    return _active_log_file


def default_log_dir() -> Path:
    """Platform user-data directory for MCToolkit log files."""
    override = (env_get("MCTOOLKIT_LOG_DIR") or "").strip()
    if override:
        return Path(override).expanduser()
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / LOG_DIR_NAME / "logs"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Logs" / LOG_DIR_NAME
    xdg = (os.environ.get("XDG_STATE_HOME") or "").strip()
    if xdg:
        return Path(xdg) / LOG_DIR_SLUG / "logs"
    return Path.home() / ".local" / "state" / LOG_DIR_SLUG / "logs"


def configure_app_logging() -> Path | None:
    """
    Configure root logging: console always; rotating file under the user log dir.

    Returns the log file path when a file handler was attached, else ``None``.
    Level comes from ``MCTOOLKIT_LOG_LEVEL`` (via ``load_config``).
    Set ``MCTOOLKIT_LOG_TO_FILE=0`` to disable the file handler.
    """
    global _active_log_file
    level_name = load_config().log_level.strip()
    level = getattr(logging, level_name, logging.INFO)
    root = logging.getLogger()
    root.setLevel(level)

    formatter = logging.Formatter(LOG_FORMAT, datefmt=LOG_DATEFMT)
    if not any(
        isinstance(h, logging.StreamHandler) and not isinstance(h, RotatingFileHandler)
        for h in root.handlers
    ):
        console = logging.StreamHandler(sys.stderr)
        console.setFormatter(formatter)
        console.setLevel(level)
        root.addHandler(console)

    log_to_file = (env_get("MCTOOLKIT_LOG_TO_FILE") or "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )
    log_path: Path | None = None
    if log_to_file:
        try:
            log_dir = default_log_dir()
            log_dir.mkdir(parents=True, exist_ok=True)
            log_path = log_dir / _LOG_FILE_NAME
            already = any(
                isinstance(h, RotatingFileHandler)
                and Path(getattr(h, "baseFilename", "")) == log_path
                for h in root.handlers
            )
            if not already:
                file_handler = RotatingFileHandler(
                    log_path,
                    maxBytes=2_000_000,
                    backupCount=5,
                    encoding="utf-8",
                )
                file_handler.setFormatter(formatter)
                file_handler.setLevel(level)
                root.addHandler(file_handler)
            _active_log_file = log_path
        except OSError as exc:
            logger.warning("Could not open log file (%s); continuing with console only", exc)
            log_path = None
            _active_log_file = None
    else:
        _active_log_file = None

    ensure_session_log_handler()
    for handler in root.handlers:
        handler.setLevel(level)
    return log_path


def format_crash_message(exc_type, exc_value, log_path: Path | None) -> str:
    """User-facing crash text including optional log path."""
    detail = f"{getattr(exc_type, '__name__', type(exc_type).__name__)}: {exc_value}"
    lines = [
        f"{APP_DISPLAY_NAME} encountered an unexpected error and may be unstable.",
        "",
        detail,
    ]
    if log_path is not None:
        lines.extend(
            [
                "",
                "Details were written to the log file:",
                str(log_path),
            ]
        )
    return "\n".join(lines)


def install_crash_excepthook(*, log_path: Path | None = None) -> None:
    """Install a ``sys.excepthook`` that logs the traceback and shows a Qt dialog when possible."""
    previous = sys.excepthook
    resolved = log_path if log_path is not None else _active_log_file

    def _hook(exc_type, exc_value, exc_tb) -> None:
        try:
            logging.getLogger("mctoolkit.crash").error(
                "Uncaught exception",
                exc_info=(exc_type, exc_value, exc_tb),
            )
        except Exception:
            pass
        try:
            from PySide6.QtWidgets import QApplication, QMessageBox

            app = QApplication.instance()
            if app is not None:
                QMessageBox.critical(
                    None,
                    window_title("unexpected error"),
                    format_crash_message(exc_type, exc_value, resolved),
                )
        except Exception:
            # Fall back to stderr if Qt is unavailable or dialog creation fails.
            traceback.print_exception(exc_type, exc_value, exc_tb)
        if previous not in (None, sys.__excepthook__):
            try:
                previous(exc_type, exc_value, exc_tb)
            except Exception:
                pass

    sys.excepthook = _hook
