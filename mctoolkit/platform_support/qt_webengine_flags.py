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

"""Qt WebEngine / Chromium process flags (must run before WebEngine loads)."""

from __future__ import annotations

import os

_QTWEBENGINE_CHROMIUM_FLAGS_ENV = "QTWEBENGINE_CHROMIUM_FLAGS"
_QUIET_LOG_LEVEL_FLAG = "--log-level=3"
_DEFAULT_BACKGROUND_FLAG = "--default-background-color=ffffffff"

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


def prepare_embedded_webengine_view(view) -> None:
    """Keep Chromium native without promoting Fusion ancestors to HWNDs.

    Qt 6 ``QWebEngineView`` is a child window. If ancestors become native too, the
    table, status strip, and splitter handles paint as unpainted black siblings.
    """
    from PySide6.QtCore import Qt

    view.setAttribute(Qt.WA_DontCreateNativeAncestors, True)
    view.setAutoFillBackground(True)


def _webengine_views_in(root) -> list:
    if root is None or not webengine_views_supported():
        return []
    try:
        from PySide6.QtWebEngineWidgets import QWebEngineView
    except Exception:
        return []
    views: list = []
    try:
        if isinstance(root, QWebEngineView):
            views.append(root)
        views.extend(root.findChildren(QWebEngineView))
    except RuntimeError:
        return []
    seen: set[int] = set()
    unique: list = []
    for view in views:
        key = id(view)
        if key in seen:
            continue
        seen.add(key)
        unique.append(view)
    return unique


def embedded_webengine_views(root) -> list:
    """``QWebEngineView`` widgets under *root*, including *root* when it is a view."""
    return _webengine_views_in(root)


def set_descendant_webengine_visible(root, visible: bool) -> None:
    """Map or unmap Chromium HWNDs. Hiding a Fusion parent leaves them painted."""
    for view in _webengine_views_in(root):
        try:
            view.setVisible(bool(visible))
        except RuntimeError:
            continue


def configure_qtwebengine_quiet_logs() -> str:
    """
    Hide Chromium GPU ERROR spam on stderr (SharedImage / GLES while rotating WebGL).

    Also set an opaque white compositor clear so HWND resize gaps are not black.
    Must run before ``QtWebEngineWidgets`` is imported. Leaves an existing
    ``--log-level=`` or ``--default-background-color=`` value alone.
    """
    current = (os.environ.get(_QTWEBENGINE_CHROMIUM_FLAGS_ENV) or "").strip()
    parts = current.split()
    if not any(part.startswith("--log-level=") for part in parts):
        parts.append(_QUIET_LOG_LEVEL_FLAG)
    if not any(part.startswith("--default-background-color=") for part in parts):
        parts.append(_DEFAULT_BACKGROUND_FLAG)
    flags = " ".join(parts)
    os.environ[_QTWEBENGINE_CHROMIUM_FLAGS_ENV] = flags
    return flags
