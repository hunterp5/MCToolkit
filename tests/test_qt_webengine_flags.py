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

"""Qt WebEngine Chromium flag helpers."""

from __future__ import annotations

from molmanager.platform_support.qt_webengine_flags import configure_qtwebengine_quiet_logs
from molmanager.ui.mol_viewer_3d import _js_console_is_benign


def test_configure_qtwebengine_quiet_logs_sets_log_level(monkeypatch):
    monkeypatch.delenv("QTWEBENGINE_CHROMIUM_FLAGS", raising=False)
    flags = configure_qtwebengine_quiet_logs()
    assert "--log-level=3" in flags
    assert flags == configure_qtwebengine_quiet_logs()


def test_configure_qtwebengine_quiet_logs_keeps_user_log_level(monkeypatch):
    monkeypatch.setenv("QTWEBENGINE_CHROMIUM_FLAGS", "--enable-gpu --log-level=0")
    flags = configure_qtwebengine_quiet_logs()
    assert "--log-level=0" in flags
    assert flags.count("--log-level=") == 1


def test_schedule_qtwebengine_prewarm_skips_pytest():
    from molmanager.platform_support import qt_webengine_flags

    qt_webengine_flags.schedule_qtwebengine_prewarm()
    qt_webengine_flags.prewarm_qtwebengine()
    assert qt_webengine_flags._PREWARM_VIEW is None


def test_js_console_filters_shared_image_gpu_noise():
    assert _js_console_is_benign(
        "GL ERROR :GL_INVALID_OPERATION : DoEndSharedImageAccessCHROMIUM: "
        "bound texture is not a shared image"
    )
    assert _js_console_is_benign(
        "SharedImageManager::ProduceGLTexture: Trying to produce a representation "
        "from a non-existent mailbox."
    )
    assert _js_console_is_benign(
        "[Violation] Added non-passive event listener to a scroll-blocking 'wheel' event"
    )
    assert not _js_console_is_benign("Uncaught TypeError: Cannot read property 'x' of undefined")
