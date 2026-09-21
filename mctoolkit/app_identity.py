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

"""User-facing application identity (display name, Qt settings, log paths).

The display name is ``mctoolkit`` (short for medicinal chemistry toolkit).
The importable Python package is ``mctoolkit``. Environment variables are
``MCTOOLKIT_*``. Session files use ``mctoolkit_session`` and the ``.mct``
extension.
"""

from __future__ import annotations

import os
from typing import Any

from PySide6.QtCore import QSettings

APP_DISPLAY_NAME = "mctoolkit"
APP_ORGANIZATION = "mctoolkit"
SETTINGS_ORG = "mctoolkit"
SETTINGS_APP = "mctoolkit"
PREVIOUS_SETTINGS = (
    ("MCToolkit", "MCToolkit"),
    ("MCtoolkit", "MCtoolkit"),
)
PREVIOUS_SETTINGS_ORG = PREVIOUS_SETTINGS[0][0]
PREVIOUS_SETTINGS_APP = PREVIOUS_SETTINGS[0][1]
PYTHON_PACKAGE = "mctoolkit"
LOG_DIR_NAME = "mctoolkit"
LOG_DIR_SLUG = "mctoolkit"
LOG_FILE_NAME = "mctoolkit.log"
SESSION_TEMP_DIR_NAME = "mctoolkit-sessions"
SESSION_FILE_EXTENSION = ".mct"
SESSION_JSON_EXTENSION = ".json"
SESSION_DOCUMENT_EXTENSIONS = (SESSION_FILE_EXTENSION, SESSION_JSON_EXTENSION)
SESSION_SAVE_FILTER = (
    f"{APP_DISPLAY_NAME} Session (*{SESSION_FILE_EXTENSION});;JSON (*{SESSION_JSON_EXTENSION})"
)
SESSION_OPEN_FILTER = (
    f"{APP_DISPLAY_NAME} Session (*{SESSION_FILE_EXTENSION} "
    f"*{SESSION_JSON_EXTENSION});;Legacy session CSV (*.csv);;All files (*.*)"
)
SESSION_INVALID_MESSAGE = (
    f"Not an {APP_DISPLAY_NAME} session file (expected {SESSION_FILE_EXTENSION} / version 1–2)."
)

_settings_migrated = False


def is_session_document_path(path: str) -> bool:
    """True when *path* looks like an mctoolkit session document (not CSV)."""
    low = (path or "").lower()
    return any(low.endswith(ext) for ext in SESSION_DOCUMENT_EXTENSIONS)


def window_title(suffix: str | None = None) -> str:
    """Main-table title, or a dialog title without the application name."""
    text = (suffix or "").strip()
    if not text:
        return APP_DISPLAY_NAME
    return text


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
        # Empty (not unset): Windows/Linux otherwise append " - mctoolkit" to every
        # native caption. The main table sets its own title to APP_DISPLAY_NAME.
        display("")
    qt_settings()


def _named_settings(org: str, app: str) -> QSettings:
    """Org/app store without falling back into other Qt settings locations."""
    store = QSettings(org, app)
    store.setFallbacksEnabled(False)
    return store


def _same_settings_file(left: QSettings, right: QSettings) -> bool:
    """True when two QSettings objects share a path (INI file or Windows registry key)."""
    a = os.path.normcase(os.path.normpath(str(left.fileName() or "")))
    b = os.path.normcase(os.path.normpath(str(right.fileName() or "")))
    return bool(a) and a == b


def _migrate_legacy_qt_settings(settings: QSettings) -> None:
    """Copy older QSettings stores into mctoolkit, then drop those leftover stores.

    Windows registry keys are case-insensitive, so ``MCToolkit`` and ``mctoolkit`` are the
    same hive. Clearing that "legacy" store would wipe the theme and other GUI settings
    on every launch. Compare ``fileName()`` rather than the org/app strings.
    """
    global _settings_migrated
    if _settings_migrated:
        return
    _settings_migrated = True
    if not settings.allKeys():
        for org, app in PREVIOUS_SETTINGS:
            if org == SETTINGS_ORG and app == SETTINGS_APP:
                continue
            legacy = _named_settings(org, app)
            if _same_settings_file(settings, legacy):
                continue
            keys = legacy.allKeys()
            if not keys:
                continue
            for key in keys:
                settings.setValue(key, legacy.value(key))
            settings.sync()
            break
    if not settings.allKeys():
        return
    for org, app in PREVIOUS_SETTINGS:
        if org == SETTINGS_ORG and app == SETTINGS_APP:
            continue
        leftover = _named_settings(org, app)
        if _same_settings_file(settings, leftover):
            continue
        if leftover.allKeys():
            leftover.clear()
            leftover.sync()
