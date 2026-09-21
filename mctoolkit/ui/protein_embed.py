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


"""WebEngine host for the protein Mol* Viewer canvas."""

from __future__ import annotations


import json
import logging
import shutil
from contextlib import suppress
from pathlib import Path

from PySide6.QtCore import (
    QEvent,
    QEventLoop,
    QObject,
    QTemporaryDir,
    QTimer,
    QUrl,
    Qt,
    Signal,
    Slot,
)
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QLabel, QSizePolicy, QVBoxLayout, QWidget

from ..platform_support.qt_webengine_flags import (
    prepare_embedded_webengine_view,
    webengine_views_supported,
)
from ..workers.process_pool_utils import application_is_shutting_down
from .mol_3d_html import _wire_webengine_console_logger
from .protein_viewer_html import (
    MOLSTAR_CDN_CSS,
    bundled_molstar_available,
    build_protein_viewer_html,
    molstar_static_css,
    molstar_static_js,
)

logger = logging.getLogger(__name__)


class _ProteinViewerBridge(QObject):
    atom_picked = Signal(str)
    delete_requested = Signal()
    undo_requested = Signal()
    redo_requested = Signal()

    @Slot(str)
    def atomPicked(self, payload: str) -> None:
        self.atom_picked.emit(payload)

    @Slot()
    def deleteRequested(self) -> None:
        self.delete_requested.emit()

    @Slot()
    def undoRequested(self) -> None:
        self.undo_requested.emit()

    @Slot()
    def redoRequested(self) -> None:
        self.redo_requested.emit()


class ProteinEmbedView(QWidget):
    """WebEngine host for the protein Mol* Viewer canvas."""

    atom_picked = Signal(str)
    delete_requested = Signal()
    undo_requested = Signal()
    redo_requested = Signal()
    web_ready = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setMinimumWidth(360)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._viewer_tmp: QTemporaryDir | None = None
        self._web_ready = False
        self._pending: list[tuple[str, object]] = []
        self._web = None
        self._web_channel = None
        self._bootstrapped = False
        self._web_shutdown = False
        self._retired_tmps: list[QTemporaryDir] = []
        self._bridge = _ProteinViewerBridge(self)
        self._bridge.atom_picked.connect(self.atom_picked.emit)
        self._bridge.delete_requested.connect(self.delete_requested.emit)
        self._bridge.undo_requested.connect(self.undo_requested.emit)
        self._bridge.redo_requested.connect(self.redo_requested.emit)
        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.setInterval(50)
        self._resize_timer.timeout.connect(self.resize_keep_view)
        self._quiet_resize_ms = 0
        self._status = QLabel("Open a PDB, mmCIF, or other structure file.", self)
        self._status.setAlignment(Qt.AlignCenter)
        self._status.setWordWrap(True)
        self._status.setStyleSheet("color: palette(mid); padding: 16px;")
        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(0, 0, 0, 0)
        self._root.setSpacing(0)
        self._root.addWidget(self._status)

    def prepare_to_show(self) -> None:
        """Allow ``_ensure_web`` after ``shutdown_web`` (close/reopen of the host dialog)."""
        if application_is_shutting_down():
            return
        self._web_shutdown = False

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self.prepare_to_show()
        if not self._bootstrapped:
            QTimer.singleShot(0, self._ensure_web)
        self.schedule_resize_keep_view()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if self._web_ready:
            self.schedule_resize_keep_view()

    def schedule_resize_keep_view(self) -> None:
        interval = max(50, int(getattr(self, "_quiet_resize_ms", 0) or 0))
        self._resize_timer.setInterval(interval)
        self._resize_timer.start()

    def resize_keep_view(self) -> None:
        self._quiet_resize_ms = 0
        self._resize_timer.setInterval(50)
        if self._web is None or not self._web_ready:
            return
        try:
            self._web.page().runJavaScript(
                "if (window.mctoolkitResizeKeepView) window.mctoolkitResizeKeepView();"
            )
        except Exception:
            logger.debug("Protein viewer resize-keep-view failed", exc_info=True)

    def shutdown_web(self) -> None:
        """Destroy the Chromium view so a later show() can create a fresh one.

        Closing a parented ``QDialog`` on Windows tears down the native window while
        ``QWebEngineView`` is still attached; showing that same view again aborts.
        """
        self._web_shutdown = True
        self._resize_timer.stop()
        self._web_ready = False
        self._bootstrapped = False
        web = self._web
        channel = self._web_channel
        self._web = None
        self._web_channel = None
        tmp = self._viewer_tmp
        self._viewer_tmp = None
        if web is None:
            if tmp is not None:
                self._retired_tmps.append(tmp)
            return
        with suppress(TypeError, RuntimeError):
            web.loadFinished.disconnect(self._on_load_finished)
        with suppress(RuntimeError):
            web.removeEventFilter(self)
        try:
            page = web.page()
            if page is not None:
                if channel is not None:
                    page.setWebChannel(None)
                page.setUrl(QUrl("about:blank"))
        except RuntimeError:
            pass
        if tmp is not None:
            self._retired_tmps.append(tmp)
            try:
                web.destroyed.connect(
                    lambda *_a, t=tmp, holder=self: holder._release_retired_tmp(t)
                )
            except RuntimeError:
                self._release_retired_tmp(tmp)
        try:
            self._root.removeWidget(web)
            web.hide()
            web.setParent(None)
            web.deleteLater()
        except RuntimeError:
            pass
        with suppress(RuntimeError):
            self._status.show()

    def _release_retired_tmp(self, tmp: QTemporaryDir) -> None:
        with suppress(ValueError):
            self._retired_tmps.remove(tmp)

    def _ensure_web(self) -> None:
        if self._bootstrapped or self._web_shutdown:
            return
        if application_is_shutting_down() or not webengine_views_supported():
            return
        self._bootstrapped = True
        try:
            from PySide6.QtWebChannel import QWebChannel
            from PySide6.QtWebEngineCore import QWebEngineSettings
            from PySide6.QtWebEngineWidgets import QWebEngineView

            web = QWebEngineView(self)
            if self._discard_web_if_shutdown(web):
                return
            prepare_embedded_webengine_view(web)
            web.setFocusPolicy(Qt.StrongFocus)
            web.setContextMenuPolicy(Qt.NoContextMenu)
            web.installEventFilter(self)
            _wire_webengine_console_logger(web)
            try:
                s = web.settings()
                s.setAttribute(QWebEngineSettings.LocalContentCanAccessRemoteUrls, True)
                s.setAttribute(QWebEngineSettings.JavascriptEnabled, True)
                s.setAttribute(QWebEngineSettings.LocalContentCanAccessFileUrls, True)
            except Exception:
                pass
            channel = QWebChannel(web.page())
            channel.registerObject("proteinBridge", self._bridge)
            web.page().setWebChannel(channel)
            self._web_channel = channel
            web.loadFinished.connect(self._on_load_finished)
            if bundled_molstar_available():
                self._viewer_tmp = QTemporaryDir()
                if not self._viewer_tmp.isValid():
                    raise OSError("Could not create a temporary directory for the 3D viewer.")
                tmp = Path(self._viewer_tmp.path())
                shutil.copy2(molstar_static_js(), tmp / "molstar.js")
                shutil.copy2(molstar_static_css(), tmp / "molstar.css")
                index = tmp / "index.html"
                index.write_text(build_protein_viewer_html(), encoding="utf-8")
                web.load(QUrl.fromLocalFile(str(index.resolve())))
            else:
                web.setHtml(build_protein_viewer_html(), QUrl(MOLSTAR_CDN_CSS))
            if self._discard_web_if_shutdown(web):
                return
            self._web = web
            proxy = web.focusProxy()
            if proxy is not None:
                proxy.installEventFilter(self)
            self._status.hide()
            self._root.addWidget(web, 1)
        except Exception as e:
            self._bootstrapped = False
            self._web = None
            self._web_channel = None
            logger.warning("Protein 3D view unavailable: %s", e, exc_info=True)
            self._status.setText(
                "3D view unavailable.\nInstall matching PySide6 and restart with "
                "`python -m mctoolkit`."
            )

    def _discard_web_if_shutdown(self, web) -> bool:
        if not self._web_shutdown and not application_is_shutting_down():
            return False
        tmp = self._viewer_tmp
        self._viewer_tmp = None
        if tmp is not None:
            self._retired_tmps.append(tmp)
            try:
                web.destroyed.connect(
                    lambda *_a, t=tmp, holder=self: holder._release_retired_tmp(t)
                )
            except RuntimeError:
                self._release_retired_tmp(tmp)
        with suppress(RuntimeError):
            web.setParent(None)
            web.deleteLater()
        self._bootstrapped = False
        self._web_channel = None
        return True

    def eventFilter(self, obj, event):  # noqa: N802
        """Keep Delete / Undo available when the WebEngine canvas has focus."""
        if event is not None and event.type() == QEvent.KeyPress:
            if self._emit_canvas_edit_key(event):
                return True
        return super().eventFilter(obj, event)

    def _emit_canvas_edit_key(self, event) -> bool:
        key = event.key()
        if key in (Qt.Key_Delete, Qt.Key_Backspace):
            self.delete_requested.emit()
            return True
        try:
            if event.matches(QKeySequence.Undo):
                self.undo_requested.emit()
                return True
            if event.matches(QKeySequence.Redo):
                self.redo_requested.emit()
                return True
        except Exception:
            return False
        return False

    def _on_load_finished(self, ok: bool) -> None:
        self._web_ready = bool(ok)
        pending = list(self._pending)
        self._pending.clear()
        for fn_name, payload in pending:
            self._eval_js(fn_name, payload)
        if self._web_ready:
            self.schedule_resize_keep_view()
            QTimer.singleShot(200, self.resize_keep_view)
        self.web_ready.emit()

    def _run_js(self, fn_name: str, payload) -> None:
        if self._web is None or not self._web_ready:
            self._pending.append((fn_name, payload))
            return
        self._eval_js(fn_name, payload)

    def _eval_js(self, fn_name: str, payload) -> None:
        if payload is None:
            js = f"if (window.{fn_name}) window.{fn_name}();"
        else:
            js = f"if (window.{fn_name}) window.{fn_name}({json.dumps(payload)});"
        try:
            self._web.page().runJavaScript(js)
        except Exception:
            logger.debug("Protein viewer %s failed", fn_name, exc_info=True)

    def load_structures(self, payload: dict) -> None:
        self._quiet_resize_ms = 180
        body = dict(payload or {})
        body.setdefault("replace", True)
        self._run_js("mctoolkitLoadStructures", body)

    def add_structures(self, payload: dict) -> None:
        self._quiet_resize_ms = 180
        body = dict(payload or {})
        body["replace"] = False
        self._run_js("mctoolkitLoadStructures", body)

    def clear_structures(self) -> None:
        self._run_js("mctoolkitClearStructures", None)

    def set_payload(self, payload: dict) -> None:
        """Replace the canvas from a models payload (session / full rebuild)."""
        self.load_structures(payload)

    def add_models(self, payload: dict) -> None:
        """Append models without clearing already loaded structures."""
        self.add_structures(payload)

    def apply_component_states(self, components: list[dict]) -> None:
        return

    def delete_components(self, ids: list[str]) -> None:
        return

    def zoom_to_components(self, ids: list[str]) -> None:
        return

    def set_residue_highlight(self, selections: list[dict]) -> None:
        return

    def mutate_residues(self, items: list[dict]) -> None:
        return

    def delete_residues(self, selections: list[dict]) -> None:
        return

    def edit_bond(self, payload: dict) -> None:
        return

    def zoom_to_selections(self, selections: list[dict]) -> None:
        return

    def set_pocket(self, pocket: dict | None) -> None:
        return

    def set_pocket_surface(self, surface: dict | None) -> None:
        return

    def set_hydrogens(self, mode: str) -> None:
        return

    def set_hbonds(self, spec: dict | None) -> None:
        return

    def set_docking_box(self, box: dict | None) -> None:
        self._run_js("mctoolkitSetDockingBox", box or {"active": False})

    def set_dock_pose(self, pose: dict | None) -> None:
        self._run_js("mctoolkitSetDockPose", pose or {"active": False})

    def set_pharmacophore(self, spec: dict | None) -> None:
        self._run_js("mctoolkitSetPharmacophore", spec or {"active": False})

    def load_trajectory(self, spec: dict) -> None:
        self._run_js("mctoolkitLoadTrajectory", spec or {})

    def load_volume(self, spec: dict) -> None:
        self._run_js("mctoolkitLoadVolume", spec or {})

    def load_molj(self, state) -> None:
        if state is None:
            return
        self._run_js("mctoolkitLoadMolj", state)

    def reset_camera(self) -> None:
        self._run_js("mctoolkitResetCamera", None)

    def apply_theme(self, payload: dict | None = None) -> None:
        """Recolor Mol* chrome and the 3D canvas to the live Fusion palette."""
        from .protein_molstar_theme import molstar_theme_payload

        self._run_js(
            "mctoolkitApplyTheme",
            payload if payload is not None else molstar_theme_payload(),
        )

    def set_camera(self, view) -> None:
        return

    def fetch_camera(self, timeout_ms: int = 250):
        return None

    def fetch_molj(self, timeout_ms: int = 400):
        """Return a Mol* snapshot object, or None if the canvas is not ready."""
        if self._web is None or not self._web_ready:
            return None
        loop = QEventLoop()
        box: dict = {"value": None, "done": False}

        def _cb(val) -> None:
            box["value"] = val
            box["done"] = True
            loop.quit()

        try:
            self._web.page().runJavaScript(
                "window.mctoolkitExportMolj ? window.mctoolkitExportMolj() : null",
                _cb,
            )
        except Exception:
            logger.debug("Protein viewer export molj failed", exc_info=True)
            return None
        QTimer.singleShot(max(1, int(timeout_ms)), loop.quit)
        loop.exec()
        return box["value"] if box["done"] else None
