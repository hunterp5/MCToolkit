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

"""The surface an embedded plot draws on: a WebEngine view, or a notice where none can exist."""

from __future__ import annotations

from contextlib import suppress

from PySide6.QtCore import QEvent, QObject, Qt, QTimer
from PySide6.QtWidgets import QLabel, QSizePolicy, QWidget

from ..platform_support.qt_webengine_flags import (
    prepare_embedded_webengine_view,
    webengine_views_supported,
)

_NO_WEB_MESSAGE = (
    "Interactive plots need a windowing surface, which this platform plugin does not provide."
)
_HOST_RESIZE_JS = "window.mctoolkitOnHostResize && window.mctoolkitOnHostResize();"


def _page_of(view):
    page = getattr(view, "page", None)
    if not callable(page):
        return None
    try:
        return page()
    except RuntimeError:
        return None


def _sync_webengine_page_background(view) -> None:
    """Fill Chromium's unpainted pixels with Fusion Window instead of black."""
    page = _page_of(view)
    if page is None:
        return
    from PySide6.QtGui import QPalette

    with suppress(RuntimeError):
        page.setBackgroundColor(view.palette().color(QPalette.Window))


def _notify_plot_shell_host_resized(view) -> None:
    page = _page_of(view)
    if page is None:
        return
    with suppress(RuntimeError):
        page.runJavaScript(_HOST_RESIZE_JS)


class _PlotWebHostFilter(QObject):
    """Coalesce HWND resizes into one shell poke per event-loop turn."""

    def __init__(self, view: QWidget) -> None:
        super().__init__(view)
        self._view = view
        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.setInterval(0)
        self._resize_timer.timeout.connect(self._emit_resize)

    def _emit_resize(self) -> None:
        _notify_plot_shell_host_resized(self._view)

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 — Qt API
        et = event.type()
        if et == QEvent.Resize:
            self._resize_timer.start()
        elif et == QEvent.PaletteChange:
            _sync_webengine_page_background(obj)
        return False


def build_plot_web_view(parent: QWidget, *, minimum_height: int) -> QWidget | None:
    """Return a ``QWebEngineView`` parented to *parent*, or ``None`` where Chromium cannot run.

    Under a surfaceless platform plugin (``offscreen``, used by the test suite and CI) building
    a view aborts the process instead of raising, so callers get ``None`` and leave their
    ``_web_ready`` flag false, which already short-circuits every JavaScript path. The
    ``QtWebEngineWidgets`` import stays local on purpose: importing it at module scope settles
    WebEngine's initialization order for the whole process, and that is what turned this abort
    into a crash reachable from unrelated code.
    """
    if not webengine_views_supported():
        return None
    from PySide6.QtWebEngineWidgets import QWebEngineView

    web = QWebEngineView(parent)
    prepare_embedded_webengine_view(web)
    _sync_webengine_page_background(web)
    web.installEventFilter(_PlotWebHostFilter(web))
    web.setMinimumHeight(minimum_height)
    web.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    return web


def no_web_surface(parent: QWidget) -> QWidget:
    """Return the widget that occupies the plot's place when no WebEngine view can be built."""
    label = QLabel(_NO_WEB_MESSAGE, parent)
    label.setAlignment(Qt.AlignCenter)
    label.setWordWrap(True)
    label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    return label
