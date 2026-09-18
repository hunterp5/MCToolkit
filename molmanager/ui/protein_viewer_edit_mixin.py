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


"""Atom and ligand-bond edits in the Protein Viewer."""

from __future__ import annotations

from PyQt5.QtWidgets import QMessageBox

from ..structure_components import (
    _atom_key4,
    add_cif_chem_bond,
    add_pdb_conect,
    delete_cif_atoms,
    delete_pdb_atoms,
    pdb_serial_for_atom,
    remove_cif_chem_bond,
    remove_pdb_conect,
)
from .protein_viewer_models import copy_loaded_slots
from .qt_widget_utils import qobject_is_deleted


def _viewer_atom_sel(sel: dict) -> dict:
    """3Dmol selection keys only (drop Manager metadata)."""
    out: dict = {}
    for key in ("model", "serial", "chain", "resi", "icode", "atom"):
        value = sel.get(key)
        if value not in (None, ""):
            out[key] = value
    return out


def _sel_atom_key(sel: dict) -> tuple[str, str, str, str]:
    return _atom_key4(
        str(sel.get("chain") or ""),
        str(sel.get("resi") or ""),
        str(sel.get("icode") or ""),
        str(sel.get("atom") or ""),
    )


def _atom_pick_id(sel: dict) -> tuple:
    return (
        str(sel.get("structure_id") or ""),
        str(sel.get("chain") or ""),
        str(sel.get("resi") or ""),
        str(sel.get("icode") or ""),
        str(sel.get("atom") or ""),
        sel.get("serial"),
    )


def _slot_is_cif(fmt: str) -> bool:
    return (fmt or "").lower() in {"cif", "mmcif"}


class ProteinViewerEditMixin:
    def _edit_structure_enabled(self) -> bool:
        act = getattr(self, "_act_edit_structure", None)
        return bool(act is not None and act.isChecked())

    def _highlighted_edit_atoms(self) -> list[dict]:
        out: list[dict] = []
        for sel in self._residue_highlight or []:
            if not isinstance(sel, dict):
                continue
            if sel.get("atom") or sel.get("serial") not in (None, ""):
                out.append(sel)
        return out

    def _merge_structure_edit_pick(self, sel: dict) -> list[dict]:
        """Accumulate up to two atoms when Edit Structure is on."""
        if not self._edit_structure_enabled():
            return [sel]
        current = self._highlighted_edit_atoms()
        pick_id = _atom_pick_id(sel)
        kept = [item for item in current if _atom_pick_id(item) != pick_id]
        if len(kept) != len(current):
            return kept
        if len(current) >= 2:
            return [sel]
        return current + [sel]

    def _structure_edit_status_text(self, sels: list[dict]) -> str:
        if not sels:
            return ""
        if len(sels) == 1:
            return self._atom_status_text(sels[0])
        left = self._atom_status_text(sels[0])
        right = self._atom_status_text(sels[1])
        return f"{left}  —  {right}"

    def _sync_structure_edit_actions(self) -> None:
        atoms = self._highlighted_edit_atoms()
        delete_act = getattr(self, "_act_delete_atoms", None)
        if delete_act is not None:
            delete_act.setEnabled(bool(atoms))
        pair_ok = self._bond_edit_pair() is not None
        add_act = getattr(self, "_act_add_bond", None)
        drop_act = getattr(self, "_act_delete_bond", None)
        if add_act is not None:
            add_act.setEnabled(pair_ok)
        if drop_act is not None:
            drop_act.setEnabled(pair_ok)

    def _on_edit_structure_toggled(self, checked: bool) -> None:
        atoms = self._highlighted_edit_atoms()
        if not checked and len(atoms) > 1:
            self._set_residue_highlight(atoms[-1:])
            self._set_atom_status(self._atom_status_text(atoms[-1]))
        hint = "Edit Structure on: click two atoms to pick a bond." if checked else ""
        if hint and not self._atom_status.text():
            self._set_atom_status(hint)
        self._sync_structure_edit_actions()

    def _slot_by_structure_id(self, structure_id: str):
        sid = str(structure_id or "")
        if sid:
            for slot in self._slots:
                if slot.structure_id == sid:
                    return slot
        return self._active_slot()

    def _bond_edit_pair(self) -> tuple[dict, dict] | None:
        atoms = self._highlighted_edit_atoms()
        if len(atoms) != 2:
            return None
        left, right = atoms
        if str(left.get("structure_id") or "") != str(right.get("structure_id") or ""):
            return None
        if left.get("kind") != "ligand" or right.get("kind") != "ligand":
            return None
        if _sel_atom_key(left) == _sel_atom_key(right):
            return None
        return left, right

    def delete_selected(self) -> None:
        if self._highlighted_edit_atoms():
            self.delete_highlighted_atoms()
            return
        self.delete_selected_chains()

    def delete_highlighted_atoms(self) -> None:
        atoms = self._highlighted_edit_atoms()
        if not atoms:
            return
        labels = [self._atom_status_text(sel) or str(sel.get("atom") or "") for sel in atoms]
        preview = ", ".join(part for part in labels if part)
        n = len(atoms)
        msg = f"Delete {n} selected atom{'s' if n != 1 else ''} from the structure?"
        if preview:
            msg += f"\n\n{preview}"
        if (
            QMessageBox.question(
                self, "Delete atoms", msg, QMessageBox.Yes | QMessageBox.No, QMessageBox.No
            )
            != QMessageBox.Yes
        ):
            return
        before = copy_loaded_slots(self._slots)
        by_slot: dict[str, set[tuple[str, str, str, str]]] = {}
        js_sels: list[dict] = []
        for sel in atoms:
            slot = self._slot_by_structure_id(str(sel.get("structure_id") or ""))
            if slot is None:
                continue
            by_slot.setdefault(slot.structure_id, set()).add(_sel_atom_key(sel))
            js_sels.append(_viewer_atom_sel(sel))
        if not by_slot:
            return
        for slot in self._slots:
            keys = by_slot.get(slot.structure_id)
            if not keys:
                continue
            if _slot_is_cif(slot.fmt):
                slot.text = delete_cif_atoms(slot.text, keys)
            else:
                slot.text = delete_pdb_atoms(slot.text, keys)
            self._invalidate_hbonds(slot.structure_id)
        self._push_manager_delete_undo(before, copy_loaded_slots(self._slots))
        if js_sels:
            self.viewer.delete_residues(js_sels)
        remain = [
            sel
            for sel in (self._residue_highlight or [])
            if _sel_atom_key(sel) not in {key for keys in by_slot.values() for key in keys}
        ]
        self._set_residue_highlight(remain)
        self._set_atom_status(self._structure_edit_status_text(self._highlighted_edit_atoms()))
        self._refresh_sequence_chains()
        self._refresh_pocket_overlays(zoom=False)
        if self._hbond_kinds_enabled():
            self._push_hbonds()
        self._sync_structure_edit_actions()
        self._mark_viewer_unsaved()

    def add_highlighted_bond(self) -> None:
        self._edit_highlighted_bond(add=True)

    def delete_highlighted_bond(self) -> None:
        self._edit_highlighted_bond(add=False)

    def _edit_highlighted_bond(self, *, add: bool) -> None:
        pair = self._bond_edit_pair()
        if pair is None:
            atoms = self._highlighted_edit_atoms()
            if len(atoms) != 2:
                QMessageBox.information(
                    self,
                    "Bond",
                    "Turn on Edit → Edit Structure and click two ligand atoms.",
                )
                return
            if atoms[0].get("kind") != "ligand" or atoms[1].get("kind") != "ligand":
                QMessageBox.information(
                    self,
                    "Bond",
                    "Bond editing is for ligands. Protein bonds come from residue templates.",
                )
                return
            QMessageBox.information(
                self,
                "Bond",
                "Pick two ligand atoms in the same loaded structure.",
            )
            return
        left, right = pair
        slot = self._slot_by_structure_id(str(left.get("structure_id") or ""))
        if slot is None:
            return
        name_a = str(left.get("atom") or "").strip()
        name_b = str(right.get("atom") or "").strip()
        if not name_a or not name_b:
            return
        if _slot_is_cif(slot.fmt):
            resn_a = str(left.get("resn") or "").strip().upper()
            resn_b = str(right.get("resn") or "").strip().upper()
            if not resn_a or resn_a != resn_b:
                QMessageBox.information(
                    self,
                    "Bond",
                    "mmCIF ligand bonds are stored per residue name (_chem_comp_bond). "
                    "Pick two atoms in the same residue.",
                )
                return
        before = copy_loaded_slots(self._slots)
        if _slot_is_cif(slot.fmt):
            resn = str(left.get("resn") or "").strip().upper()
            if add:
                slot.text = add_cif_chem_bond(slot.text, resn, name_a, name_b)
            else:
                slot.text = remove_cif_chem_bond(slot.text, resn, name_a, name_b)
        else:
            serial_a = pdb_serial_for_atom(slot.text, _sel_atom_key(left))
            serial_b = pdb_serial_for_atom(slot.text, _sel_atom_key(right))
            if serial_a is None or serial_b is None:
                QMessageBox.warning(self, "Bond", "Could not find those atoms in the PDB file.")
                return
            if add:
                slot.text = add_pdb_conect(slot.text, serial_a, serial_b)
            else:
                slot.text = remove_pdb_conect(slot.text, serial_a, serial_b)
        self._invalidate_hbonds(slot.structure_id)
        self._push_manager_delete_undo(before, copy_loaded_slots(self._slots))
        edit_bond = getattr(self.viewer, "edit_bond", None)
        if callable(edit_bond):
            edit_bond(
                {
                    "a": _viewer_atom_sel(left),
                    "b": _viewer_atom_sel(right),
                    "action": "add" if add else "remove",
                    "order": 1,
                }
            )
        if _slot_is_cif(slot.fmt):
            self._push_structure(refit=False)
        dlg = getattr(self, "_sequence_dialog", None)
        if dlg is not None and not qobject_is_deleted(dlg):
            self._refresh_sequence_chains()
        if self._hbond_kinds_enabled():
            self._push_hbonds()
        self._mark_viewer_unsaved()
