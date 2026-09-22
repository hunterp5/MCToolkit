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

"""Qt WebEngine Chromium flag helpers."""

from __future__ import annotations

import pytest

from mctoolkit.platform_support.qt_webengine_flags import (
    configure_qtwebengine_quiet_logs,
    prepare_embedded_webengine_view,
    set_descendant_webengine_visible,
    webengine_views_supported,
)
from mctoolkit.ui.mol_viewer_3d import _js_console_is_benign


def test_configure_qtwebengine_quiet_logs_sets_log_level(monkeypatch):
    monkeypatch.delenv("QTWEBENGINE_CHROMIUM_FLAGS", raising=False)
    flags = configure_qtwebengine_quiet_logs()
    assert "--log-level=3" in flags
    assert "--default-background-color=ffffffff" in flags
    assert flags == configure_qtwebengine_quiet_logs()


def test_configure_qtwebengine_quiet_logs_keeps_user_log_level(monkeypatch):
    monkeypatch.setenv("QTWEBENGINE_CHROMIUM_FLAGS", "--enable-gpu --log-level=0")
    flags = configure_qtwebengine_quiet_logs()
    assert "--log-level=0" in flags
    assert flags.count("--log-level=") == 1
    assert "--default-background-color=ffffffff" in flags


def test_configure_qtwebengine_quiet_logs_keeps_user_background(monkeypatch):
    monkeypatch.setenv("QTWEBENGINE_CHROMIUM_FLAGS", "--default-background-color=000000ff")
    flags = configure_qtwebengine_quiet_logs()
    assert "--default-background-color=000000ff" in flags
    assert flags.count("--default-background-color=") == 1


def test_startup_does_not_construct_a_webengine_view():
    """Chromium at launch maps extra HWNDs on Windows; keep it off until a plot or 3D view."""
    import ast
    from pathlib import Path

    import mctoolkit.app as app_mod
    from mctoolkit.platform_support import qt_webengine_flags

    source = Path(app_mod.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    calls: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name):
                calls.append(func.id)
            elif isinstance(func, ast.Attribute):
                calls.append(func.attr)
    assert "schedule_qtwebengine_prewarm" not in calls
    assert "prewarm_qtwebengine" not in calls
    assert not hasattr(qt_webengine_flags, "prewarm_qtwebengine")
    assert not hasattr(qt_webengine_flags, "schedule_qtwebengine_prewarm")


def test_prepare_embedded_webengine_view_blocks_ancestor_hwnds(qapp):  # noqa: ARG001
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QWidget

    view = QWidget()
    prepare_embedded_webengine_view(view)
    try:
        assert view.testAttribute(Qt.WA_DontCreateNativeAncestors)
        assert view.autoFillBackground()
    finally:
        view.deleteLater()


def test_set_descendant_webengine_visible_is_noop_offscreen(qapp, monkeypatch):  # noqa: ARG001
    from PySide6.QtWidgets import QWidget

    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    root = QWidget()
    child = QWidget(root)
    try:
        set_descendant_webengine_visible(root, False)
        set_descendant_webengine_visible(root, True)
        assert child.parentWidget() is root
    finally:
        root.deleteLater()


@pytest.mark.parametrize(
    ("plugin", "supported"),
    [
        ("offscreen", False),
        ("minimal", False),
        ("vnc", False),
        ("offscreen:enable_fonts", False),
        ("windows", True),
        ("xcb", True),
        ("", True),
    ],
)
def test_webengine_views_supported_per_platform_plugin(monkeypatch, plugin, supported):
    """Constructing a WebEngine page aborts the process on surface-less plugins."""
    monkeypatch.setenv("QT_QPA_PLATFORM", plugin)
    assert webengine_views_supported() is supported


def test_viewer_skips_webengine_under_offscreen(qapp, monkeypatch):  # noqa: ARG001
    """The 3D viewer must fall back instead of building a page the platform cannot host."""
    from rdkit import Chem

    from mctoolkit.ui.mol_viewer_3d import Molecule3DViewerWidget, prepare_mol_2d

    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    mol = prepare_mol_2d(Chem.MolFromSmiles("CCO"))
    viewer = Molecule3DViewerWidget(mol, None, window_title="View in 2D", flat=True)
    try:
        assert viewer._standalone_web is None
    finally:
        viewer.deleteLater()


def test_interactive_plot_skips_webengine_under_offscreen(qapp, monkeypatch):  # noqa: ARG001
    """The embedded plot must fall back instead of building a page the platform cannot host."""
    from mctoolkit.ui.plotly_interactive_view import PlotlyInteractiveView

    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    view = PlotlyInteractiveView()
    try:
        assert view.web is None
        assert view._web_channel is None
        assert view._web_ready is False
    finally:
        view.deleteLater()


def test_plot_web_host_filter_pokes_shell_after_resize(qapp):
    """Splitter HWND resizes must reach the Plotly shell even without window.resize."""
    from PySide6.QtCore import QSize, Qt
    from PySide6.QtGui import QColor, QResizeEvent
    from PySide6.QtWidgets import QWidget

    from mctoolkit.ui.plot_web_surface import (
        _HOST_RESIZE_JS,
        _PlotWebHostFilter,
        _notify_plot_shell_host_resized,
        _page_of,
        _sync_webengine_page_background,
    )

    class _FakePage:
        def __init__(self) -> None:
            self.js: list[str] = []
            self.bg = None

        def runJavaScript(self, js: str) -> None:
            self.js.append(js)

        def setBackgroundColor(self, color) -> None:
            self.bg = color

    class _FakeView(QWidget):
        def __init__(self) -> None:
            super().__init__()
            self._page = _FakePage()

        def page(self):
            return self._page

    plain = QWidget()
    view = _FakeView()
    filt = _PlotWebHostFilter(view)
    try:
        assert _page_of(plain) is None
        _sync_webengine_page_background(view)
        assert view._page.bg == QColor(Qt.white)
        _notify_plot_shell_host_resized(view)
        assert view._page.js == [_HOST_RESIZE_JS]
        view._page.js.clear()
        filt.eventFilter(view, QResizeEvent(QSize(320, 240), QSize(100, 100)))
        assert filt._resize_timer.isActive()
        qapp.processEvents()
        qapp.processEvents()
        assert view._page.js == [_HOST_RESIZE_JS]
    finally:
        plain.deleteLater()
        view.deleteLater()


def test_plot_web_load_finished_reapplies_page_background(qapp):  # noqa: ARG001
    """Loading the Plotly shell must not leave Chromium's page fill transparent/black."""
    from PySide6.QtCore import Qt, Signal
    from PySide6.QtGui import QColor
    from PySide6.QtWidgets import QWidget

    from mctoolkit.ui.plot_web_surface import _wire_plot_web_lifecycle

    class _FakePage:
        def __init__(self) -> None:
            self.bg = None

        def setBackgroundColor(self, color) -> None:
            self.bg = color

        def runJavaScript(self, _js: str) -> None:
            return None

    class _FakeView(QWidget):
        loadFinished = Signal(bool)

        def __init__(self) -> None:
            super().__init__()
            self._page = _FakePage()

        def page(self):
            return self._page

    view = _FakeView()
    try:
        _wire_plot_web_lifecycle(view)
        assert view._page.bg == QColor(Qt.white)
        view._page.bg = None
        view.loadFinished.emit(True)
        assert view._page.bg == QColor(Qt.white)
    finally:
        view.deleteLater()


def test_freeze_web_view_hides_hwnd_behind_scaled_cover(qapp):
    """Splitter drag must unmap Chromium; Fusion scales the last frame in the slot."""
    from PySide6.QtCore import QSize
    from PySide6.QtGui import QResizeEvent
    from PySide6.QtWidgets import QVBoxLayout, QWidget

    from mctoolkit.ui.plot_web_surface import (
        _FORCE_HOST_RESIZE_JS,
        _SPLIT_COVER_ATTR,
        _PlotWebHostFilter,
        _freeze_one_web_view,
        _plot_web_cover_rect,
        _thaw_one_web_view,
    )

    class _FakePage:
        def __init__(self) -> None:
            self.js: list[str] = []
            self.bg = None

        def runJavaScript(self, js: str) -> None:
            self.js.append(js)

        def setBackgroundColor(self, color) -> None:
            self.bg = color

    class _FakeView(QWidget):
        def __init__(self, parent=None) -> None:
            super().__init__(parent)
            self._page = _FakePage()

        def page(self):
            return self._page

    parent = QWidget()
    layout = QVBoxLayout(parent)
    layout.setContentsMargins(0, 0, 0, 0)
    child = _FakeView(parent)
    layout.addWidget(child, 1)
    parent.resize(240, 180)
    parent.show()
    qapp.processEvents()
    filt = _PlotWebHostFilter(child)
    child.installEventFilter(filt)
    try:
        _freeze_one_web_view(child)
        cover = getattr(child, _SPLIT_COVER_ATTR)
        assert cover is not None
        assert child.isHidden()
        assert cover.isVisible()
        assert cover.hasScaledContents()
        assert cover.geometry() == _plot_web_cover_rect(child)
        _freeze_one_web_view(child)
        assert getattr(child, _SPLIT_COVER_ATTR) is cover
        # Expanding the pane while Chromium is hidden must grow the cover, not leave gray.
        parent.resize(400, 300)
        qapp.processEvents()
        assert cover.geometry() == _plot_web_cover_rect(child)
        assert cover.width() >= 390
        assert cover.height() >= 290
        filt.eventFilter(child, QResizeEvent(QSize(160, 120), QSize(100, 80)))
        assert cover.geometry() == _plot_web_cover_rect(child)
        child._page.js.clear()
        _thaw_one_web_view(child)
        assert getattr(child, _SPLIT_COVER_ATTR, None) is None
        assert child.isVisible()
        qapp.processEvents()
        assert _FORCE_HOST_RESIZE_JS in child._page.js
        _thaw_one_web_view(child)
    finally:
        parent.deleteLater()


def test_no_module_scope_webengine_imports():
    """WebEngine must only be imported inside functions, behind ``webengine_views_supported``.

    A module-scope import settles WebEngine's initialization order for the whole process, which
    decides whether a later unguarded view construction raises ``ImportError`` or aborts. That is
    what let a plot widget kill the test suite from an unrelated test.
    """
    import ast
    from pathlib import Path

    import mctoolkit

    package_root = Path(mctoolkit.__file__).parent
    offenders: list[str] = []
    for path in sorted(package_root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Import, ast.ImportFrom)) or node.col_offset != 0:
                continue
            names = [alias.name for alias in node.names]
            module = getattr(node, "module", None) or ""
            if "QtWebEngine" in module or any("QtWebEngine" in name for name in names):
                offenders.append(f"{path}:{node.lineno}")
    assert offenders == [], f"import QtWebEngine inside a guarded function instead: {offenders}"


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
