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
import logging

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QKeySequence
from PyQt5.QtWidgets import (
    QAction,
    QActionGroup,
    QDialog,
    QMenuBar,
    QShortcut,
    QSplitter,
    QVBoxLayout,
)

from ..structure_components import PolymerChain, cif_viewer_bond_tables
from .protein_chain_manager import ProteinChainManager
from .protein_embed import ProteinEmbedView
from .protein_sequence import ProteinSequenceDialog
from .protein_viewer_io_mixin import ProteinViewerIoMixin
from .protein_viewer_models import _LoadedSlot, _RENDER_COLOR_SPEC
from .protein_viewer_sequence_mixin import ProteinViewerSequenceMixin
from .protein_viewer_style_mixin import ProteinViewerStyleMixin
from .qt_widget_utils import make_window_minimizable

logger = logging.getLogger(__name__)


class ProteinViewerDialog(
    ProteinViewerIoMixin,
    ProteinViewerStyleMixin,
    ProteinViewerSequenceMixin,
    QDialog,
):
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
