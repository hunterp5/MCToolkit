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

"""Render style, hydrogens, H-bonds, pocket, and Manager actions."""

from __future__ import annotations

import base64
import json
import logging
from dataclasses import replace

from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import QAction, QActionGroup, QColorDialog, QMessageBox

from ..hydrogen_bonds import (
    HBOND_KIND_COMPLEX,
    HBOND_KIND_LIGAND,
    HBOND_KIND_PROTEIN,
    detect_hydrogen_bonds,
)
from ..structure_components import (
    component_id_for_atom,
    pocket_view_plan,
    polymer_residue_for_atom,
)
from .protein_viewer_models import (
    COMPONENT_COLOR_CHOICES,
    COMPONENT_STYLE_CHOICES,
    _LoadedSlot,
)
from .qt_widget_utils import qobject_is_deleted

logger = logging.getLogger(__name__)


class ProteinViewerStyleMixin:
    def _on_all_atoms_toggled(self, checked: bool) -> None:
        style = "ballstick" if checked else "cartoon"
        self._check_style_action(self._protein_style_actions, style)
        self._apply_kind_style("polymer", style)

    def _hydrogen_mode(self) -> str:
        if self._act_hydrogens_all is not None and self._act_hydrogens_all.isChecked():
            return "all"
        return "polar"

    def _set_hydrogen_mode(self, mode: str) -> None:
        chosen = "all" if mode == "all" else "polar"
        self.viewer.set_hydrogens(chosen)

    def _hbond_kinds_enabled(self) -> set[str]:
        kinds: set[str] = set()
        if self._act_hbond_protein is not None and self._act_hbond_protein.isChecked():
            kinds.add(HBOND_KIND_PROTEIN)
        if self._act_hbond_ligand is not None and self._act_hbond_ligand.isChecked():
            kinds.add(HBOND_KIND_LIGAND)
        if self._act_hbond_complex is not None and self._act_hbond_complex.isChecked():
            kinds.add(HBOND_KIND_COMPLEX)
        return kinds

    def _invalidate_hbonds(self, structure_id: str | None = None) -> None:
        if structure_id is None:
            self._hbond_cache.clear()
        else:
            self._hbond_cache.pop(structure_id, None)

    def _slot_model_index(self, slot: _LoadedSlot) -> int | None:
        for row in slot.rows:
            model = (row.spec.selection or {}).get("model")
            if model is not None:
                try:
                    return int(model)
                except (TypeError, ValueError):
                    return None
        return None

    def _ensure_hbond_cache(self) -> None:
        if not self._hbond_kinds_enabled():
            return
        for slot in self._slots:
            if slot.structure_id in self._hbond_cache:
                continue
            self._hbond_cache[slot.structure_id] = detect_hydrogen_bonds(
                slot.text, slot.fmt, model=self._slot_model_index(slot)
            )

    def _hbond_endpoint_visible(self, bond, *, model: int | None) -> bool:
        return self._residue_is_visible(
            chain=bond.donor_chain,
            resn=bond.donor_resn,
            resi=bond.donor_resi,
            icode=bond.donor_icode,
            kind=bond.donor_kind,
            model=model,
        ) and self._residue_is_visible(
            chain=bond.acceptor_chain,
            resn=bond.acceptor_resn,
            resi=bond.acceptor_resi,
            icode=bond.acceptor_icode,
            kind=bond.acceptor_kind,
            model=model,
        )

    def _residue_is_visible(
        self,
        *,
        chain: str,
        resn: str,
        resi: str,
        icode: str,
        kind: str,
        model: int | None,
    ) -> bool:
        resi_s = str(resi)
        for row in self._rows:
            if not row.visible:
                continue
            spec = row.spec
            sel_model = (spec.selection or {}).get("model")
            if model is not None and sel_model is not None:
                try:
                    if int(sel_model) != int(model):
                        continue
                except (TypeError, ValueError):
                    continue
            if spec.kind == "polymer" and kind == "polymer" and spec.chain == chain:
                return True
            if (
                spec.kind == kind
                and spec.chain == chain
                and spec.resn == resn
                and spec.resi == resi_s
                and spec.icode == icode
            ):
                return True
        return False

    def _hbond_overlay_payload(self) -> dict:
        kinds = self._hbond_kinds_enabled()
        if not kinds or not self._slots:
            return {"active": False, "bonds": []}
        self._ensure_hbond_cache()
        bonds = []
        for slot in self._slots:
            model = self._slot_model_index(slot)
            for bond in self._hbond_cache.get(slot.structure_id, ()):
                if bond.kind not in kinds:
                    continue
                if not self._hbond_endpoint_visible(bond, model=model):
                    continue
                bonds.append(bond.to_payload())
        return {"active": True, "bonds": bonds}

    def _on_hbond_toggles(self, _checked: bool = False) -> None:
        self._push_hbonds()

    def _push_hbonds(self) -> None:
        self.viewer.set_hbonds(self._hbond_overlay_payload())

    def _apply_kind_style(self, kind: str, style: str) -> None:
        allowed = {key for key, _label in COMPONENT_STYLE_CHOICES}
        if style not in allowed:
            return
        changed = False
        for slot in self._slots:
            new_rows = []
            for row in slot.rows:
                if row.spec.kind == kind and row.style != style:
                    new_rows.append(replace(row, style=style))
                    changed = True
                else:
                    new_rows.append(row)
            slot.rows = new_rows
        if changed:
            self.manager.apply_row_states(self._rows)
            self._push_states()

    def _add_select_style_menu(self, menu) -> None:
        for style_id, label in COMPONENT_STYLE_CHOICES:
            act = QAction(label, self)
            act.setToolTip("Apply this style to the Manager selection.")
            act.triggered.connect(lambda _checked=False, s=style_id: self._on_style_requested(s))
            menu.addAction(act)

    def _add_select_color_menu(self, menu) -> None:
        for color_id, label in COMPONENT_COLOR_CHOICES:
            act = QAction(label, self)
            act.setToolTip("Color carbons in the Manager selection; heteroatoms stay CPK.")
            act.triggered.connect(lambda _checked=False, c=color_id: self._apply_selected_color(c))
            menu.addAction(act)
        menu.addSeparator()
        act_custom = QAction("Custom…", self, triggered=self._on_select_custom_color)
        act_custom.setToolTip("Pick a carbon color for the Manager selection.")
        menu.addAction(act_custom)

    def _selected_component_ids(self) -> list[str]:
        return self.manager.selected_component_ids() or [
            r.spec.component_id for r in self._rows if r.selected
        ]

    def _require_selection(self) -> list[str]:
        ids = self._selected_component_ids()
        if not ids:
            QMessageBox.information(
                self,
                "Select",
                "Select a chain or ligand in the Manager first.",
            )
        return ids

    def _set_selected_visible(self, visible: bool) -> None:
        ids = set(self._require_selection())
        if not ids:
            return
        changed = False
        for slot in self._slots:
            new_rows = []
            for row in slot.rows:
                if row.spec.component_id in ids and row.visible != visible:
                    new_rows.append(replace(row, visible=visible))
                    changed = True
                else:
                    new_rows.append(row)
            slot.rows = new_rows
        if changed:
            self.manager.apply_row_states(self._rows)
            self._push_states()

    def _on_select_custom_color(self) -> None:
        chosen = QColorDialog.getColor(QColor("#2ca02c"), self, "Carbon color")
        if not chosen.isValid():
            return
        self._apply_selected_color(chosen.name())

    def _apply_selected_color(self, color_scheme: str) -> None:
        allowed = {key for key, _label in COMPONENT_COLOR_CHOICES}
        if color_scheme not in allowed and not str(color_scheme).startswith("#"):
            return
        ids = set(self._require_selection())
        if not ids:
            return
        changed = False
        for slot in self._slots:
            new_rows = []
            for row in slot.rows:
                if row.spec.component_id in ids and row.color_scheme != color_scheme:
                    new_rows.append(replace(row, color_scheme=color_scheme))
                    changed = True
                else:
                    new_rows.append(row)
            slot.rows = new_rows
        if changed:
            self._push_states()

    def _add_render_style_menu(self, menu, *, kind: str, default: str) -> dict[str, QAction]:
        group = QActionGroup(self)
        group.setExclusive(True)
        actions: dict[str, QAction] = {}
        for style_id, label in COMPONENT_STYLE_CHOICES:
            act = QAction(label, self)
            act.setCheckable(True)
            act.setData(style_id)
            if style_id == default:
                act.setChecked(True)
            group.addAction(act)
            menu.addAction(act)
            act.triggered.connect(
                lambda _checked=False, s=style_id, k=kind: self._on_render_style_chosen(k, s)
            )
            actions[style_id] = act
        return actions

    def _add_render_color_menu(self, menu, *, kind: str) -> dict[str, QAction]:
        group = QActionGroup(self)
        group.setExclusive(True)
        actions: dict[str, QAction] = {}
        for color_id, label in COMPONENT_COLOR_CHOICES:
            act = QAction(label, self)
            act.setCheckable(True)
            act.setData(color_id)
            if color_id == "default":
                act.setChecked(True)
            group.addAction(act)
            menu.addAction(act)
            act.triggered.connect(
                lambda _checked=False, c=color_id, k=kind: self._on_render_color_chosen(k, c)
            )
            actions[color_id] = act
        return actions

    def _on_render_style_chosen(self, kind: str, style: str) -> None:
        self._apply_kind_style(kind, style)
        if kind == "polymer":
            self._sync_all_atoms_check(style == "ballstick")

    def _on_render_color_chosen(self, kind: str, color_scheme: str) -> None:
        self._apply_kind_color(kind, color_scheme)

    def _apply_kind_color(self, kind: str, color_scheme: str) -> None:
        allowed = {key for key, _label in COMPONENT_COLOR_CHOICES}
        if color_scheme not in allowed:
            return
        changed = False
        for slot in self._slots:
            new_rows = []
            for row in slot.rows:
                if row.spec.kind == kind and row.color_scheme != color_scheme:
                    new_rows.append(replace(row, color_scheme=color_scheme))
                    changed = True
                else:
                    new_rows.append(row)
            slot.rows = new_rows
        if changed:
            self._push_states()

    def _checked_style(self, actions: dict[str, QAction], fallback: str) -> str:
        for style_id, act in actions.items():
            if act.isChecked():
                return style_id
        return fallback

    def _check_style_action(self, actions: dict[str, QAction], style: str) -> None:
        act = actions.get(style)
        if act is None or act.isChecked():
            return
        act.blockSignals(True)
        act.setChecked(True)
        act.blockSignals(False)

    def _sync_all_atoms_check(self, checked: bool) -> None:
        if self._act_all_atoms.isChecked() == checked:
            return
        self._act_all_atoms.blockSignals(True)
        self._act_all_atoms.setChecked(checked)
        self._act_all_atoms.blockSignals(False)

    def _sync_render_menus_from_rows(self) -> None:
        polymer = {r.style for r in self._rows if r.spec.kind == "polymer"}
        ligand = {r.style for r in self._rows if r.spec.kind == "ligand"}
        if len(polymer) == 1:
            style = next(iter(polymer))
            self._check_style_action(self._protein_style_actions, style)
            self._sync_all_atoms_check(style == "ballstick")
        if len(ligand) == 1:
            self._check_style_action(self._ligand_style_actions, next(iter(ligand)))
        polymer_color = {r.color_scheme for r in self._rows if r.spec.kind == "polymer"}
        ligand_color = {r.color_scheme for r in self._rows if r.spec.kind == "ligand"}
        if len(polymer_color) == 1:
            self._check_style_action(self._protein_color_actions, next(iter(polymer_color)))
        if len(ligand_color) == 1:
            self._check_style_action(self._ligand_color_actions, next(iter(ligand_color)))

    def _on_pocket(self) -> None:
        self._activate_pocket(zoom=True)

    def _activate_pocket(self, *, zoom: bool) -> bool:
        payload = self._compute_pocket_payload()
        if payload is None:
            if zoom:
                QMessageBox.information(
                    self,
                    "Pocket",
                    "Open a structure that contains a ligand, or select a ligand in the Manager.",
                )
            return False
        self._pocket_payload_data = payload
        self.viewer.set_pocket(payload)
        if zoom:
            sels = payload.get("zoomSels") or []
            if sels:
                self.viewer.zoom_to_selections(sels)
        return True

    def _refresh_pocket(self, *, zoom: bool) -> None:
        if self._pocket_payload_data is None:
            return
        if self._activate_pocket(zoom=zoom):
            return
        self._pocket_payload_data = None
        self.viewer.set_pocket({"active": False})

    def _compute_pocket_payload(self) -> dict | None:
        selected_ligands = [r for r in self._rows if r.selected and r.spec.kind == "ligand"]
        if selected_ligands:
            sid = selected_ligands[0].spec.structure_id
            slot = next((s for s in self._slots if s.structure_id == sid), None)
            lig_rows = [r for r in selected_ligands if r.spec.structure_id == sid]
        else:
            slot = self._active_slot()
            lig_rows = [r for r in (slot.rows if slot else []) if r.spec.kind == "ligand"]
        if slot is None or not lig_rows:
            return None
        model = None
        for row in lig_rows:
            model = (row.spec.selection or {}).get("model")
            if model is not None:
                break
        keys = [(r.spec.chain, r.spec.resn, r.spec.resi, r.spec.icode) for r in lig_rows]
        plan = pocket_view_plan(slot.text, slot.fmt, ligand_keys=keys, model=model)
        if plan is None:
            return None
        polar_b64 = ""
        if plan.polar_h_pdb:
            polar_b64 = base64.b64encode(plan.polar_h_pdb.encode("utf-8")).decode("ascii")
        return {
            "active": True,
            "ligandSels": list(plan.ligand_sels),
            "residueSels": list(plan.residue_sels),
            "zoomSels": list(plan.ligand_sels),
            "polarHPdb": polar_b64,
        }

    def delete_selected(self) -> None:
        ids = self._selected_component_ids()
        if not ids:
            return
        labels = [r.spec.label for r in self._rows if r.spec.component_id in set(ids)]
        preview = ", ".join(labels[:6])
        if len(labels) > 6:
            preview += "…"
        n = len(ids)
        msg = f"Delete {n} selected chain{'s' if n != 1 else ''} from the viewer?"
        if preview:
            msg += f"\n\n{preview}"
        if (
            QMessageBox.question(
                self, "Delete chains", msg, QMessageBox.Yes | QMessageBox.No, QMessageBox.No
            )
            != QMessageBox.Yes
        ):
            return
        drop = set(ids)
        kept: list[_LoadedSlot] = []
        for slot in self._slots:
            rows = [r for r in slot.rows if r.spec.component_id not in drop]
            if rows:
                slot.rows = rows
                kept.append(slot)
        self._slots = kept
        self._reindex_models()
        if not self._slots:
            self.close_structure()
            return
        self._refresh_manager()
        self._refresh_sequence_chains()
        self._push_structure(refit=False)
        if self._pocket_payload_data is not None:
            self._refresh_pocket(zoom=False)
        self._mark_host_session_dirty()

    def focus_selected(self) -> None:
        ids = self._require_selection()
        if ids:
            self.viewer.zoom_to_components(ids)

    def _on_visibility_changed(self, component_id: str, visible: bool) -> None:
        changed = False
        for slot in self._slots:
            new_rows = []
            for row in slot.rows:
                if row.spec.component_id == component_id and row.visible != visible:
                    new_rows.append(replace(row, visible=visible))
                    changed = True
                else:
                    new_rows.append(row)
            slot.rows = new_rows
        if changed:
            self.manager.apply_row_states(self._rows)
            self._push_states()

    def _on_manager_selection(self, ids: list) -> None:
        want = set(ids)
        changed = False
        for slot in self._slots:
            new_rows = []
            for row in slot.rows:
                selected = row.spec.component_id in want
                if row.selected != selected:
                    new_rows.append(replace(row, selected=selected))
                    changed = True
                else:
                    new_rows.append(row)
            slot.rows = new_rows
        if not self._syncing_from_atom and self._residue_highlight:
            self._residue_highlight = []
            self.viewer.set_residue_highlight([])
        if changed:
            self._push_states()

    def _on_style_requested(self, style: str) -> None:
        allowed = {key for key, _label in COMPONENT_STYLE_CHOICES}
        if style not in allowed:
            return
        ids = set(self._require_selection())
        if not ids:
            return
        changed = False
        for slot in self._slots:
            new_rows = []
            for row in slot.rows:
                if row.spec.component_id in ids and row.style != style:
                    new_rows.append(replace(row, style=style))
                    changed = True
                else:
                    new_rows.append(row)
            slot.rows = new_rows
        if changed:
            self._push_states()
            self._sync_render_menus_from_rows()

    def _on_atom_picked(self, payload: str) -> None:
        try:
            data = json.loads(payload or "{}")
        except json.JSONDecodeError:
            return
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
        if not cid:
            return
        sel = {
            "chain": str(data.get("chain") or ""),
            "resi": data.get("resi"),
        }
        icode = str(data.get("icode") or "")
        if icode:
            sel["icode"] = icode
        if model_i is not None:
            sel["model"] = model_i
        try:
            sel["resi"] = int(str(sel["resi"]).strip())
        except (TypeError, ValueError):
            sel["resi"] = str(sel.get("resi") or "")
        self._syncing_from_atom = True
        try:
            for slot in self._slots:
                slot.rows = [
                    replace(row, selected=row.spec.component_id == cid) for row in slot.rows
                ]
            self.manager.apply_row_states(self._rows)
            self._set_residue_highlight([sel])
            self._push_states()
        finally:
            self._syncing_from_atom = False
        dlg = self._sequence_dialog
        if dlg is not None and not qobject_is_deleted(dlg):
            spec = next((r.spec for r in self._rows if r.spec.component_id == cid), None)
            hit = polymer_residue_for_atom(
                self._sequence_chains,
                chain=str(data.get("chain") or ""),
                resi=data.get("resi"),
                icode=icode,
                structure_id=spec.structure_id if spec is not None else "",
            )
            if hit is not None:
                dlg.select_residue(hit.chain, hit.resi, hit.icode, structure_id=hit.structure_id)
