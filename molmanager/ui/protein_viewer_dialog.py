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


"""Standalone Protein Viewer window (3D canvas + chain Manager)."""

from __future__ import annotations


import base64
import json
import logging
from dataclasses import replace
from pathlib import Path

from PyQt5.QtCore import QByteArray, Qt
from PyQt5.QtGui import QColor, QKeySequence
from PyQt5.QtWidgets import (
    QAction,
    QActionGroup,
    QColorDialog,
    QDialog,
    QFileDialog,
    QMenuBar,
    QMessageBox,
    QShortcut,
    QSplitter,
    QVBoxLayout,
)

from ..hydrogen_bonds import (
    HBOND_KIND_COMPLEX,
    HBOND_KIND_LIGAND,
    HBOND_KIND_PROTEIN,
    detect_hydrogen_bonds,
)
from ..structure_components import (
    LoadedStructure,
    PolymerChain,
    cif_viewer_bond_tables,
    component_id_for_atom,
    delete_pdb_residues,
    letter_to_resn,
    load_structure_file,
    parse_polymer_sequences,
    parse_structure_components,
    pocket_view_plan,
    polymer_residue_for_atom,
    rewrite_pdb_residue_names,
    scope_structure_component,
)
from .protein_chain_manager import ProteinChainManager
from .protein_embed import ProteinEmbedView
from .protein_sequence import ProteinSequenceDialog
from .protein_viewer_models import (
    COMPONENT_COLOR_CHOICES,
    COMPONENT_STYLE_CHOICES,
    STRUCTURE_FILE_FILTER,
    STRUCTURE_SAVE_FILTER,
    _ComponentView,
    _LoadedSlot,
    _RENDER_COLOR_SPEC,
    _component_state_key,
)
from .qt_widget_utils import make_window_minimizable, qobject_is_deleted

logger = logging.getLogger(__name__)


class ProteinViewerDialog(QDialog):
    """Standalone Protein → Viewer window (3D canvas + chain Manager)."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Protein Viewer")
        self.resize(1180, 760)
        make_window_minimizable(self)

        self._slots: list[_LoadedSlot] = []
        self._slot_seq = 0
        self._sequence_chains: list[PolymerChain] = []
        self._sequence_dialog: ProteinSequenceDialog | None = None
        self._prepare_dialog = None
        self._residue_highlight: list[dict] = []
        self._syncing_from_atom = False
        self._pocket_payload_data: dict | None = None
        self._protein_style_actions: dict[str, QAction] = {}
        self._ligand_style_actions: dict[str, QAction] = {}
        self._protein_color_actions: dict[str, QAction] = {}
        self._ligand_color_actions: dict[str, QAction] = {}
        self._act_hydrogens_all: QAction | None = None
        self._act_hydrogens_polar: QAction | None = None
        self._act_hbond_protein: QAction | None = None
        self._act_hbond_ligand: QAction | None = None
        self._act_hbond_complex: QAction | None = None
        self._hbond_cache: dict[str, tuple] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        menubar = QMenuBar(self)
        file_menu = menubar.addMenu("&File")
        act_open = QAction("&Open…", self, triggered=self.open_structure_dialog)
        act_open.setShortcut(QKeySequence.Open)
        file_menu.addAction(act_open)
        act_save = QAction("&Save Structure…", self, triggered=self.save_structure_dialog)
        act_save.setShortcut(QKeySequence.Save)
        act_save.setToolTip(
            "Write the Manager-selected structure (or the last loaded file) to disk."
        )
        file_menu.addAction(act_save)
        act_close = QAction("&Close Structure", self, triggered=self.close_structure)
        file_menu.addAction(act_close)
        act_sequence = QAction("&Sequence", self, triggered=self.open_sequence_window)
        act_sequence.setToolTip("Show the editable amino-acid sequence and select residues in 3D.")
        menubar.addAction(act_sequence)
        act_prepare = QAction("&Prepare…", self, triggered=self.open_prepare_dialog)
        act_prepare.setToolTip(
            "Repair missing atoms, strip waters/heterogens, protonate at pH, and relax with OpenMM."
        )
        menubar.addAction(act_prepare)
        view_menu = menubar.addMenu("&View")
        render_menu = view_menu.addMenu("&Render")
        protein_menu = render_menu.addMenu("&Protein")
        self._protein_style_actions = self._add_render_style_menu(
            protein_menu,
            kind="polymer",
            default="cartoon",
        )
        protein_menu.addSeparator()
        self._protein_color_actions = self._add_render_color_menu(
            protein_menu.addMenu("&Color"),
            kind="polymer",
        )
        ligand_menu = render_menu.addMenu("&Ligand")
        self._ligand_style_actions = self._add_render_style_menu(
            ligand_menu,
            kind="ligand",
            default="ballstick",
        )
        ligand_menu.addSeparator()
        self._ligand_color_actions = self._add_render_color_menu(
            ligand_menu.addMenu("&Color"),
            kind="ligand",
        )
        hydrogens_menu = view_menu.addMenu("&Hydrogens")
        hydrogen_group = QActionGroup(self)
        hydrogen_group.setExclusive(True)
        self._act_hydrogens_all = QAction("&All", self)
        self._act_hydrogens_all.setCheckable(True)
        self._act_hydrogens_all.setToolTip("Show all explicit hydrogens on the 3D canvas.")
        self._act_hydrogens_polar = QAction("&Polar", self)
        self._act_hydrogens_polar.setCheckable(True)
        self._act_hydrogens_polar.setChecked(True)
        self._act_hydrogens_polar.setToolTip("Show only polar hydrogens (bonded to N, O, S, or F).")
        hydrogen_group.addAction(self._act_hydrogens_all)
        hydrogen_group.addAction(self._act_hydrogens_polar)
        hydrogens_menu.addAction(self._act_hydrogens_all)
        hydrogens_menu.addAction(self._act_hydrogens_polar)
        self._act_hydrogens_all.triggered.connect(lambda: self._set_hydrogen_mode("all"))
        self._act_hydrogens_polar.triggered.connect(lambda: self._set_hydrogen_mode("polar"))
        hbonds_menu = view_menu.addMenu("Hydrogen &Bonds")
        self._act_hbond_protein = QAction("&Protein", self)
        self._act_hbond_protein.setCheckable(True)
        self._act_hbond_protein.setToolTip(
            "Show intramolecular hydrogen bonds within protein chains (gold)."
        )
        self._act_hbond_ligand = QAction("&Ligand", self)
        self._act_hbond_ligand.setCheckable(True)
        self._act_hbond_ligand.setToolTip(
            "Show intramolecular hydrogen bonds within ligands (cyan)."
        )
        self._act_hbond_complex = QAction("Protein–&Ligand", self)
        self._act_hbond_complex.setCheckable(True)
        self._act_hbond_complex.setToolTip(
            "Show intermolecular hydrogen bonds between protein and ligand (green)."
        )
        hbonds_menu.addAction(self._act_hbond_protein)
        hbonds_menu.addAction(self._act_hbond_ligand)
        hbonds_menu.addAction(self._act_hbond_complex)
        self._act_hbond_protein.toggled.connect(self._on_hbond_toggles)
        self._act_hbond_ligand.toggled.connect(self._on_hbond_toggles)
        self._act_hbond_complex.toggled.connect(self._on_hbond_toggles)
        self._act_pocket = QAction("&Pocket", self)
        self._act_pocket.setToolTip(
            "Zoom to the ligand, show nearby protein residues as ball-and-stick "
            "with residue labels, and display explicit polar hydrogens."
        )
        self._act_pocket.triggered.connect(self._on_pocket)
        view_menu.addAction(self._act_pocket)
        view_menu.addSeparator()
        self._act_all_atoms = QAction("All &Atoms", self)
        self._act_all_atoms.setCheckable(True)
        self._act_all_atoms.setToolTip(
            "Draw protein residues as ball-and-stick (all atoms) instead of a ribbon cartoon."
        )
        self._act_all_atoms.toggled.connect(self._on_all_atoms_toggled)
        view_menu.addAction(self._act_all_atoms)
        view_menu.addSeparator()
        view_menu.addAction(QAction("Reset Camera", self, triggered=self._reset_camera))
        select_menu = menubar.addMenu("&Select")
        act_hide = QAction("&Hide", self, triggered=lambda: self._set_selected_visible(False))
        act_hide.setToolTip("Hide the chains selected in the Manager.")
        select_menu.addAction(act_hide)
        act_show = QAction("&Show", self, triggered=lambda: self._set_selected_visible(True))
        act_show.setToolTip("Show the chains selected in the Manager.")
        select_menu.addAction(act_show)
        act_focus = QAction("&Focus", self, triggered=self.focus_selected)
        act_focus.setToolTip("Zoom the 3D view to the Manager selection.")
        select_menu.addAction(act_focus)
        act_delete = QAction("&Delete", self, triggered=self.delete_selected)
        act_delete.setToolTip("Remove the Manager selection from the viewer.")
        select_menu.addAction(act_delete)
        select_menu.addSeparator()
        self._add_select_style_menu(select_menu.addMenu("&Render"))
        self._add_select_color_menu(select_menu.addMenu("&Color"))
        root.setMenuBar(menubar)

        splitter = QSplitter(Qt.Horizontal)
        self.viewer = ProteinEmbedView(self)
        self.viewer.atom_picked.connect(self._on_atom_picked)
        self.manager = ProteinChainManager(self)
        self.manager.visibility_changed.connect(self._on_visibility_changed)
        self.manager.selection_changed.connect(self._on_manager_selection)
        self.manager.focus_requested.connect(self.focus_selected)
        splitter.addWidget(self.viewer)
        splitter.addWidget(self.manager)
        splitter.setStretchFactor(0, 4)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([860, 300])
        root.addWidget(splitter, 1)

        QShortcut(QKeySequence.Delete, self, activated=self.delete_selected)
        QShortcut(QKeySequence("Backspace"), self, activated=self.delete_selected)

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
        self._invalidate_hbonds()
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

    def open_sequence_window(self) -> None:
        """Open or raise the Sequence window for the current polymer chains."""
        dlg = self._sequence_dialog
        if dlg is not None and qobject_is_deleted(dlg):
            self._sequence_dialog = None
            dlg = None
        if dlg is None:
            dlg = ProteinSequenceDialog(self)
            dlg.residue_selection_changed.connect(self._on_sequence_selection)
            dlg.residues_mutated.connect(self._on_sequence_mutated)
            dlg.residues_deleted.connect(self._on_sequence_deleted)
            dlg.focus_residues_requested.connect(self._on_sequence_focus)
            dlg.destroyed.connect(self._on_sequence_dialog_destroyed)
            self._sequence_dialog = dlg
        dlg.set_chains(self._sequence_chains)
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()

    def _on_sequence_dialog_destroyed(self) -> None:
        self._sequence_dialog = None

    def _refresh_sequence_chains(self) -> None:
        filtered: list[PolymerChain] = []
        for model, slot in enumerate(self._slots):
            fmt = "cif" if slot.fmt == "cif" else "pdb"
            for poly in parse_polymer_sequences(slot.text, fmt):
                residues = [
                    replace(
                        res,
                        structure_id=slot.structure_id,
                        model=model,
                    )
                    for res in poly.residues
                    if self._sequence_residue_is_live(res, slot)
                ]
                if residues:
                    filtered.append(
                        PolymerChain(
                            chain=poly.chain,
                            residues=list(residues),
                            structure_id=slot.structure_id,
                            structure_name=slot.name,
                        )
                    )
        self._sequence_chains = filtered
        self._sync_sequence_dialog()

    def _sequence_residue_is_live(self, res, slot: _LoadedSlot) -> bool:
        rows = slot.rows
        if not rows:
            return False
        if res.kind in {"polymer", "missing"}:
            return any(row.spec.kind == "polymer" and row.spec.chain == res.chain for row in rows)
        if res.kind == "water":
            return any(row.spec.kind == "water" and row.spec.chain == res.chain for row in rows)
        return any(
            row.spec.kind == res.kind
            and row.spec.chain == res.chain
            and row.spec.resn == res.resn
            and row.spec.resi == res.resi
            for row in rows
        )

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

    def _sync_sequence_dialog(self) -> None:
        dlg = self._sequence_dialog
        if dlg is None or qobject_is_deleted(dlg):
            return
        dlg.set_chains(self._sequence_chains)

    def _set_residue_highlight(self, selections: list[dict]) -> None:
        self._residue_highlight = list(selections)
        self.viewer.set_residue_highlight(self._residue_highlight)

    def _on_sequence_selection(self, selections: list) -> None:
        self._set_residue_highlight(list(selections or []))

    def _on_sequence_focus(self, selections: list) -> None:
        if selections:
            self.viewer.zoom_to_selections(list(selections))

    def _slot_for_residue(self, residue) -> _LoadedSlot | None:
        sid = getattr(residue, "structure_id", "") or ""
        if sid:
            for slot in self._slots:
                if slot.structure_id == sid:
                    return slot
        return self._active_slot()

    def _on_sequence_mutated(self, items: list) -> None:
        payload = []
        by_slot: dict[str, list[tuple[str, str, str, str]]] = {}
        for residue, letter in items:
            resn = letter_to_resn(letter)
            if not resn:
                continue
            entry = {
                "chain": residue.chain,
                "resi": residue.selection().get("resi"),
                "icode": residue.icode,
                "resn": resn,
            }
            if residue.model is not None:
                entry["model"] = residue.model
            payload.append(entry)
            slot = self._slot_for_residue(residue)
            if slot is None:
                continue
            by_slot.setdefault(slot.structure_id, []).append(
                (residue.chain, residue.resi, residue.icode, resn)
            )
        if not payload:
            return
        for slot in self._slots:
            changes = by_slot.get(slot.structure_id)
            if changes and slot.fmt in {"pdb", "pqr"}:
                slot.text = rewrite_pdb_residue_names(slot.text, changes)
                self._invalidate_hbonds(slot.structure_id)
        self.viewer.mutate_residues(payload)
        dlg = self._sequence_dialog
        if dlg is not None and not qobject_is_deleted(dlg):
            self._sequence_chains = dlg.chains()
        if self._hbond_kinds_enabled():
            self._push_hbonds()

    def _on_sequence_deleted(self, residues: list) -> None:
        if not residues:
            return
        keys = {(res.chain, res.resi, res.icode) for res in residues}
        sels = [res.selection() for res in residues]
        by_slot: dict[str, set[tuple[str, str, str]]] = {}
        for res in residues:
            slot = self._slot_for_residue(res)
            if slot is None:
                continue
            by_slot.setdefault(slot.structure_id, set()).add((res.chain, res.resi, res.icode))
        for slot in self._slots:
            slot_keys = by_slot.get(slot.structure_id)
            if slot_keys and slot.fmt in {"pdb", "pqr"}:
                slot.text = delete_pdb_residues(slot.text, slot_keys)
                self._invalidate_hbonds(slot.structure_id)
        self.viewer.delete_residues(sels)
        self._residue_highlight = [
            sel
            for sel in self._residue_highlight
            if (str(sel.get("chain")), str(sel.get("resi")), str(sel.get("icode") or ""))
            not in {(k[0], k[1], k[2]) for k in keys}
        ]
        dlg = self._sequence_dialog
        if dlg is not None and not qobject_is_deleted(dlg):
            self._sequence_chains = dlg.chains()
        self.viewer.set_residue_highlight(self._residue_highlight)
        if self._hbond_kinds_enabled():
            self._push_hbonds()

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

    def _reset_camera(self) -> None:
        web = getattr(self.viewer, "_web", None)
        if web is None:
            return
        try:
            web.page().runJavaScript(
                "if (window.molmanagerResetStructure) window.molmanagerResetStructure();"
            )
        except Exception:
            logger.debug("Protein viewer reset camera failed", exc_info=True)

    def _component_payloads(self) -> list[dict]:
        out: list[dict] = []
        for row in self._rows:
            payload = row.spec.to_payload()
            payload["visible"] = row.visible
            payload["selected"] = row.selected
            payload["style"] = row.style
            scheme = row.color_scheme or "default"
            spec = _RENDER_COLOR_SPEC.get(scheme)
            if spec is not None:
                payload["cartoonColor"] = spec[0]
                payload["carbonScheme"] = spec[1]
            elif str(scheme).startswith("#"):
                payload["cartoonColor"] = scheme
                payload["carbonScheme"] = scheme
            out.append(payload)
        return out

    def _push_structure(self, *, refit: bool) -> None:
        models = []
        for slot in self._slots:
            model = {
                "data": base64.b64encode(slot.text.encode("utf-8")).decode("ascii"),
                "fmt": slot.fmt,
                "name": slot.name,
            }
            if slot.fmt == "cif":
                tables = cif_viewer_bond_tables(slot.text)
                if tables:
                    model["cifBonds"] = tables
            models.append(model)
        self.viewer.set_payload(
            {
                "models": models,
                "fmt": models[0]["fmt"] if models else "pdb",
                "data": models[0]["data"] if models else "",
                "components": self._component_payloads(),
                "residueHighlight": self._residue_highlight,
                "pocket": self._pocket_payload_data,
                "hbonds": self._hbond_overlay_payload(),
                "hydrogens": self._hydrogen_mode(),
                "refit": bool(refit),
            }
        )

    def _push_states(self) -> None:
        self.viewer.apply_component_states(self._component_payloads())
        if self._hbond_kinds_enabled():
            self._push_hbonds()
