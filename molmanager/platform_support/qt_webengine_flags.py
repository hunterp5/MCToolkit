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

"""Qt WebEngine / Chromium process flags (must run before WebEngine loads)."""

from __future__ import annotations

import logging
import os
import sys

logger = logging.getLogger(__name__)

_QTWEBENGINE_CHROMIUM_FLAGS_ENV = "QTWEBENGINE_CHROMIUM_FLAGS"
_QUIET_LOG_LEVEL_FLAG = "--log-level=3"
_PREWARM_VIEW = None

# Chromium needs a real windowing surface. These platform plugins provide none.
_PLATFORMS_WITHOUT_WEBENGINE = frozenset({"offscreen", "minimal", "vnc"})


def webengine_views_supported() -> bool:
    """Whether a ``QWebEngineView`` can be constructed on the current platform plugin.

    Under ``QT_QPA_PLATFORM=offscreen`` (headless tests, CI) constructing one **aborts the
    process** instead of raising, so every lazy WebEngine bootstrap must ask first and take
    its no-web fallback. Without this the behavior depends on whether some earlier import
    pulled in ``QtWebEngineWidgets`` before ``QApplication`` existed.
    """
    plugin = (os.environ.get("QT_QPA_PLATFORM") or "").strip().lower()
    return plugin.split(":")[0] not in _PLATFORMS_WITHOUT_WEBENGINE


def configure_qtwebengine_quiet_logs() -> str:
    """
    Hide Chromium GPU ERROR spam on stderr (SharedImage / GLES while rotating WebGL).

    Must run before ``QtWebEngineWidgets`` is imported. Leaves an existing
    ``--log-level=`` value alone so a user can still raise Chromium verbosity.
    """
    current = (os.environ.get(_QTWEBENGINE_CHROMIUM_FLAGS_ENV) or "").strip()
    parts = current.split()
    if not any(part.startswith("--log-level=") for part in parts):
        parts.append(_QUIET_LOG_LEVEL_FLAG)
    flags = " ".join(parts)
    os.environ[_QTWEBENGINE_CHROMIUM_FLAGS_ENV] = flags
    return flags


def schedule_qtwebengine_prewarm(*, delay_ms: int = 0) -> None:
    """Start Chromium after the first GUI paint so later 3D views do not stall."""
    if "pytest" in sys.modules:
        return
    from PySide6.QtCore import QTimer

    QTimer.singleShot(max(0, int(delay_ms)), prewarm_qtwebengine)


def prewarm_qtwebengine() -> None:
    """Create a hidden WebEngine view so the first protein canvas is not the Chromium cold start."""
    global _PREWARM_VIEW
    if _PREWARM_VIEW is not None or "pytest" in sys.modules:
        return
    try:
        from PySide6.QtCore import Qt
        from PySide6.QtWebEngineWidgets import QWebEngineView
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance()
        if app is None:
            return
        view = QWebEngineView()
        view.setAttribute(Qt.WA_DontShowOnScreen, True)
        view.resize(2, 2)
        view.setHtml("<!DOCTYPE html><html><body></body></html>")
        _PREWARM_VIEW = view
        app.aboutToQuit.connect(_release_qtwebengine_prewarm)
    except Exception:
        logger.debug("Qt WebEngine prewarm skipped", exc_info=True)


def _release_qtwebengine_prewarm() -> None:
    global _PREWARM_VIEW
    view = _PREWARM_VIEW
    _PREWARM_VIEW = None
    if view is None:
        return
    try:
        view.deleteLater()
    except RuntimeError:
        pass
