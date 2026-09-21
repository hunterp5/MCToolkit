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


"""SBDD overlays for Protein Viewer: docking box, dock pose, and atom picks."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from PySide6.QtWidgets import QFileDialog, QMessageBox

from ..chem.molecule_conversion import copy_mol
from ..protein.structure_components import component_id_for_atom
from .protein_canvas import molstar_coordinate_format, molstar_volume_format

_TRAJ_FILTER = "Trajectories (*.dcd *.xtc *.trr *.nc *.nctraj);;All files (*.*)"
_MAP_FILTER = "Maps (*.ccp4 *.mrc *.map *.dsn6 *.brix *.dx *.cube);;All files (*.*)"


class ProteinViewerStyleMixin:
    """Docking-box / pose overlays and atom-pick status (Mol* owns representation)."""

    def _docking_box_overlay_payload(self) -> dict | None:
        payload = self._docking_box_payload
        if not payload:
            return None
        act = getattr(self, "_act_docking_box", None)
        if act is not None and not act.isChecked():
            return {"active": False}
        return payload

    def _on_docking_box_toggled(self, checked: bool) -> None:
        if checked and not self._docking_box_payload:
            return
        self.viewer.set_docking_box(self._docking_box_overlay_payload())

    def set_docking_box_from_prepare(self, result) -> None:
        """Show the Gnina box from a Prepare run."""
        box = getattr(result, "box", None)
        if box is None:
            return
        payload = box.viewer_payload()
        self._docking_box_payload = payload
        act = getattr(self, "_act_docking_box", None)
        if act is not None:
            act.blockSignals(True)
            act.setChecked(True)
            act.blockSignals(False)
        self.viewer.set_docking_box(payload)
        self._mark_viewer_unsaved()

    def _dock_pose_overlay_payload(self) -> dict | None:
        payload = getattr(self, "_dock_pose_payload", None)
        if not payload:
            return None
        return payload

    def set_dock_pose(self, mol, *, zoom: bool = False, caption: str = "") -> bool:
        """Overlay a docked pose in the pocket without adding a structure slot."""
        from .dock_complex_viewer import ligand_display_payload

        if mol is None:
            self.clear_dock_pose()
            return False
        b64, fmt = ligand_display_payload(mol)
        if not b64:
            return False
        live = {"active": True, "data": b64, "fmt": fmt or "sdf", "zoom": bool(zoom)}
        stored = dict(live)
        stored["zoom"] = False
        self._dock_pose_mol = copy_mol(mol) or mol
        self._dock_pose_payload = stored
        self.viewer.set_dock_pose(live)
        if caption:
            self._set_atom_status(caption)
        return True

    def clear_dock_pose(self) -> None:
        """Remove the transient dock-pose overlay from the 3D canvas."""
        self._dock_pose_mol = None
        self._dock_pose_payload = None
        self.viewer.set_dock_pose({"active": False})

    def _set_atom_status(self, text: str) -> None:
        lbl = getattr(self, "_atom_status", None)
        if lbl is None:
            return
        lbl.setText(text or "")

    def _atom_status_text(self, data: dict) -> str:
        chain = str(data.get("chain") or "").strip()
        resn = str(data.get("resn") or "").strip()
        resi = data.get("resi")
        resi_s = str(resi).strip() if resi is not None and str(resi).strip() != "" else ""
        icode = str(data.get("icode") or "").strip()
        atom = str(data.get("atom") or "").strip()
        elem = str(data.get("elem") or "").strip()
        serial = data.get("serial")
        alt = str(data.get("altLoc") or data.get("altloc") or "").strip()
        loc = f"{chain}:" if chain else ""
        loc += " ".join(part for part in (resn, resi_s + icode) if part)
        bits = [part for part in (loc.strip(), atom) if part]
        if elem and elem.upper() != atom.upper():
            bits.append(elem)
        if alt and alt not in {"", " ", "A"}:
            bits.append(f"alt {alt}")
        try:
            if serial is not None and str(serial).strip() != "":
                bits.append(f"#{int(serial)}")
        except (TypeError, ValueError):
            if serial not in (None, ""):
                bits.append(f"#{serial}")
        return "  ".join(bits)

    def _set_residue_highlight(self, selections: list[dict]) -> None:
        self._residue_highlight = list(selections)

    def _on_atom_picked(self, payload: str) -> None:
        try:
            data = json.loads(payload or "{}")
        except json.JSONDecodeError:
            return
        hook = getattr(self, "_on_pharmacophore_atom_picked", None)
        if callable(hook):
            hook(data)
        model = data.get("model")
        try:
            model_i = int(model) if model is not None and str(model).strip() != "" else None
        except (TypeError, ValueError):
            model_i = None
        cid = component_id_for_atom(
            (r.spec for r in self._rows),
            chain=str(data.get("chain") or ""),
            resn=str(data.get("resn") or ""),
            resi=data.get("resi"),
            icode=str(data.get("icode") or ""),
            model=model_i,
        )
        spec = (
            next((r.spec for r in self._rows if r.spec.component_id == cid), None) if cid else None
        )
        icode = str(data.get("icode") or "")
        double_click = bool(data.get("doubleClick"))
        kind = spec.kind if spec is not None else ""
        whole_ligand = double_click and kind == "ligand"
        whole_residue = double_click and kind == "polymer"
        resi = data.get("resi")
        try:
            if resi is not None and str(resi).strip() != "":
                resi = int(resi)
        except (TypeError, ValueError):
            resi = data.get("resi")
        if whole_ligand and spec is not None:
            sel = dict(spec.selection or {})
            if not sel:
                sel = {"chain": str(data.get("chain") or ""), "resi": resi}
                if icode:
                    sel["icode"] = icode
        elif whole_residue:
            sel = {"chain": str(data.get("chain") or ""), "resi": resi}
            if icode:
                sel["icode"] = icode
        else:
            sel = {"chain": str(data.get("chain") or ""), "resi": resi}
            if icode:
                sel["icode"] = icode
            atom = str(data.get("atom") or "").strip()
            if atom:
                sel["atom"] = atom
            serial = data.get("serial")
            try:
                if serial is not None and str(serial).strip() != "":
                    sel["serial"] = int(serial)
            except (TypeError, ValueError):
                pass
        sel["resn"] = str(data.get("resn") or sel.get("resn") or "")
        sel["kind"] = kind
        sel["component_id"] = cid
        if spec is not None:
            sel["structure_id"] = spec.structure_id
        if model_i is not None:
            sel["model"] = model_i
        highlights = [sel]
        merger = getattr(self, "_merge_structure_edit_pick", None)
        if callable(merger) and not whole_ligand and not whole_residue:
            highlights = merger(sel) or [sel]
        self._set_residue_highlight(highlights)
        if cid:
            for slot in self._slots:
                slot.rows = [
                    replace(row, selected=row.spec.component_id == cid) for row in slot.rows
                ]
        self._set_atom_status(self._atom_status_text(highlights[-1] if highlights else sel))
        sync = getattr(self, "_sync_structure_edit_actions", None)
        if callable(sync):
            sync()

    def load_trajectory_path(self, path: str | Path, slot=None) -> bool:
        """Load a DCD/XTC onto ``slot`` (or the active structure) in Mol*."""
        rec = Path(path)
        host = slot if slot is not None else self._active_slot()
        if host is None or not rec.is_file():
            return False
        try:
            coords = rec.read_bytes()
        except OSError as exc:
            QMessageBox.warning(self, "Open Trajectory", str(exc))
            return False
        import base64

        spec = {
            "topology": {
                "data": base64.b64encode(host.text.encode("utf-8")).decode("ascii"),
                "fmt": host.fmt,
            },
            "coordinates": {
                "data": base64.b64encode(coords).decode("ascii"),
                "fmt": molstar_coordinate_format(rec.suffix),
            },
        }
        self.viewer.load_trajectory(spec)
        self.append_log(f"Loaded trajectory {rec.name} onto {host.name}.")
        return True

    def open_trajectory_dialog(self) -> None:
        """Load a DCD/XTC trajectory onto the active structure topology."""
        slot = self._active_slot()
        if slot is None:
            QMessageBox.information(self, "Open Trajectory", "Open a structure first.")
            return
        path, _ = QFileDialog.getOpenFileName(self, "Open trajectory", "", _TRAJ_FILTER)
        if not path:
            return
        self.load_trajectory_path(path, slot)

    def open_map_dialog(self) -> None:
        """Load a CCP4/MRC map through Mol* Density."""
        path, _ = QFileDialog.getOpenFileName(self, "Open map", "", _MAP_FILTER)
        if not path:
            return
        rec = Path(path)
        try:
            data = rec.read_bytes()
        except OSError as exc:
            QMessageBox.warning(self, "Open Map", str(exc))
            return
        import base64

        self.viewer.load_volume(
            {
                "data": base64.b64encode(data).decode("ascii"),
                "fmt": molstar_volume_format(rec.suffix),
                "name": rec.name,
            }
        )
        self.append_log(f"Loaded map {rec.name}.")

    def export_canvas_image(self) -> None:
        """Save a PNG of the Mol* canvas."""
        path, _ = QFileDialog.getSaveFileName(self, "Export Image", "protein.png", "PNG (*.png)")
        if not path:
            return
        from PySide6.QtCore import QEventLoop, QTimer

        loop = QEventLoop()
        box: dict = {"value": None}

        def _cb(val) -> None:
            box["value"] = val
            loop.quit()

        web = getattr(self.viewer, "_web", None)
        if web is None:
            QMessageBox.information(self, "Export Image", "The 3D canvas is not ready.")
            return
        try:
            web.page().runJavaScript(
                "window.mctoolkitScreenshotPng ? window.mctoolkitScreenshotPng() : null",
                _cb,
            )
        except Exception as exc:
            QMessageBox.warning(self, "Export Image", str(exc))
            return
        QTimer.singleShot(1500, loop.quit)
        loop.exec()
        uri = box.get("value")
        if not isinstance(uri, str) or "," not in uri:
            QMessageBox.warning(self, "Export Image", "Could not capture the canvas.")
            return
        import base64

        try:
            Path(path).write_bytes(base64.b64decode(uri.split(",", 1)[1]))
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Export Image", str(exc))
