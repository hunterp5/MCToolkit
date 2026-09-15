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

"""Open/save/session state for the Protein Viewer window."""

from __future__ import annotations

import logging
from dataclasses import replace
from pathlib import Path

from PyQt5.QtCore import QByteArray
from PyQt5.QtWidgets import QFileDialog, QMessageBox

from ..structure_components import (
    LoadedStructure,
    load_structure_file,
    parse_polymer_sequences,
    parse_structure_components,
    scope_structure_component,
)
from .protein_viewer_models import (
    STRUCTURE_FILE_FILTER,
    STRUCTURE_SAVE_FILTER,
    _ComponentView,
    _LoadedSlot,
    _component_state_key,
)
from .qt_widget_utils import qobject_is_deleted

logger = logging.getLogger(__name__)


class ProteinViewerIoMixin:
    @property
    def _rows(self) -> list[_ComponentView]:
        return [row for slot in self._slots for row in slot.rows]

    @property
    def _loaded(self) -> LoadedStructure | None:
        slot = self._active_slot()
        if slot is None:
            return None
        return LoadedStructure(
            path=slot.path,
            text=slot.text,
            sniffed_format=slot.fmt,
            viewer_format=slot.fmt,
            components=tuple(row.spec for row in slot.rows),
        )

    @property
    def _viewer_text(self) -> str:
        slot = self._active_slot()
        return slot.text if slot is not None else ""

    @property
    def _viewer_fmt(self) -> str:
        slot = self._active_slot()
        return slot.fmt if slot is not None else "pdb"

    def _active_slot(self) -> _LoadedSlot | None:
        selected = [r.spec.structure_id for r in self._rows if r.selected]
        if selected:
            sid = selected[-1]
            for slot in self._slots:
                if slot.structure_id == sid:
                    return slot
        if self._slots:
            return self._slots[-1]
        return None

    def _manager_groups(self) -> list[tuple[str, str]]:
        return [(slot.structure_id, slot.name) for slot in self._slots]

    def _refresh_manager(self) -> None:
        names = [slot.name for slot in self._slots]
        filename = ", ".join(names) if names else ""
        self.manager.set_structure(self._rows, filename=filename, groups=self._manager_groups())
        if len(names) == 1:
            self.setWindowTitle(f"Protein Viewer — {names[0]}")
        elif names:
            self.setWindowTitle(f"Protein Viewer — {len(names)} structures")
        else:
            self.setWindowTitle("Protein Viewer")

    def _unique_slot_name(self, name: str) -> str:
        used = {slot.name for slot in self._slots}
        if name not in used:
            return name
        stem = Path(name).stem
        suffix = Path(name).suffix
        n = 2
        while True:
            candidate = f"{stem} ({n}){suffix}"
            if candidate not in used:
                return candidate
            n += 1

    def prepare_source(self) -> tuple[str, str, str, Path | None]:
        """Return (display name, file text, viewer format, path) for Prepare."""
        slot = self._active_slot()
        if slot is None:
            return ("", "", "pdb", None)
        return (slot.name, slot.text, slot.fmt, slot.path)

    def prepare_source_id(self) -> str:
        """Structure id of the file Prepare will read."""
        slot = self._active_slot()
        return slot.structure_id if slot is not None else ""

    def prepare_slot_payload(self, structure_id: str) -> tuple[str, str]:
        """Return ``(text, fmt)`` for a loaded structure id."""
        sid = (structure_id or "").strip()
        for slot in self._slots:
            if slot.structure_id == sid:
                return slot.text, slot.fmt
        return "", "pdb"

    def prepare_water_keys(self) -> tuple[tuple[str, str, str], ...]:
        """Residue keys for Manager-selected water groups on the active structure."""
        slot = self._active_slot()
        if slot is None:
            return ()
        selected_chains = {
            row.spec.chain
            for row in slot.rows
            if row.selected and row.spec.kind == "water" and row.spec.chain
        }
        if not selected_chains:
            return ()
        keys: list[tuple[str, str, str]] = []
        seen: set[tuple[str, str, str]] = set()
        for poly in parse_polymer_sequences(slot.text, slot.fmt):
            if poly.chain not in selected_chains:
                continue
            for res in poly.residues:
                if res.kind != "water":
                    continue
                key = (res.chain, res.resi, res.icode)
                if key in seen:
                    continue
                seen.add(key)
                keys.append(key)
        return tuple(keys)

    def prepare_ligand_options(self) -> list[tuple[str, tuple[str, str, str], bool, str]]:
        """Ligands on loaded structures: ``(label, residue key, selected, structure_id)``."""
        slots = list(self._slots)
        if not slots:
            return []
        multi = len(slots) > 1
        active = self._active_slot()
        rows_by_slot: list[tuple[_LoadedSlot, list[_ComponentView]]] = []
        for slot in slots:
            lig_rows = [row for row in slot.rows if row.spec.kind == "ligand"]
            if lig_rows:
                rows_by_slot.append((slot, lig_rows))
        if not rows_by_slot:
            return []
        any_selected = any(row.selected for _slot, lig_rows in rows_by_slot for row in lig_rows)
        out: list[tuple[str, tuple[str, str, str], bool, str]] = []
        for slot, lig_rows in rows_by_slot:
            for row in lig_rows:
                spec = row.spec
                key = (spec.chain or "", str(spec.resi or "").strip() or "0", spec.icode or "")
                label = spec.label or f"{spec.resn} {spec.chain}{spec.resi}"
                if multi:
                    label = f"{slot.name}: {label}"
                selected = bool(row.selected) if any_selected else False
                out.append((label, key, selected, slot.structure_id))
        if not any_selected and out:
            ranked: list[tuple[int, bool, tuple[str, str, str], str]] = []
            for slot, lig_rows in rows_by_slot:
                for row in lig_rows:
                    spec = row.spec
                    key = (
                        spec.chain or "",
                        str(spec.resi or "").strip() or "0",
                        spec.icode or "",
                    )
                    ranked.append(
                        (
                            int(spec.n_atoms or 0),
                            slot is active,
                            key,
                            slot.structure_id,
                        )
                    )
            ranked.sort(key=lambda item: (item[1], item[0]), reverse=True)
            best_key, best_sid = ranked[0][2], ranked[0][3]
            out = [
                (label, key, key == best_key and sid == best_sid, sid)
                for label, key, _selected, sid in out
            ]
        return out

    def open_structure_dialog(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Open structure", "", STRUCTURE_FILE_FILTER)
        for i, path in enumerate(paths):
            self.add_structure_path(path, refit=(i == len(paths) - 1))

    def save_structure_dialog(self) -> None:
        slot = self._active_slot()
        if slot is None:
            QMessageBox.information(self, "Save Structure", "Open a structure first.")
            return
        fmt = (slot.fmt or "pdb").lower()
        if fmt == "cif":
            suffix = ".cif"
            selected = "mmCIF (*.cif *.mmcif *.mcif)"
        else:
            suffix = ".pdb"
            selected = "PDB (*.pdb)"
        default_name = (
            Path(slot.name).with_suffix(suffix) if slot.name else Path(f"structure{suffix}")
        )
        start = str(slot.path) if slot.path and slot.path.parent.is_dir() else str(default_name)
        path, _ = QFileDialog.getSaveFileName(
            self, "Save structure", start, STRUCTURE_SAVE_FILTER, selected
        )
        if not path:
            return
        rec = Path(path)
        if not rec.suffix:
            rec = rec.with_suffix(suffix)
        try:
            rec.write_bytes(slot.text.encode("utf-8"))
        except OSError as exc:
            QMessageBox.warning(self, "Save Structure", str(exc))

    def load_structure_path(self, path: str | Path) -> None:
        self.add_structure_path(path, refit=True)

    def add_structure_path(self, path: str | Path, *, refit: bool = True) -> None:
        try:
            loaded = load_structure_file(path)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Protein Viewer", str(exc))
            return
        text = loaded.text
        fmt = loaded.viewer_format
        if loaded.sniffed_format == "pdbqt":
            from .dock_complex_viewer import pdbqt_to_pdb_text

            text = pdbqt_to_pdb_text(loaded.text) or loaded.text
            fmt = "pdb"
        if not loaded.components:
            QMessageBox.information(
                self,
                "Protein Viewer",
                "No atoms were found in that file.",
            )
            return
        self._append_loaded_slot(
            text=text,
            fmt=fmt,
            components=loaded.components,
            name=loaded.path.name,
            path=loaded.path,
            refit=refit,
        )

    def _append_loaded_slot(
        self,
        *,
        text: str,
        fmt: str,
        components,
        name: str,
        path: Path | None,
        refit: bool,
        row_states: list[dict] | None = None,
        push: bool = True,
    ) -> None:
        sid = f"s{self._slot_seq}"
        self._slot_seq += 1
        model = len(self._slots)
        protein_style = self._checked_style(self._protein_style_actions, "cartoon")
        ligand_style = self._checked_style(self._ligand_style_actions, "ballstick")
        protein_color = self._checked_style(self._protein_color_actions, "default")
        ligand_color = self._checked_style(self._ligand_color_actions, "default")
        state_by_key = {
            _component_state_key(item): item
            for item in (row_states or [])
            if isinstance(item, dict)
        }
        rows = []
        for comp in components:
            spec = scope_structure_component(comp, structure_id=sid, model=model)
            saved = state_by_key.get(_component_state_key(spec))
            style = (
                protein_style
                if spec.kind == "polymer"
                else ligand_style
                if spec.kind == "ligand"
                else spec.default_style
            )
            color_scheme = (
                protein_color
                if spec.kind == "polymer"
                else ligand_color
                if spec.kind == "ligand"
                else "default"
            )
            visible = spec.default_visible
            selected = False
            if saved:
                style = str(saved.get("style") or style)
                color_scheme = str(saved.get("color_scheme") or color_scheme)
                visible = bool(saved.get("visible", visible))
                selected = bool(saved.get("selected", False))
            rows.append(
                _ComponentView(
                    spec=spec,
                    visible=visible,
                    selected=selected,
                    style=style,
                    color_scheme=color_scheme,
                )
            )
        self._slots.append(
            _LoadedSlot(
                structure_id=sid,
                name=self._unique_slot_name(name),
                path=path or Path(name),
                text=text,
                fmt=fmt,
                rows=rows,
            )
        )
        self._residue_highlight = []
        self._invalidate_hbonds()
        if push:
            self._refresh_manager()
            self._refresh_sequence_chains()
            self._push_structure(refit=refit)
            if self._pocket_payload_data is not None:
                self._refresh_pocket(zoom=False)
            self._mark_host_session_dirty()

    def _reindex_models(self) -> None:
        for model, slot in enumerate(self._slots):
            slot.rows = [
                replace(
                    row,
                    spec=scope_structure_component(
                        row.spec, structure_id=slot.structure_id, model=model
                    ),
                )
                for row in slot.rows
            ]

    def close_structure(self, *, mark_dirty: bool = True) -> None:
        self._slots = []
        self._sequence_chains = []
        self._residue_highlight = []
        self._pocket_payload_data = None
        self._docking_box_payload = None
        self._invalidate_hbonds()
        act_box = getattr(self, "_act_docking_box", None)
        if act_box is not None:
            act_box.blockSignals(True)
            act_box.setChecked(False)
            act_box.blockSignals(False)
        self._act_all_atoms.blockSignals(True)
        self._act_all_atoms.setChecked(False)
        self._act_all_atoms.blockSignals(False)
        self._check_style_action(self._protein_style_actions, "cartoon")
        self._check_style_action(self._ligand_style_actions, "ballstick")
        self._check_style_action(self._protein_color_actions, "default")
        self._check_style_action(self._ligand_color_actions, "default")
        self.setWindowTitle("Protein Viewer")
        self.manager.set_structure([])
        self._sync_sequence_dialog()
        self.viewer.set_payload(
            {
                "data": "",
                "fmt": "pdb",
                "models": [],
                "components": [],
                "residueHighlight": [],
                "pocket": None,
                "dockingBox": None,
                "hbonds": {"active": False, "bonds": []},
                "hydrogens": self._hydrogen_mode(),
                "refit": True,
            }
        )
        if mark_dirty:
            self._mark_host_session_dirty()

    def _mark_host_session_dirty(self) -> None:
        parent = self.parent()
        mark = getattr(parent, "_mark_session_dirty", None)
        if callable(mark):
            mark()

    def collect_session_state(self) -> dict | None:
        """JSON payload so File → Save Session can restore this viewer."""
        if not self._slots:
            return None
        structures = []
        for slot in self._slots:
            structures.append(
                {
                    "name": slot.name,
                    "path": str(slot.path) if slot.path else "",
                    "fmt": slot.fmt,
                    "text": slot.text,
                    "rows": [
                        {
                            "kind": row.spec.kind,
                            "chain": row.spec.chain,
                            "resn": row.spec.resn,
                            "resi": row.spec.resi,
                            "icode": row.spec.icode,
                            "visible": row.visible,
                            "selected": row.selected,
                            "style": row.style,
                            "color_scheme": row.color_scheme,
                        }
                        for row in slot.rows
                    ],
                }
            )
        state: dict = {
            "structures": structures,
            "hydrogens": self._hydrogen_mode(),
            "hbonds": {
                "protein": bool(
                    self._act_hbond_protein is not None and self._act_hbond_protein.isChecked()
                ),
                "ligand": bool(
                    self._act_hbond_ligand is not None and self._act_hbond_ligand.isChecked()
                ),
                "complex": bool(
                    self._act_hbond_complex is not None and self._act_hbond_complex.isChecked()
                ),
            },
            "allAtoms": bool(self._act_all_atoms.isChecked()),
            "pocket": bool(self._pocket_payload_data),
            "dockingBox": self._docking_box_payload,
        }
        try:
            geo = self.saveGeometry()
            if geo is not None and not geo.isEmpty():
                state["geometry"] = bytes(geo.toBase64()).decode("ascii")
        except RuntimeError:
            pass
        return state

    def apply_session_state(self, state: dict | None) -> None:
        """Rebuild Manager rows and the 3D canvas from a session payload."""
        if not isinstance(state, dict):
            return
        self.close_structure(mark_dirty=False)
        for spec in state.get("structures") or []:
            if not isinstance(spec, dict):
                continue
            text = str(spec.get("text") or "")
            if not text.strip():
                continue
            fmt = str(spec.get("fmt") or "pdb").lower()
            parse_fmt = "cif" if fmt == "cif" else "pdb"
            try:
                components = parse_structure_components(text, parse_fmt)
            except Exception:
                continue
            if not components:
                continue
            name = str(spec.get("name") or "structure")
            raw_path = str(spec.get("path") or "")
            path = Path(raw_path) if raw_path else Path(name)
            self._append_loaded_slot(
                text=text,
                fmt="cif" if fmt == "cif" else "pdb",
                components=components,
                name=name,
                path=path,
                refit=False,
                row_states=list(spec.get("rows") or []),
                push=False,
            )
        hydrogens = "all" if state.get("hydrogens") == "all" else "polar"
        if self._act_hydrogens_all is not None and self._act_hydrogens_polar is not None:
            target = self._act_hydrogens_all if hydrogens == "all" else self._act_hydrogens_polar
            target.setChecked(True)
        hbonds = state.get("hbonds") if isinstance(state.get("hbonds"), dict) else {}
        for act, key in (
            (self._act_hbond_protein, "protein"),
            (self._act_hbond_ligand, "ligand"),
            (self._act_hbond_complex, "complex"),
        ):
            if act is None:
                continue
            act.blockSignals(True)
            act.setChecked(bool(hbonds.get(key)))
            act.blockSignals(False)
        geo = state.get("geometry")
        if isinstance(geo, str) and geo.strip():
            try:
                self.restoreGeometry(QByteArray.fromBase64(geo.encode("ascii")))
            except Exception:
                logger.debug("Protein viewer restore geometry failed", exc_info=True)
        self._refresh_manager()
        self._refresh_sequence_chains()
        self._sync_render_menus_from_rows()
        if self._slots:
            self._push_structure(refit=True)
            if state.get("pocket"):
                self._activate_pocket(zoom=False)
            box = state.get("dockingBox")
            if isinstance(box, dict) and box.get("active"):
                from ..docking_box import docking_box_from_dict

                parsed = docking_box_from_dict(box)
                payload = parsed.viewer_payload() if parsed is not None else box
                self._docking_box_payload = payload
                act = getattr(self, "_act_docking_box", None)
                if act is not None:
                    act.blockSignals(True)
                    act.setChecked(True)
                    act.blockSignals(False)
                self.viewer.set_docking_box(payload)

    def open_prepare_dialog(self) -> None:
        """Open the Prepare pipeline dialog for the loaded structure."""
        if not self._slots:
            QMessageBox.information(self, "Prepare Structure", "Open a structure first.")
            return
        dlg = self._prepare_dialog
        if dlg is not None and qobject_is_deleted(dlg):
            self._prepare_dialog = None
            dlg = None
        if dlg is None:
            from .dialogs.protein_prepare import ProteinPrepareDialog

            dlg = ProteinPrepareDialog(self)
            dlg.prepared.connect(self._on_structure_prepared)
            dlg.smina_prepared.connect(self._on_smina_prepared)
            dlg.destroyed.connect(self._on_prepare_dialog_destroyed)
            self._prepare_dialog = dlg
        dlg.prefill_from_viewer()
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()

    def _on_prepare_dialog_destroyed(self) -> None:
        self._prepare_dialog = None

    def _on_structure_prepared(self, output_pdb: str) -> None:
        path = Path(output_pdb)
        if not path.is_file():
            QMessageBox.warning(self, "Prepare Structure", f"Prepared file was not found:\n{path}")
            return
        self.add_structure_path(path, refit=False)

    def _on_smina_prepared(self, result) -> None:
        setter = getattr(self, "set_docking_box_from_prepare", None)
        if callable(setter):
            setter(result)
