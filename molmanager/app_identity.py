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

"""User-facing application identity (display name, Qt settings, log paths).

The importable Python package remains ``molmanager``. Environment variables stay
``MOLMANAGER_*``. Session files still use ``molmanager_session``.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QSettings

APP_DISPLAY_NAME = "MCToolkit"
APP_ORGANIZATION = "MCToolkit"
SETTINGS_ORG = "MCToolkit"
SETTINGS_APP = "MCToolkit"
LEGACY_SETTINGS_ORG = "MolManager"
LEGACY_SETTINGS_APP = "MolManager"
PREVIOUS_SETTINGS_ORG = "MCtoolkit"
PREVIOUS_SETTINGS_APP = "MCtoolkit"
PYTHON_PACKAGE = "molmanager"
LOG_DIR_NAME = "MCToolkit"
LOG_DIR_SLUG = "mctoolkit"
LOG_FILE_NAME = "mctoolkit.log"
SESSION_TEMP_DIR_NAME = "MCToolkitSessions"
SESSION_SAVE_FILTER = f"{APP_DISPLAY_NAME} Session (*.cms);;JSON (*.json)"
SESSION_OPEN_FILTER = (
    f"{APP_DISPLAY_NAME} Session (*.cms *.json);;Legacy session CSV (*.csv);;All files (*.*)"
)
SESSION_INVALID_MESSAGE = f"Not an {APP_DISPLAY_NAME} session file (expected .cms / version 1–2)."

_settings_migrated = False


def window_title(suffix: str | None = None) -> str:
    """Main-window or dialog title, optionally with an em-dash suffix."""
    text = (suffix or "").strip()
    if not text:
        return APP_DISPLAY_NAME
    return f"{APP_DISPLAY_NAME} — {text}"


def http_user_agent(purpose: str) -> str:
    """User-Agent for outbound HTTP from this desktop app."""
    from . import __version__

    detail = (purpose or "").strip()
    if detail:
        return f"{APP_DISPLAY_NAME}/{__version__} ({detail}; local desktop app)"
    return f"{APP_DISPLAY_NAME}/{__version__} (local desktop app)"


def reset_settings_migration_for_tests() -> None:
    """Allow tests to re-run legacy QSettings migration in-process."""
    global _settings_migrated
    _settings_migrated = False


def qt_settings() -> QSettings:
    """QSettings for the current app identity, migrating older org/app keys once."""
    settings = QSettings(SETTINGS_ORG, SETTINGS_APP)
    _migrate_legacy_qt_settings(settings)
    return settings


def apply_qt_application_identity(app: Any) -> None:
    """Set Qt org/app names and copy legacy settings before other QSettings writes."""
    app.setOrganizationName(APP_ORGANIZATION)
    app.setApplicationName(APP_DISPLAY_NAME)
    display = getattr(app, "setApplicationDisplayName", None)
    if callable(display):
        display(APP_DISPLAY_NAME)
    qt_settings()


def _migrate_legacy_qt_settings(settings: QSettings) -> None:
    """Copy older QSettings stores into MCToolkit when the new store is empty."""
    global _settings_migrated
    if _settings_migrated:
        return
    _settings_migrated = True
    if settings.allKeys():
        return
    for org, app in (
        (PREVIOUS_SETTINGS_ORG, PREVIOUS_SETTINGS_APP),
        (LEGACY_SETTINGS_ORG, LEGACY_SETTINGS_APP),
    ):
        if org == SETTINGS_ORG and app == SETTINGS_APP:
            continue
        legacy = QSettings(org, app)
        keys = legacy.allKeys()
        if not keys:
            continue
        for key in keys:
            settings.setValue(key, legacy.value(key))
        settings.sync()
        return
