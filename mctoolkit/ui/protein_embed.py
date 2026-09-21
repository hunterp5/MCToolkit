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


"""WebEngine host for the protein 3Dmol canvas."""

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

from ..platform_support.qt_webengine_flags import webengine_views_supported
from ..workers.process_pool_utils import application_is_shutting_down
from .mol_3d_html import _BUNDLED_3DMOL, _wire_webengine_console_logger, bundled_3dmol_available
from .protein_viewer_html import build_protein_viewer_html

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
    """WebEngine host for the protein 3Dmol canvas."""

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
        self._pending_payload: dict | None = None
        self._pending_residue_highlight: list | None = None
        self._pending_pocket: dict | None = None
        self._pending_pocket_surface: dict | None = None
        self._pending_hydrogens: str | None = None
        self._pending_hbonds: dict | None = None
        self._pending_docking_box: dict | None = None
        self._pending_dock_pose: dict | None = None
        self._pending_pharmacophore: dict | None = None
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
        # A queued show event can land here after close started. Building a WebEngine
        # view against a dying native window crashes Chromium.
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
            if bundled_3dmol_available():
                self._viewer_tmp = QTemporaryDir()
                if not self._viewer_tmp.isValid():
                    raise OSError("Could not create a temporary directory for the 3D viewer.")
                tmp = Path(self._viewer_tmp.path())
                shutil.copy2(_BUNDLED_3DMOL, tmp / "3Dmol-min.js")
                index = tmp / "index.html"
                index.write_text(build_protein_viewer_html(), encoding="utf-8")
                web.load(QUrl.fromLocalFile(str(index.resolve())))
            else:
                web.setHtml(build_protein_viewer_html(), QUrl("https://3dmol.org/"))
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
        if self._web_ready and self._pending_payload is not None:
            payload = self._pending_payload
            self._pending_payload = None
            self._pending_hydrogens = None
            self._pending_hbonds = None
            if payload.get("dockPose") is not None:
                self._pending_dock_pose = None
            self._run_js("mctoolkitSetProteinPayload", payload)
        elif self._web_ready and self._pending_residue_highlight is not None:
            highlight = self._pending_residue_highlight
            self._pending_residue_highlight = None
            self._run_js("mctoolkitSetResidueHighlight", highlight)
        if self._web_ready and self._pending_pocket is not None and self._pending_payload is None:
            pocket = self._pending_pocket
            self._pending_pocket = None
            self._run_js("mctoolkitSetPocket", pocket)
        if (
            self._web_ready
            and self._pending_pocket_surface is not None
            and self._pending_payload is None
        ):
            surface = self._pending_pocket_surface
            self._pending_pocket_surface = None
            self._run_js("mctoolkitSetPocketSurface", surface)
        if self._web_ready and self._pending_hydrogens is not None:
            mode = self._pending_hydrogens
            self._pending_hydrogens = None
            self._run_js("mctoolkitSetHydrogens", mode)
        if self._web_ready and self._pending_hbonds is not None and self._pending_payload is None:
            hbonds = self._pending_hbonds
            self._pending_hbonds = None
            self._run_js("mctoolkitSetHbonds", hbonds)
        if (
            self._web_ready
            and self._pending_docking_box is not None
            and self._pending_payload is None
        ):
            box = self._pending_docking_box
            self._pending_docking_box = None
            self._run_js("mctoolkitSetDockingBox", box)
        if (
            self._web_ready
            and self._pending_dock_pose is not None
            and self._pending_payload is None
        ):
            pose = self._pending_dock_pose
            self._pending_dock_pose = None
            self._run_js("mctoolkitSetDockPose", pose)
        if (
            self._web_ready
            and self._pending_pharmacophore is not None
            and self._pending_payload is None
        ):
            pharma = self._pending_pharmacophore
            self._pending_pharmacophore = None
            self._run_js("mctoolkitSetPharmacophore", pharma)
        if self._web_ready:
            self.schedule_resize_keep_view()
            QTimer.singleShot(200, self.resize_keep_view)
        self.web_ready.emit()

    def _run_js(self, fn_name: str, payload) -> None:
        if self._web is None or not self._web_ready:
            if fn_name == "mctoolkitSetProteinPayload":
                self._pending_payload = payload
            elif fn_name == "mctoolkitAddProteinModels":
                if self._pending_payload is None:
                    self._pending_payload = dict(payload)
                    self._pending_payload.setdefault("models", list(payload.get("models") or []))
                else:
                    existing = list(self._pending_payload.get("models") or [])
                    existing.extend(payload.get("models") or [])
                    self._pending_payload["models"] = existing
                    for key in (
                        "components",
                        "residueHighlight",
                        "pocket",
                        "pocketSurface",
                        "hbonds",
                        "dockingBox",
                        "dockPose",
                        "pharmacophore",
                        "hydrogens",
                        "refit",
                    ):
                        if key in payload:
                            self._pending_payload[key] = payload[key]
            elif fn_name == "mctoolkitApplyComponentStates" and self._pending_payload is not None:
                self._pending_payload["components"] = payload
            elif fn_name == "mctoolkitDeleteComponents" and self._pending_payload is not None:
                drop = set(payload or [])
                self._pending_payload["components"] = [
                    comp
                    for comp in self._pending_payload.get("components") or []
                    if comp.get("id") not in drop
                ]
            elif fn_name == "mctoolkitSetResidueHighlight":
                self._pending_residue_highlight = payload
                if self._pending_payload is not None:
                    self._pending_payload["residueHighlight"] = payload
            elif fn_name == "mctoolkitSetPocket":
                self._pending_pocket = payload
                if self._pending_payload is not None:
                    self._pending_payload["pocket"] = payload
            elif fn_name == "mctoolkitSetPocketSurface":
                self._pending_pocket_surface = payload
                if self._pending_payload is not None:
                    self._pending_payload["pocketSurface"] = payload
            elif fn_name == "mctoolkitSetHydrogens":
                self._pending_hydrogens = payload
                if self._pending_payload is not None:
                    self._pending_payload["hydrogens"] = payload
            elif fn_name == "mctoolkitSetHbonds":
                self._pending_hbonds = payload
                if self._pending_payload is not None:
                    self._pending_payload["hbonds"] = payload
            elif fn_name == "mctoolkitSetDockingBox":
                self._pending_docking_box = payload
                if self._pending_payload is not None:
                    self._pending_payload["dockingBox"] = payload
            elif fn_name == "mctoolkitSetDockPose":
                self._pending_dock_pose = payload
                if self._pending_payload is not None:
                    self._pending_payload["dockPose"] = payload
            elif fn_name == "mctoolkitSetPharmacophore":
                self._pending_pharmacophore = payload
                if self._pending_payload is not None:
                    self._pending_payload["pharmacophore"] = payload
            elif fn_name == "mctoolkitSetView" and self._pending_payload is not None:
                self._pending_payload["camera"] = payload
            return
        js = f"if (window.{fn_name}) window.{fn_name}({json.dumps(payload)});"
        try:
            self._web.page().runJavaScript(js)
        except Exception:
            logger.debug("Protein viewer %s failed", fn_name, exc_info=True)

    def set_payload(self, payload: dict) -> None:
        self._quiet_resize_ms = 180
        self._run_js("mctoolkitSetProteinPayload", payload)

    def add_models(self, payload: dict) -> None:
        """Add models to the current canvas without re-parsing already loaded files."""
        self._quiet_resize_ms = 180
        self._run_js("mctoolkitAddProteinModels", payload)

    def apply_component_states(self, components: list[dict]) -> None:
        self._run_js("mctoolkitApplyComponentStates", components)

    def delete_components(self, ids: list[str]) -> None:
        self._run_js("mctoolkitDeleteComponents", ids)

    def zoom_to_components(self, ids: list[str]) -> None:
        self._run_js("mctoolkitZoomToComponents", ids)

    def set_residue_highlight(self, selections: list[dict]) -> None:
        self._run_js("mctoolkitSetResidueHighlight", selections)

    def mutate_residues(self, items: list[dict]) -> None:
        self._run_js("mctoolkitMutateResidues", items)

    def delete_residues(self, selections: list[dict]) -> None:
        self._run_js("mctoolkitDeleteResidues", selections)

    def edit_bond(self, payload: dict) -> None:
        self._run_js("mctoolkitEditBond", payload)

    def zoom_to_selections(self, selections: list[dict]) -> None:
        self._run_js("mctoolkitZoomToSelections", selections)

    def set_pocket(self, pocket: dict | None) -> None:
        self._run_js("mctoolkitSetPocket", pocket)

    def set_pocket_surface(self, surface: dict | None) -> None:
        self._run_js("mctoolkitSetPocketSurface", surface or {"active": False})

    def set_hydrogens(self, mode: str) -> None:
        chosen = mode if mode in ("all", "polar", "none") else "polar"
        self._run_js("mctoolkitSetHydrogens", chosen)

    def set_hbonds(self, spec: dict | None) -> None:
        self._run_js("mctoolkitSetHbonds", spec or {"active": False, "bonds": []})

    def set_docking_box(self, box: dict | None) -> None:
        self._run_js("mctoolkitSetDockingBox", box or {"active": False})

    def set_dock_pose(self, pose: dict | None) -> None:
        self._run_js("mctoolkitSetDockPose", pose or {"active": False})

    def set_pharmacophore(self, spec: dict | None) -> None:
        self._run_js("mctoolkitSetPharmacophore", spec or {"active": False})

    def set_camera(self, view) -> None:
        if view is None:
            return
        self._run_js("mctoolkitSetView", view)

    def fetch_camera(self, timeout_ms: int = 250):
        """Return 3Dmol getView() or None if the canvas is not ready."""
        if self._web is None or not self._web_ready:
            pending = getattr(self, "_pending_payload", None) or {}
            camera = pending.get("camera") if isinstance(pending, dict) else None
            return camera
        loop = QEventLoop()
        box: dict = {"value": None, "done": False}

        def _cb(val) -> None:
            box["value"] = val
            box["done"] = True
            loop.quit()

        try:
            self._web.page().runJavaScript(
                "window.mctoolkitGetView ? window.mctoolkitGetView() : null",
                _cb,
            )
        except Exception:
            logger.debug("Protein viewer getView failed", exc_info=True)
            return None
        QTimer.singleShot(max(1, int(timeout_ms)), loop.quit)
        loop.exec()
        return box["value"] if box["done"] else None
