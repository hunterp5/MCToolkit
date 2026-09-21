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
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with MCToolkit. If not, see <https://www.gnu.org/licenses/>.

"""The surface an embedded plot draws on: a WebEngine view, or a notice where none can exist."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QSizePolicy, QWidget

from ..platform_support.qt_webengine_flags import webengine_views_supported

_NO_WEB_MESSAGE = (
    "Interactive plots need a windowing surface, which this platform plugin does not provide."
)


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
