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

"""The surface an embedded plot draws on: a WebEngine view, or a notice where none can exist."""

from __future__ import annotations

from contextlib import suppress

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import QLabel, QSizePolicy, QWidget

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
    from PyQt5.QtWebEngineWidgets import QWebEngineView

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


def teardown_plot_web_view(view: QWidget | None) -> None:
    """Stop loads and drop page content so Chromium destroy is cheaper later."""
    if view is None:
        return
    try:
        from PyQt5.QtWebEngineWidgets import QWebEngineView
    except ImportError:
        return
    if not isinstance(view, QWebEngineView):
        return
    with suppress(RuntimeError, TypeError):
        view.stop()
    with suppress(RuntimeError, TypeError):
        view.loadFinished.disconnect()
    page = None
    with suppress(RuntimeError, AttributeError):
        page = view.page()
    if page is not None:
        with suppress(RuntimeError, TypeError):
            page.setWebChannel(None)
    with suppress(RuntimeError, TypeError):
        view.setHtml("")


def teardown_webengine_views_in(widget: QWidget | None) -> None:
    """Blank every ``QWebEngineView`` owned by ``widget``."""
    if widget is None:
        return
    views: list[QWidget] = []
    for attr in ("web", "_web"):
        candidate = getattr(widget, attr, None)
        if candidate is not None:
            views.append(candidate)
    try:
        from PyQt5.QtWebEngineWidgets import QWebEngineView
    except ImportError:
        QWebEngineView = None
    if QWebEngineView is not None:
        with suppress(RuntimeError):
            views.extend(widget.findChildren(QWebEngineView))
    seen: set[int] = set()
    for view in views:
        key = id(view)
        if key in seen:
            continue
        seen.add(key)
        teardown_plot_web_view(view)
    if hasattr(widget, "_web_ready"):
        with suppress(Exception):
            widget._web_ready = False
    if getattr(widget, "_pending_payload_json", None) is not None:
        with suppress(Exception):
            widget._pending_payload_json = None


def schedule_webengine_widget_delete(widget: QWidget | None) -> None:
    """Hide ``widget`` now; blank WebEngine views and deleteLater on the next tick."""
    if widget is None:
        return
    with suppress(RuntimeError):
        widget.hide()
    with suppress(RuntimeError):
        widget.setParent(None)

    def _delete() -> None:
        teardown_webengine_views_in(widget)
        with suppress(RuntimeError):
            widget.deleteLater()

    QTimer.singleShot(0, _delete)
