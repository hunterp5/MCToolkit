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

"""Display-name identity, QSettings migration, and session format aliases."""

from __future__ import annotations

from PySide6.QtCore import QSettings

from molmanager.app_identity import (
    APP_DISPLAY_NAME,
    LEGACY_SETTINGS_APP,
    LEGACY_SETTINGS_ORG,
    PREVIOUS_SETTINGS_APP,
    PREVIOUS_SETTINGS_ORG,
    SESSION_INVALID_MESSAGE,
    SESSION_OPEN_FILTER,
    SESSION_SAVE_FILTER,
    SESSION_TEMP_DIR_NAME,
    SETTINGS_APP,
    SETTINGS_ORG,
    http_user_agent,
    qt_settings,
    reset_settings_migration_for_tests,
    window_title,
)
from molmanager.table.session_codec import session_format_ok


def test_display_name_and_window_title() -> None:
    assert APP_DISPLAY_NAME == "MCToolkit"
    assert window_title() == "MCToolkit"
    assert window_title("Help") == "MCToolkit — Help"
    assert PREVIOUS_SETTINGS_ORG == "MCtoolkit"
    assert PREVIOUS_SETTINGS_APP == "MCtoolkit"


def test_http_user_agent_includes_display_name() -> None:
    agent = http_user_agent("FAME3R SOM")
    assert agent.startswith("MCToolkit/")
    assert "FAME3R SOM" in agent


def test_session_format_aliases_include_legacy_and_new_names() -> None:
    assert session_format_ok("molmanager_session")
    assert session_format_ok("chemmanager_session")
    assert session_format_ok("mctoolkit_session")
    assert not session_format_ok("other_session")


def test_session_dialog_filters_use_display_name() -> None:
    assert SESSION_SAVE_FILTER.startswith("MCToolkit Session")
    assert "MCToolkit Session" in SESSION_OPEN_FILTER
    assert "MCToolkit" in SESSION_INVALID_MESSAGE
    assert SESSION_TEMP_DIR_NAME == "MCToolkitSessions"


def test_qt_settings_migrates_legacy_keys(tmp_path, monkeypatch, qapp):  # noqa: ARG001
    import molmanager.app_identity as ident

    new_ini = str(tmp_path / "new.ini")
    old_ini = str(tmp_path / "old.ini")

    def _settings(org, app, *args, **kwargs):
        del args, kwargs
        path = new_ini if org == SETTINGS_ORG and app == SETTINGS_APP else old_ini
        return QSettings(path, QSettings.IniFormat)

    monkeypatch.setattr(ident, "QSettings", _settings)
    reset_settings_migration_for_tests()

    legacy = ident.QSettings(LEGACY_SETTINGS_ORG, LEGACY_SETTINGS_APP)
    legacy.setValue("gui/theme", "dark")
    legacy.sync()

    settings = qt_settings()
    assert str(settings.value("gui/theme")) == "dark"


def test_qt_settings_does_not_overwrite_existing_keys(tmp_path, monkeypatch, qapp):  # noqa: ARG001
    import molmanager.app_identity as ident

    new_ini = str(tmp_path / "new.ini")
    old_ini = str(tmp_path / "old.ini")

    def _settings(org, app, *args, **kwargs):
        del args, kwargs
        path = new_ini if org == SETTINGS_ORG and app == SETTINGS_APP else old_ini
        return QSettings(path, QSettings.IniFormat)

    monkeypatch.setattr(ident, "QSettings", _settings)
    reset_settings_migration_for_tests()

    current = ident.QSettings(SETTINGS_ORG, SETTINGS_APP)
    current.setValue("gui/theme", "light")
    current.sync()
    legacy = ident.QSettings(LEGACY_SETTINGS_ORG, LEGACY_SETTINGS_APP)
    legacy.setValue("gui/theme", "dark")
    legacy.sync()

    settings = qt_settings()
    assert str(settings.value("gui/theme")) == "light"
