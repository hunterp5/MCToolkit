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


"""WebEngine host for the protein 3Dmol canvas."""

from __future__ import annotations


import json
import logging
import shutil
from pathlib import Path

from PyQt5.QtCore import QObject, QTemporaryDir, QTimer, QUrl, Qt, pyqtSignal, pyqtSlot
from PyQt5.QtWidgets import QLabel, QSizePolicy, QVBoxLayout, QWidget

from .mol_3d_html import _BUNDLED_3DMOL, _wire_webengine_console_logger, bundled_3dmol_available
from .protein_viewer_html import build_protein_viewer_html

logger = logging.getLogger(__name__)


class _ProteinViewerBridge(QObject):
    atom_picked = pyqtSignal(str)

    @pyqtSlot(str)
    def atomPicked(self, payload: str) -> None:
        self.atom_picked.emit(payload)


class ProteinEmbedView(QWidget):
    """WebEngine host for the protein 3Dmol canvas."""

    atom_picked = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setMinimumWidth(360)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._viewer_tmp: QTemporaryDir | None = None
        self._web_ready = False
        self._pending_payload: dict | None = None
        self._pending_residue_highlight: list | None = None
        self._pending_pocket: dict | None = None
        self._pending_hydrogens: str | None = None
        self._pending_hbonds: dict | None = None
        self._web = None
        self._bootstrapped = False
        self._bridge = _ProteinViewerBridge(self)
        self._bridge.atom_picked.connect(self.atom_picked.emit)
        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.setInterval(50)
        self._resize_timer.timeout.connect(self.resize_keep_view)
        self._status = QLabel("Open a PDB, mmCIF, or other structure file.", self)
        self._status.setAlignment(Qt.AlignCenter)
        self._status.setWordWrap(True)
        self._status.setStyleSheet("color: palette(mid); padding: 16px;")
        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(0, 0, 0, 0)
        self._root.setSpacing(0)
        self._root.addWidget(self._status)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._ensure_web()
        self.schedule_resize_keep_view()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if self._web_ready:
            self.schedule_resize_keep_view()

    def schedule_resize_keep_view(self) -> None:
        self._resize_timer.start()

    def resize_keep_view(self) -> None:
        if self._web is None or not self._web_ready:
            return
        try:
            self._web.page().runJavaScript(
                "if (window.molmanagerResizeKeepView) window.molmanagerResizeKeepView();"
            )
        except Exception:
            logger.debug("Protein viewer resize-keep-view failed", exc_info=True)

    def _ensure_web(self) -> None:
        if self._bootstrapped:
            return
        try:
            if not self.isVisible():
                return
        except RuntimeError:
            return
        self._bootstrapped = True
        try:
            from PyQt5.QtWebChannel import QWebChannel
            from PyQt5.QtWebEngineWidgets import QWebEngineSettings, QWebEngineView

            web = QWebEngineView(self)
            web.setContextMenuPolicy(Qt.NoContextMenu)
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
            self._web = web
            self._status.hide()
            self._root.addWidget(web, 1)
        except Exception as e:
            logger.warning("Protein 3D view unavailable: %s", e, exc_info=True)
            self._status.setText(
                "3D view unavailable.\nInstall matching PyQtWebEngine and restart with "
                "`python -m molmanager`."
            )

    def _on_load_finished(self, ok: bool) -> None:
        self._web_ready = bool(ok)
        if self._web_ready and self._pending_payload is not None:
            payload = self._pending_payload
            self._pending_payload = None
            self._pending_hydrogens = None
            self._pending_hbonds = None
            self._run_js("molmanagerSetProteinPayload", payload)
        elif self._web_ready and self._pending_residue_highlight is not None:
            highlight = self._pending_residue_highlight
            self._pending_residue_highlight = None
            self._run_js("molmanagerSetResidueHighlight", highlight)
        if self._web_ready and self._pending_pocket is not None and self._pending_payload is None:
            pocket = self._pending_pocket
            self._pending_pocket = None
            self._run_js("molmanagerSetPocket", pocket)
        if self._web_ready and self._pending_hydrogens is not None:
            mode = self._pending_hydrogens
            self._pending_hydrogens = None
            self._run_js("molmanagerSetHydrogens", mode)
        if self._web_ready and self._pending_hbonds is not None and self._pending_payload is None:
            hbonds = self._pending_hbonds
            self._pending_hbonds = None
            self._run_js("molmanagerSetHbonds", hbonds)
        if self._web_ready:
            self.schedule_resize_keep_view()
            QTimer.singleShot(200, self.resize_keep_view)

    def _run_js(self, fn_name: str, payload) -> None:
        if self._web is None or not self._web_ready:
            if fn_name == "molmanagerSetProteinPayload":
                self._pending_payload = payload
            elif fn_name == "molmanagerApplyComponentStates" and self._pending_payload is not None:
                self._pending_payload["components"] = payload
            elif fn_name == "molmanagerDeleteComponents" and self._pending_payload is not None:
                drop = set(payload or [])
                self._pending_payload["components"] = [
                    comp
                    for comp in self._pending_payload.get("components") or []
                    if comp.get("id") not in drop
                ]
            elif fn_name == "molmanagerSetResidueHighlight":
                self._pending_residue_highlight = payload
                if self._pending_payload is not None:
                    self._pending_payload["residueHighlight"] = payload
            elif fn_name == "molmanagerSetPocket":
                self._pending_pocket = payload
                if self._pending_payload is not None:
                    self._pending_payload["pocket"] = payload
            elif fn_name == "molmanagerSetHydrogens":
                self._pending_hydrogens = payload
                if self._pending_payload is not None:
                    self._pending_payload["hydrogens"] = payload
            elif fn_name == "molmanagerSetHbonds":
                self._pending_hbonds = payload
                if self._pending_payload is not None:
                    self._pending_payload["hbonds"] = payload
            return
        js = f"if (window.{fn_name}) window.{fn_name}({json.dumps(payload)});"
        try:
            self._web.page().runJavaScript(js)
        except Exception:
            logger.debug("Protein viewer %s failed", fn_name, exc_info=True)

    def set_payload(self, payload: dict) -> None:
        self._run_js("molmanagerSetProteinPayload", payload)

    def apply_component_states(self, components: list[dict]) -> None:
        self._run_js("molmanagerApplyComponentStates", components)

    def delete_components(self, ids: list[str]) -> None:
        self._run_js("molmanagerDeleteComponents", ids)

    def zoom_to_components(self, ids: list[str]) -> None:
        self._run_js("molmanagerZoomToComponents", ids)

    def set_residue_highlight(self, selections: list[dict]) -> None:
        self._run_js("molmanagerSetResidueHighlight", selections)

    def mutate_residues(self, items: list[dict]) -> None:
        self._run_js("molmanagerMutateResidues", items)

    def delete_residues(self, selections: list[dict]) -> None:
        self._run_js("molmanagerDeleteResidues", selections)

    def zoom_to_selections(self, selections: list[dict]) -> None:
        self._run_js("molmanagerZoomToSelections", selections)

    def set_pocket(self, pocket: dict | None) -> None:
        self._run_js("molmanagerSetPocket", pocket)

    def set_hydrogens(self, mode: str) -> None:
        self._run_js("molmanagerSetHydrogens", "all" if mode == "all" else "polar")

    def set_hbonds(self, spec: dict | None) -> None:
        self._run_js("molmanagerSetHbonds", spec or {"active": False, "bonds": []})
