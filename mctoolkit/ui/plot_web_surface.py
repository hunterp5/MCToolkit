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
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QLabel, QSizePolicy, QWidget

from ..platform_support.qt_webengine_flags import (
    embedded_webengine_views,
    prepare_embedded_webengine_view,
    webengine_views_supported,
)

_NO_WEB_MESSAGE = (
    "Interactive plots need a windowing surface, which this platform plugin does not provide."
)
_HOST_RESIZE_JS = "window.mctoolkitOnHostResize && window.mctoolkitOnHostResize();"
_FORCE_HOST_RESIZE_JS = (
    "window.mctoolkitForceHostResize && window.mctoolkitForceHostResize();"
)
_SPLIT_COVER_ATTR = "_mctoolkit_split_cover"
_SPLIT_PARENT_FILTER_ATTR = "_mctoolkit_split_parent_filter"
_SPLIT_RETAIN_PROP = "mctoolkit_split_retain_hidden"
_SPLIT_THAW_MS = 80


def _page_of(view):
    page = getattr(view, "page", None)
    if not callable(page):
        return None
    try:
        return page()
    except RuntimeError:
        return None


def _sync_webengine_page_background(view) -> None:
    """Fill Chromium's unpainted pixels with opaque white instead of compositor black."""
    page = _page_of(view)
    if page is None:
        return
    from PySide6.QtGui import QColor

    with suppress(RuntimeError):
        page.setBackgroundColor(QColor(Qt.white))


def _notify_plot_shell_host_resized(view) -> None:
    page = _page_of(view)
    if page is None:
        return
    with suppress(RuntimeError):
        page.runJavaScript(_HOST_RESIZE_JS)


def _force_plot_shell_host_resized(view) -> None:
    """Invalidate shell size cache and resize Plotly after Chromium remaps."""
    page = _page_of(view)
    if page is None:
        return
    with suppress(RuntimeError):
        page.runJavaScript(_FORCE_HOST_RESIZE_JS)


def _plot_web_cover_rect(view: QWidget):
    """Fill the plot web slot while hidden; retainSizeWhenHidden stops layout from growing *view*."""
    from PySide6.QtCore import QRect

    parent = view.parentWidget()
    if parent is None:
        return view.geometry()
    anchor = view.geometry().topLeft()
    inner = parent.contentsRect()
    return QRect(
        anchor.x(),
        anchor.y(),
        max(0, inner.width() - anchor.x()),
        max(0, inner.height() - anchor.y()),
    )


def _sync_split_cover(view: QWidget) -> None:
    cover = getattr(view, _SPLIT_COVER_ATTR, None)
    if cover is None:
        return
    with suppress(RuntimeError):
        cover.setGeometry(_plot_web_cover_rect(view))


class _SplitCoverParentFilter(QObject):
    """Parent grows during splitter expand; hidden web views may not get QEvent.Resize."""

    def __init__(self, view: QWidget) -> None:
        super().__init__(view)
        self._view = view

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 — Qt API
        if event.type() == QEvent.Resize and obj is self._view.parentWidget():
            _sync_split_cover(self._view)
        return False


def _freeze_one_web_view(view: QWidget) -> None:
    """Unmap Chromium; show a Qt-scaled snapshot while the splitter handle moves."""
    if getattr(view, _SPLIT_COVER_ATTR, None) is not None:
        return
    parent = view.parentWidget()
    if parent is None:
        return
    pix = None
    with suppress(RuntimeError):
        pix = view.grab()
    cover = QLabel(parent)
    cover.setAttribute(Qt.WA_DontCreateNativeAncestors, True)
    cover.setAutoFillBackground(True)
    pal = cover.palette()
    pal.setColor(cover.backgroundRole(), QColor(Qt.white))
    cover.setPalette(pal)
    cover.setAlignment(Qt.AlignLeft | Qt.AlignTop)
    cover.setScaledContents(True)
    if pix is not None and not pix.isNull():
        cover.setPixmap(pix)
    setattr(view, _SPLIT_COVER_ATTR, cover)
    parent_filter = _SplitCoverParentFilter(view)
    parent.installEventFilter(parent_filter)
    setattr(view, _SPLIT_PARENT_FILTER_ATTR, parent_filter)
    policy = view.sizePolicy()
    view.setProperty(_SPLIT_RETAIN_PROP, policy.retainSizeWhenHidden())
    policy.setRetainSizeWhenHidden(True)
    view.setSizePolicy(policy)
    view.hide()
    _sync_split_cover(view)
    cover.show()
    cover.raise_()


def _thaw_one_web_view(view: QWidget) -> None:
    cover = getattr(view, _SPLIT_COVER_ATTR, None)
    if cover is None:
        return
    setattr(view, _SPLIT_COVER_ATTR, None)
    parent_filter = getattr(view, _SPLIT_PARENT_FILTER_ATTR, None)
    parent = view.parentWidget()
    if parent_filter is not None:
        setattr(view, _SPLIT_PARENT_FILTER_ATTR, None)
        if parent is not None:
            with suppress(RuntimeError):
                parent.removeEventFilter(parent_filter)
        parent_filter.deleteLater()
    slot = cover.geometry()
    policy = view.sizePolicy()
    retain = view.property(_SPLIT_RETAIN_PROP)
    if retain is not None:
        policy.setRetainSizeWhenHidden(bool(retain))
        view.setSizePolicy(policy)
    with suppress(RuntimeError):
        view.show()
        view.setGeometry(slot)
        if parent is not None:
            layout = parent.layout()
            if layout is not None:
                layout.activate()
            parent.updateGeometry()
        _sync_webengine_page_background(view)
        view.update()
        cover.raise_()

    def _poke_plotly() -> None:
        _force_plot_shell_host_resized(view)
        with suppress(RuntimeError):
            view.update()

    def _drop_cover() -> None:
        with suppress(RuntimeError):
            cover.hide()
            cover.deleteLater()
        _poke_plotly()

    # Immediate onHostResize early-outs on the pre-drag size; wait for HWND map.
    QTimer.singleShot(0, _poke_plotly)
    QTimer.singleShot(_SPLIT_THAW_MS, _drop_cover)
    QTimer.singleShot(_SPLIT_THAW_MS + 64, _poke_plotly)


def freeze_webengine_for_splitter_drag(root: QWidget) -> None:
    """Snapshot and unmap plot WebEngine views under *root* for a live splitter drag."""
    for view in embedded_webengine_views(root):
        _freeze_one_web_view(view)


def thaw_webengine_after_splitter_drag(root: QWidget) -> None:
    """Remap plot WebEngine views after the splitter handle is released."""
    for view in embedded_webengine_views(root):
        _thaw_one_web_view(view)


def _wire_plot_web_lifecycle(view) -> None:
    """Keep Chromium's page fill opaque across load and HWND resize."""
    _sync_webengine_page_background(view)
    load_finished = getattr(view, "loadFinished", None)
    if load_finished is not None:
        with suppress(RuntimeError, TypeError):
            load_finished.connect(lambda _ok, v=view: _sync_webengine_page_background(v))
    view.installEventFilter(_PlotWebHostFilter(view))


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
        if getattr(self._view, _SPLIT_COVER_ATTR, None) is not None:
            return
        _notify_plot_shell_host_resized(self._view)
        with suppress(RuntimeError):
            self._view.update()

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 — Qt API
        et = event.type()
        if et == QEvent.Resize:
            if getattr(self._view, _SPLIT_COVER_ATTR, None) is not None:
                _sync_split_cover(self._view)
                return False
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
    _wire_plot_web_lifecycle(web)
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
