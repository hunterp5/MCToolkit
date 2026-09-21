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

"""Keep native window captions on the PyQt5 / Windows 10 look.

Qt 6's Windows plugin turns on DWM immersive dark mode (black title bars with
minimize / maximize / close) from the OS color scheme. PyQt5 never set that
            attribute, so mctoolkit captions stayed the classic light Windows frame even
when Fusion was dark. Call ``configure_windows_native_caption_platform`` before
``QApplication`` and ``install_classic_native_captions`` after it exists.
"""

from __future__ import annotations

import os
import sys
from typing import Any

_QT_QPA_PLATFORM = "QT_QPA_PLATFORM"
_HEADLESS_PLUGINS = frozenset({"offscreen", "minimal", "minimalegl", "vnc"})
# Win10 1809 used 19; 1903+ uses 20 (DWMWA_USE_IMMERSIVE_DARK_MODE).
_DWMWA_USE_IMMERSIVE_DARK_MODE = (20, 19)
_FILTER_ATTR = "_mctoolkit_classic_caption_filter"


def configure_windows_native_caption_platform() -> str | None:
    """Disable Qt 6 Windows dark frames. Must run before ``QApplication``.

    Leaves headless plugins (offscreen tests) alone. Returns the platform
    string written, or ``None`` when nothing changed.
    """
    if sys.platform != "win32":
        return None
    current = (os.environ.get(_QT_QPA_PLATFORM) or "").strip()
    plugin, sep, rest = current.partition(":")
    plugin_l = (plugin or "windows").strip().lower()
    if plugin_l in _HEADLESS_PLUGINS:
        return None
    if plugin_l != "windows":
        plugin = "windows"
        rest = current if current and not sep else rest
    options = [part for part in rest.split(":") if part]
    options = [part for part in options if not part.lower().startswith("darkmode=")]
    options.append("darkmode=0")
    value = ":".join([plugin or "windows", *options])
    os.environ[_QT_QPA_PLATFORM] = value
    return value


def existing_native_hwnd(widget: Any) -> int:
    """Return a realized HWND without calling ``winId()``.

    ``QWidget.winId()`` creates native windows and breaks ``QWebEngineView`` in the
    same top-level window (QTBUG-48130).
    """
    if widget is None:
        return 0
    internal = getattr(widget, "internalWinId", None)
    if not callable(internal):
        return 0
    try:
        return int(internal() or 0)
    except (RuntimeError, TypeError, ValueError, AttributeError):
        return 0


def _set_widget_caption_classic(widget: Any) -> None:
    if sys.platform != "win32" or widget is None:
        return
    hwnd = existing_native_hwnd(widget)
    if hwnd == 0:
        return
    try:
        import ctypes

        value = ctypes.c_int(0)
        dwm = ctypes.windll.dwmapi
        for attr in _DWMWA_USE_IMMERSIVE_DARK_MODE:
            dwm.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(value), ctypes.sizeof(value))
    except (OSError, AttributeError, ValueError, TypeError):
        return


def apply_classic_native_captions(app: object | None = None) -> None:
    """Force light Windows title bars on current top-level windows."""
    if sys.platform != "win32":
        return
    if app is None:
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance()
    if app is None:
        return
    try:
        widgets = list(app.topLevelWidgets())
    except (RuntimeError, TypeError, AttributeError):
        return
    for widget in widgets:
        try:
            _set_widget_caption_classic(widget)
        except RuntimeError:
            continue


def install_classic_native_captions(app: object | None = None) -> None:
    """Re-apply classic captions when Qt 6 restyles a native frame."""
    if sys.platform != "win32":
        return
    from PySide6.QtCore import QEvent, QObject
    from PySide6.QtWidgets import QApplication, QWidget

    if app is None:
        app = QApplication.instance()
    if app is None:
        return
    existing = getattr(app, _FILTER_ATTR, None)
    if existing is not None:
        apply_classic_native_captions(app)
        return

    class _ClassicCaptionFilter(QObject):
        def eventFilter(self, obj, event):  # noqa: N802 — Qt API
            et = event.type()
            if et in (QEvent.Show, QEvent.WinIdChange) or et == getattr(
                QEvent, "ThemeChange", None
            ):
                if isinstance(obj, QWidget) and obj.isWindow():
                    _set_widget_caption_classic(obj)
            return False

    filt = _ClassicCaptionFilter(app)
    app.installEventFilter(filt)
    setattr(app, _FILTER_ATTR, filt)
    apply_classic_native_captions(app)
