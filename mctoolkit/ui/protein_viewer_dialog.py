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


"""Standalone Protein Viewer window (Mol* canvas + SBDD tools)."""

from __future__ import annotations

import base64
import logging
import sys
from dataclasses import replace
from datetime import datetime

from PySide6.QtCore import QEventLoop, Qt, QTimer
from PySide6.QtGui import (
    QCloseEvent,
    QKeySequence,
    QAction,
    QShortcut,
)
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QLabel,
    QMenuBar,
    QMessageBox,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..app_identity import APP_DISPLAY_NAME
from ..platform_support.session_log import record_ui_log
from ..protein.structure_components import PolymerChain, parse_polymer_sequences
from .protein_chain_manager import ProteinChainManager
from .protein_embed import ProteinEmbedView
from .protein_viewer_edit_mixin import ProteinViewerEditMixin
from .protein_viewer_io_mixin import ProteinViewerIoMixin
from .protein_viewer_models import NamedManagerGroup, _LoadedSlot, copy_loaded_slots
from .protein_viewer_pharmacophore_mixin import ProteinViewerPharmacophoreMixin
from .protein_viewer_style_mixin import ProteinViewerStyleMixin
from .qt_widget_utils import apply_monospace_to_text_edit, make_window_minimizable

logger = logging.getLogger(__name__)


class ProteinViewerDialog(
    ProteinViewerEditMixin,
    ProteinViewerIoMixin,
    ProteinViewerStyleMixin,
    ProteinViewerPharmacophoreMixin,
    QDialog,
):
    """Standalone Protein → Viewer window (Mol* canvas + SBDD tools).

    Mixin bases are a file-split of this dialog (IO/style/pharmacophore).
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._init_viewer_state(parent)
        self._build_viewer_ui()

    def _init_viewer_state(self, parent) -> None:
        self.setWindowTitle("Protein Viewer")
        self.resize(1180, 760)
        make_window_minimizable(self)

        self._slots: list[_LoadedSlot] = []
        self._slot_seq = 0
        self._named_groups: list[NamedManagerGroup] = []
        self._group_seq = 0
        self._manager_delete_undo: list[tuple[list[_LoadedSlot], list[_LoadedSlot]]] = []
        self._manager_delete_redo: list[tuple[list[_LoadedSlot], list[_LoadedSlot]]] = []
        self._act_undo: QAction | None = None
        self._act_redo: QAction | None = None
        self._act_edit_structure: QAction | None = None
        self._act_delete_atoms: QAction | None = None
        self._act_add_bond: QAction | None = None
        self._act_delete_bond: QAction | None = None
        self._sequence_chains: list[PolymerChain] = []
        self._sequence_dialog = None
        self._prepare_dialog = None
        self._pdbfixer_dialog = None
        self._pdb2pqr_dialog = None
        self._minimize_dialog = None
        self._mmgbsa_dialog = None
        self._md_dialog = None
        self._md_analysis_dialog = None
        self._dock_file_dialog = None
        self._act_dock_viewer: QAction | None = None
        self._residue_highlight: list[dict] = []
        self._syncing_from_atom = False
        self._pocket_payload_data: dict | None = None
        self._pocket_surface_payload: dict | None = None
        self._pocket_surface_settings: dict = {}
        self._pocket_surface_dialog = None
        self._pharmacophore = None
        self._pharmacophore_path: str | None = None
        self._pharmacophore_temp_path: str | None = None
        self._pharmacophore_dialog = None
        self._pharmacophore_overlay_visible = False
        self._docking_box_payload: dict | None = None
        self._dock_pose_payload: dict | None = None
        self._dock_pose_mol = None
        self._dock_pose_overlay = None
        self._dock_pose_overlay_gen = 0
        self._protein_style_actions: dict[str, QAction] = {}
        self._ligand_style_actions: dict[str, QAction] = {}
        self._protein_color_actions: dict[str, QAction] = {}
        self._ligand_color_actions: dict[str, QAction] = {}
        self._act_hydrogens_all: QAction | None = None
        self._act_hydrogens_polar: QAction | None = None
        self._act_hydrogens_none: QAction | None = None
        self._hydrogen_mode_actions: dict[str, list[QAction]] = {
            "all": [],
            "polar": [],
            "none": [],
        }
        self._act_hbond_protein: QAction | None = None
        self._act_hbond_ligand: QAction | None = None
        self._act_hbond_complex: QAction | None = None
        self._act_interact_hydrophobic: QAction | None = None
        self._act_interact_ionic: QAction | None = None
        self._act_interact_pi_stacking: QAction | None = None
        self._act_interact_pi_cation: QAction | None = None
        self._act_interact_halogen: QAction | None = None
        self._act_pocket_surface: QAction | None = None
        self._act_docking_box: QAction | None = None
        self._hbond_cache: dict[str, tuple] = {}
        self._prolif_cache: dict[str, tuple] = {}
        self._prolif_missing_logged = False
        self._overlay_job_gen = 0
        self._session_dirty = False
        self._canvas_load_depth = 0
        self._canvas_bootstrapped = False
        self._waiting_for_web = False
        self._pending_session_state = None
        self._pending_after_bootstrap: list = []
        self._suppress_close_prompt = "pytest" in sys.modules
        if parent is not None:
            self._suppress_close_prompt = bool(
                getattr(parent, "_suppress_exit_session_prompt", self._suppress_close_prompt)
            )

    def _build_viewer_ui(self) -> None:
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
        act_save.setToolTip("Write the last loaded structure to disk as PDB or mmCIF.")
        file_menu.addAction(act_save)
        act_save_session = QAction("Save to Session", self, triggered=self.save_viewer_to_session)
        act_save_session.setToolTip(
            f"Write the current Protein Viewer into the open {APP_DISPLAY_NAME} session. "
            "Closing without this leaves the session unchanged."
        )
        file_menu.addAction(act_save_session)
        act_export = QAction("Export &Image…", self, triggered=self.export_canvas_image)
        file_menu.addAction(act_export)
        file_menu.addSeparator()
        act_traj = QAction("Open &Trajectory…", self, triggered=self.open_trajectory_dialog)
        file_menu.addAction(act_traj)
        act_map = QAction("Open &Map…", self, triggered=self.open_map_dialog)
        file_menu.addAction(act_map)
        file_menu.addSeparator()
        act_close = QAction("&Close Structure", self, triggered=self.close_structure)
        file_menu.addAction(act_close)
        edit_menu = menubar.addMenu("&Edit")
        self._act_undo = QAction("&Undo", self, triggered=self.undo_manager_delete)
        self._act_undo.setShortcut(QKeySequence.Undo)
        self._act_undo.setToolTip("Undo the last atom, bond, or Manager chain edit.")
        self._act_undo.setEnabled(False)
        edit_menu.addAction(self._act_undo)
        self._act_redo = QAction("&Redo", self, triggered=self.redo_manager_delete)
        self._act_redo.setShortcut(QKeySequence.Redo)
        self._act_redo.setToolTip("Redo the last atom, bond, or Manager chain edit.")
        self._act_redo.setEnabled(False)
        edit_menu.addAction(self._act_redo)
        edit_menu.addSeparator()
        self._act_edit_structure = QAction("Edit &Structure", self, checkable=True)
        self._act_edit_structure.setToolTip(
            "Click a second atom to pick a ligand bond. Delete removes the current 3D selection."
        )
        self._act_edit_structure.toggled.connect(self._on_edit_structure_toggled)
        edit_menu.addAction(self._act_edit_structure)
        self._act_delete_atoms = QAction(
            "Delete &Atom(s)", self, triggered=self.delete_highlighted_atoms
        )
        self._act_delete_atoms.setToolTip("Remove the highlighted atom(s) from the structure file.")
        self._act_delete_atoms.setEnabled(False)
        edit_menu.addAction(self._act_delete_atoms)
        self._act_add_bond = QAction("&Add Bond", self, triggered=self.add_highlighted_bond)
        self._act_add_bond.setToolTip(
            "Add a ligand bond between the two highlighted atoms (PDB CONECT or mmCIF _chem_comp_bond)."
        )
        self._act_add_bond.setEnabled(False)
        edit_menu.addAction(self._act_add_bond)
        self._act_delete_bond = QAction(
            "Delete &Bond", self, triggered=self.delete_highlighted_bond
        )
        self._act_delete_bond.setToolTip(
            "Remove the ligand bond between the two highlighted atoms."
        )
        self._act_delete_bond.setEnabled(False)
        edit_menu.addAction(self._act_delete_bond)
        tools_menu = menubar.addMenu("&Tools")
        tools_menu.setToolTipsVisible(True)
        prepare_menu = tools_menu.addMenu("&Prepare")
        prepare_menu.setToolTipsVisible(True)
        act_fast_prepare = QAction("&Fast Prepare…", self, triggered=self.open_prepare_dialog)
        act_fast_prepare.setToolTip(
            "Repair missing atoms, strip waters/heterogens, protonate at pH, and relax with OpenMM."
        )
        prepare_menu.addAction(act_fast_prepare)
        act_pdbfixer = QAction("&PDBFixer…", self, triggered=self.open_pdbfixer_dialog)
        act_pdbfixer.setToolTip(
            "Repair missing atoms and strip waters/heterogens. No protonation or minimization."
        )
        prepare_menu.addAction(act_pdbfixer)
        act_pdb2pqr = QAction("pdb&2pqr…", self, triggered=self.open_pdb2pqr_dialog)
        act_pdb2pqr.setToolTip(
            "Assign protonation states at a chosen pH with pdb2pqr/PROPKA. "
            "No PDBFixer repair or minimization."
        )
        prepare_menu.addAction(act_pdb2pqr)
        act_minimize = QAction("&Minimize…", self, triggered=self.open_minimize_dialog)
        act_minimize.setToolTip(
            "Restrained OpenMM minimization of the loaded protein–ligand complex (GAFF2)."
        )
        prepare_menu.addAction(act_minimize)
        act_dock_file = QAction("&Dock File…", self, triggered=self.open_dock_file_dialog)
        act_dock_file.setToolTip(
            "Write Gnina receptor PDBQT, crystal ligand, and search box from a ready "
            "structure, then open Protein → Dock Ligand → Gnina filled in (crystal "
            "ligand is kept for internal validation)."
        )
        prepare_menu.addAction(act_dock_file)
        simulate_menu = tools_menu.addMenu("&Simulate")
        simulate_menu.setToolTipsVisible(True)
        dock_menu = simulate_menu.addMenu("&Dock Ligand")
        dock_menu.setToolTipsVisible(True)
        dock_prepare = dock_menu.addMenu("Prepare")
        dock_prepare.setToolTipsVisible(True)
        act_pdbqt = QAction("PDBQT…", self, triggered=self.open_dock_prepare)
        act_pdbqt.setToolTip(
            "Generate receptor and/or ligand PDBQT (receptor PDB; ligand SDF, PDB, "
            "SMILES, or table rows)."
        )
        dock_prepare.addAction(act_pdbqt)
        act_rec_pdb = QAction("Receptor PDB…", self, triggered=self.open_dock_prepare_pdb)
        act_rec_pdb.setToolTip(
            "Clean a receptor PDB with PDBFixer (remove ligands/waters, add atoms "
            "and hydrogens) before PDBQT conversion or docking."
        )
        dock_prepare.addAction(act_rec_pdb)
        dock_menu.addSeparator()
        act_gnina = QAction("Gnina…", self, triggered=self.open_gnina_dock)
        act_gnina.setToolTip("Run Gnina as a file-based CLI (CNN scoring; no table writeback).")
        dock_menu.addAction(act_gnina)
        dock_menu.addSeparator()
        self._act_dock_viewer = QAction(
            "Pose Browser", self, triggered=self.open_dock_results_viewer
        )
        self._act_dock_viewer.setToolTip(
            "Show the pose browser for the last docking run, even after it has been closed."
        )
        self._act_dock_viewer.setEnabled(False)
        dock_menu.addAction(self._act_dock_viewer)
        self._sync_dock_viewer_action()
        simulate_menu.addSeparator()
        act_mmgbsa = QAction("&MM-GBSA…", self, triggered=self.open_mmgbsa_dialog)
        act_mmgbsa.setToolTip(
            "1-trajectory MM-GBSA (OpenMM GBn2) on the loaded protein–ligand complex."
        )
        simulate_menu.addAction(act_mmgbsa)
        act_md = QAction("Molecular &Dynamics…", self, triggered=self.open_md_dialog)
        act_md.setToolTip("OpenMM MD (implicit GBSA or TIP3P PME), with optional snapshot MM-GBSA.")
        simulate_menu.addAction(act_md)
        act_md_an = QAction("&Analyze Trajectory…", self, triggered=self.open_md_analysis_dialog)
        act_md_an.setToolTip(
            "RMSD, RMSF, and energy vs time from an MD DCD. Not a trajectory player."
        )
        simulate_menu.addAction(act_md_an)
        pharma_menu = tools_menu.addMenu("&Pharmacophore")
        pharma_menu.setToolTipsVisible(True)
        act_pharma_edit = QAction("&Editor", self, triggered=self.open_pharmacophore_dialog)
        act_pharma_edit.setToolTip(
            "Place and edit pharmacophore features, save them, and send them to Gnina."
        )
        pharma_menu.addAction(act_pharma_edit)
        act_pharma_screen = QAction(
            "Screen &Table…", self, triggered=self.screen_pharmacophore_table
        )
        act_pharma_screen.setToolTip(
            "Screen packed table ensembles (confs / superpose / poses) against this pharmacophore."
        )
        pharma_menu.addAction(act_pharma_screen)
        act_pharma_open = QAction("&Open…", self, triggered=self.open_pharmacophore_file)
        act_pharma_open.setToolTip("Load a saved pharmacophore JSON onto the canvas.")
        pharma_menu.addAction(act_pharma_open)
        view_menu = menubar.addMenu("&View")
        self._act_docking_box = QAction("&Docking Box", self)
        self._act_docking_box.setCheckable(True)
        self._act_docking_box.setToolTip(
            "Show the Gnina search box written by Prepare (ligand bounding box + padding)."
        )
        self._act_docking_box.toggled.connect(self._on_docking_box_toggled)
        view_menu.addAction(self._act_docking_box)
        self._act_reset_camera = QAction("Reset Camera", self, triggered=self._reset_camera)
        self._act_reset_camera.setToolTip("Restore the fitted Mol* camera.")
        view_menu.addAction(self._act_reset_camera)
        if sys.platform == "win32":
            menubar.setNativeMenuBar(False)
        root.setMenuBar(menubar)

        splitter = QSplitter(Qt.Horizontal)
        self._main_splitter = splitter
        self.viewer = ProteinEmbedView(self)
        self.viewer.atom_picked.connect(self._on_atom_picked)
        self.viewer.delete_requested.connect(self.delete_selected)
        self.viewer.undo_requested.connect(self.undo_manager_delete)
        self.viewer.redo_requested.connect(self.redo_manager_delete)
        self.viewer.web_ready.connect(self._on_canvas_web_ready)
        self.manager = ProteinChainManager(self)
        self.manager.setVisible(False)
        self.manager.selection_changed.connect(self._on_manager_selection)
        self.manager.delete_requested.connect(self.delete_selected_chains)
        self.manager.duplicate_requested.connect(self.duplicate_selected)
        self.manager.add_to_group_requested.connect(self._on_add_to_group)
        self.manager.remove_from_group_requested.connect(self._on_remove_from_group)
        self.manager.rename_group_requested.connect(self._on_rename_group)
        self.manager.delete_group_requested.connect(self._on_delete_group)

        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setMinimumHeight(36)
        self.log.setPlaceholderText(
            "Progress from Fast Prepare, PDBFixer, pdb2pqr, Minimize, MM-GBSA, MD, and Gnina appears here."
        )
        apply_monospace_to_text_edit(self.log)
        self.log.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.log.document().setDocumentMargin(2)

        self._atom_status = QLabel("")
        self._atom_status.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._atom_status.setStyleSheet("padding: 0px 6px; color: palette(window-text);")
        self._atom_status.setToolTip("Clicked atom in the 3D view.")

        canvas_host = QWidget(self)
        canvas_host.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        canvas_ly = QVBoxLayout(canvas_host)
        canvas_ly.setContentsMargins(0, 0, 0, 0)
        canvas_ly.setSpacing(0)
        canvas_ly.addWidget(self.viewer, 1)
        canvas_ly.addWidget(self._atom_status)

        vsplit = QSplitter(Qt.Vertical)
        self._log_splitter = vsplit
        vsplit.addWidget(canvas_host)
        vsplit.addWidget(self.log)
        vsplit.setHandleWidth(3)
        vsplit.setStretchFactor(0, 1)
        vsplit.setStretchFactor(1, 0)
        vsplit.setSizes([800, 48])
        vsplit.setChildrenCollapsible(False)

        splitter.addWidget(vsplit)
        splitter.addWidget(self.manager)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        splitter.setSizes([1180, 0])
        splitter.setChildrenCollapsible(False)

        self._loading_page = QWidget()
        load_lyt = QVBoxLayout(self._loading_page)
        load_lyt.setContentsMargins(0, 0, 0, 0)
        load_lyt.addStretch()
        self._loading_detail = QLabel("")
        self._loading_detail.setAlignment(Qt.AlignCenter)
        self._loading_detail.setWordWrap(True)
        self._loading_detail.setStyleSheet("font-size: 14px; color: palette(mid); padding: 24px;")
        load_lyt.addWidget(self._loading_detail)
        load_lyt.addStretch()

        self._workspace_ready_page = QWidget()
        ready_lyt = QVBoxLayout(self._workspace_ready_page)
        ready_lyt.setContentsMargins(0, 0, 0, 0)
        ready_lyt.setSpacing(0)
        ready_lyt.addWidget(splitter, 1)

        self._content_stack = QStackedWidget()
        self._content_stack.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._content_stack.addWidget(self._loading_page)
        self._content_stack.addWidget(self._workspace_ready_page)
        self._content_stack.setCurrentIndex(1)
        root.addWidget(self._content_stack, 1)

        QShortcut(QKeySequence.Delete, self, activated=self.delete_selected)
        QShortcut(QKeySequence("Backspace"), self, activated=self.delete_selected)

    def refresh_theme(self) -> None:
        """Recolor Mol* chrome after a GUI theme or application font change."""
        viewer = getattr(self, "viewer", None)
        apply = getattr(viewer, "apply_theme", None)
        if callable(apply):
            apply()

    def canvas_loading_visible(self) -> bool:
        """True while the loading page covers the 3D canvas and Manager."""
        stack = getattr(self, "_content_stack", None)
        try:
            return stack is not None and int(stack.currentIndex()) == 0
        except RuntimeError:
            return False

    def begin_canvas_load(self, message: str, *, paint: bool = True) -> None:
        """Cover the canvas with the session/table-style loading page (nested)."""
        depth = int(getattr(self, "_canvas_load_depth", 0))
        self._canvas_load_depth = depth + 1
        label = getattr(self, "_loading_detail", None)
        if label is not None and (message or "").strip():
            try:
                label.setText(message)
            except RuntimeError:
                pass
        stack = getattr(self, "_content_stack", None)
        if stack is not None:
            try:
                stack.setCurrentIndex(0)
            except RuntimeError:
                return
        if paint:
            self.flush_canvas_load_paint()

    def end_canvas_load(self) -> None:
        """Reveal the canvas when the outermost load finishes."""
        depth = max(0, int(getattr(self, "_canvas_load_depth", 0)) - 1)
        self._canvas_load_depth = depth
        if depth:
            return
        stack = getattr(self, "_content_stack", None)
        if stack is None:
            return
        try:
            stack.setCurrentIndex(1)
        except RuntimeError:
            pass

    def flush_canvas_load_paint(self) -> None:
        """Paint the loading page before a blocking restore or file parse."""
        if not self.isVisible() or not self.canvas_loading_visible():
            return
        try:
            self.repaint()
        except RuntimeError:
            return
        QApplication.processEvents(QEventLoop.ExcludeUserInputEvents)

    def set_pending_session_state(self, state: dict | None) -> None:
        """Queue a session snapshot to apply after the window has been shown."""
        self._pending_session_state = state if isinstance(state, dict) else None

    def queue_after_canvas_bootstrap(self, callback) -> None:
        """Run ``callback`` after session restore during the first canvas start."""
        if not callable(callback):
            return
        if self._canvas_bootstrapped:
            callback()
            return
        self._pending_after_bootstrap.append(callback)

    def schedule_canvas_bootstrap(self) -> None:
        """Start the 3D canvas after the dialog chrome has a chance to paint."""
        if self._canvas_bootstrapped:
            return
        if "pytest" in sys.modules:
            self._bootstrap_canvas()
            return
        QTimer.singleShot(0, self._bootstrap_canvas)

    def _bootstrap_canvas(self) -> None:
        if self._canvas_bootstrapped:
            return
        self._canvas_bootstrapped = True
        try:
            self.viewer._ensure_web()
        except Exception:
            logger.exception("Protein viewer canvas bootstrap failed")
        pending = self._pending_session_state
        self._pending_session_state = None
        if isinstance(pending, dict) and pending.get("structures"):
            try:
                self.apply_session_state(pending)
                self._session_dirty = False
            except Exception:
                logger.exception("Protein viewer session restore failed")
        elif self._slots:
            try:
                self._push_structure(refit=True)
            except Exception:
                logger.exception("Protein viewer canvas restore failed")
        queued = list(self._pending_after_bootstrap)
        self._pending_after_bootstrap.clear()
        for callback in queued:
            try:
                callback()
            except Exception:
                logger.exception("Protein viewer post-bootstrap callback failed")
        web = getattr(self.viewer, "_web", None)
        web_ready = bool(getattr(self.viewer, "_web_ready", False))
        if web_ready or web is None or "pytest" in sys.modules:
            self._waiting_for_web = False
            self._release_open_overlay()
            return
        self._waiting_for_web = True
        QTimer.singleShot(8000, self._on_canvas_web_ready)

    def _on_canvas_web_ready(self) -> None:
        if not self._waiting_for_web:
            return
        self._waiting_for_web = False
        self._release_open_overlay()

    def _release_open_overlay(self) -> None:
        while int(getattr(self, "_canvas_load_depth", 0)) > 0:
            self.end_canvas_load()

    def append_log(self, text: str) -> None:
        """Append a timestamped line to the viewer log and the session Log window."""
        t = (text or "").rstrip()
        if not t:
            return
        stamp = datetime.now().strftime("%H:%M:%S")
        self.log.append(f"[{stamp}] {t}")
        record_ui_log(t, name="mctoolkit.ui.protein_viewer")

    def _reset_camera(self) -> None:
        self.viewer.reset_camera()

    def _slot_model_payload(self, slot: _LoadedSlot) -> dict:
        return {
            "data": base64.b64encode(slot.text.encode("utf-8")).decode("ascii"),
            "fmt": slot.fmt,
            "name": slot.name,
            "id": slot.structure_id,
        }

    def _push_structure(self, *, refit: bool, camera=None, append_from: int | None = None) -> None:
        if not self._slots:
            self.viewer.clear_structures()
            return
        web_ready = bool(getattr(self.viewer, "_web_ready", False))
        can_append = (
            append_from is not None
            and append_from > 0
            and append_from < len(self._slots)
            and web_ready
        )
        models = [
            self._slot_model_payload(slot)
            for slot in (self._slots[append_from:] if can_append else self._slots)
        ]
        payload = {"models": models, "refit": bool(refit)}
        if can_append:
            self.viewer.add_structures(payload)
        else:
            self.viewer.load_structures(payload)
        box = self._docking_box_overlay_payload()
        if box:
            self.viewer.set_docking_box(box)
        pose = self._dock_pose_overlay_payload()
        if pose:
            self.viewer.set_dock_pose(pose)
        pharma = self._pharmacophore_overlay_payload()
        if pharma and pharma.get("active"):
            self.viewer.set_pharmacophore(pharma)

    def _schedule_canvas_structure_push(self, *, refit: bool = False) -> None:
        self._pending_canvas_refit = bool(getattr(self, "_pending_canvas_refit", False) or refit)
        if "pytest" in sys.modules:
            self._flush_canvas_structure_push()
            return
        timer = getattr(self, "_canvas_push_timer", None)
        if timer is None:
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.setInterval(50)
            timer.timeout.connect(self._flush_canvas_structure_push)
            self._canvas_push_timer = timer
        timer.start()

    def _flush_canvas_structure_push(self) -> None:
        refit = bool(getattr(self, "_pending_canvas_refit", False))
        self._pending_canvas_refit = False
        if not self._slots:
            return
        self._push_structure(refit=refit)

    def _push_states(self) -> None:
        self._mark_viewer_unsaved()

    def _refresh_sequence_chains(self, force: bool = False) -> None:
        """Parse polymer sequences for Protein → Sequence MSA (Mol* owns the Sequence panel)."""
        del force
        filtered: list[PolymerChain] = []
        for model, slot in enumerate(self._slots):
            fmt = "cif" if slot.fmt == "cif" else "pdb"
            for poly in parse_polymer_sequences(slot.text, fmt):
                residues = [
                    replace(res, structure_id=slot.structure_id, model=model)
                    for res in poly.residues
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

    def _on_sequence_deleted(self, residues: list) -> None:
        if not residues:
            return
        sels = []
        for res in residues:
            sel = res.selection()
            sel["structure_id"] = res.structure_id
            sel["kind"] = res.kind
            sel["resn"] = res.resn
            sels.append(sel)
        self.delete_residue_selections(sels, confirm=False)

    def _sync_sequence_dialog(self) -> None:
        return

    def _selected_component_ids(self) -> list[str]:
        return self.manager.selected_component_ids() or [
            r.spec.component_id for r in self._rows if r.selected
        ]

    def _clear_manager_delete_history(self) -> None:
        self._manager_delete_undo = []
        self._manager_delete_redo = []
        self._sync_manager_edit_actions()

    def _sync_manager_edit_actions(self) -> None:
        undo = getattr(self, "_act_undo", None)
        redo = getattr(self, "_act_redo", None)
        if undo is not None:
            undo.setEnabled(bool(self._manager_delete_undo))
        if redo is not None:
            redo.setEnabled(bool(self._manager_delete_redo))

    def _push_manager_delete_undo(
        self,
        before: list[_LoadedSlot],
        after: list[_LoadedSlot],
    ) -> None:
        self._manager_delete_undo.append((before, after))
        if len(self._manager_delete_undo) > 50:
            self._manager_delete_undo = self._manager_delete_undo[-50:]
        self._manager_delete_redo = []
        self._sync_manager_edit_actions()

    def _restore_manager_slots(self, slots: list[_LoadedSlot]) -> None:
        self._slots = copy_loaded_slots(slots)
        self._reindex_models()
        self._residue_highlight = []
        self._set_atom_status("")
        if not self._slots:
            self.close_structure(keep_edit_history=True)
            return
        self._refresh_manager()
        self._refresh_sequence_chains()
        self._push_structure(refit=False)
        self._mark_viewer_unsaved()
        sync_edit = getattr(self, "_sync_structure_edit_actions", None)
        if callable(sync_edit):
            sync_edit()

    def undo_manager_delete(self) -> None:
        if not self._manager_delete_undo:
            return
        before, after = self._manager_delete_undo.pop()
        self._manager_delete_redo.append((before, after))
        self._restore_manager_slots(before)
        self._sync_manager_edit_actions()

    def redo_manager_delete(self) -> None:
        if not self._manager_delete_redo:
            return
        before, after = self._manager_delete_redo.pop()
        self._manager_delete_undo.append((before, after))
        self._restore_manager_slots(after)
        self._sync_manager_edit_actions()

    def _hydrogen_mode(self) -> str:
        return "polar"

    def _hbond_kinds_enabled(self) -> set:
        return set()

    def _interaction_overlay_active(self) -> bool:
        return False

    def _hbond_payload_for_structure_push(self) -> dict:
        return {"active": False, "bonds": []}

    def _pocket_surface_overlay_payload(self):
        return {"active": False}

    def _refresh_pocket_overlays(self, *, zoom: bool = False) -> None:
        return

    def _invalidate_hbonds(self, structure_id: str | None = None) -> None:
        return

    def _push_hbonds(self) -> None:
        return

    def _drop_overlay_structures(self, sids) -> None:
        return

    def _enable_protein_ligand_interactions_for_complex(self) -> None:
        return

    def _checked_style(self, actions, default: str) -> str:
        return default

    def _check_style_action(self, actions, key: str) -> None:
        return

    def _on_visibility_changed(self, *_a) -> None:
        return

    def _on_manager_selection(self, ids: list) -> None:
        want = set(ids)
        for slot in self._slots:
            slot.rows = [replace(row, selected=row.spec.component_id in want) for row in slot.rows]
        if not self._syncing_from_atom and self._residue_highlight:
            self._residue_highlight = []
            self._set_atom_status("")

    def focus_selected(self) -> None:
        return

    def invert_selection(self) -> None:
        return

    def clear_selection(self) -> None:
        """Clear the 3D pick highlight and any Manager row selection."""
        for slot in self._slots:
            slot.rows = [replace(row, selected=False) for row in slot.rows]
        self._residue_highlight = []
        self._set_atom_status("")

    def delete_selected_chains(self) -> None:
        if self.manager.selected_items_are_groups_only():
            for gid in self.manager.selected_user_group_ids():
                self._on_delete_group(gid)
            return
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
        before = copy_loaded_slots(self._slots)
        drop = set(ids)
        kept: list[_LoadedSlot] = []
        for slot in self._slots:
            rows = [r for r in slot.rows if r.spec.component_id not in drop]
            if rows:
                slot.rows = rows
                kept.append(slot)
        self._slots = kept
        reindex = getattr(self, "_reindex_models", None)
        if callable(reindex):
            reindex()
        self._push_manager_delete_undo(before, copy_loaded_slots(self._slots))
        if not self._slots:
            self.close_structure(keep_edit_history=True)
            return
        self._refresh_manager()
        self._refresh_sequence_chains()
        schedule = getattr(self, "_schedule_canvas_structure_push", None)
        if callable(schedule):
            schedule(refit=False)
        else:
            self._push_structure(refit=False)
        self._mark_viewer_unsaved()

    def dock_side_widget(self, widget) -> bool:
        """Dock a panel as a full-height Manager page and show it."""
        dock = getattr(self.manager, "dock_widget", None)
        if not callable(dock) or not dock(widget):
            return False
        self.manager.setVisible(True)
        self._widen_manager_for_side_dock()
        sync = getattr(widget, "_sync_footer_chrome", None)
        if callable(sync):
            sync()
        return True

    def show_side_widget(self, widget) -> bool:
        """Show a Manager page (chain list or a docked panel)."""
        show = getattr(self.manager, "show_widget", None)
        return callable(show) and bool(show(widget))

    def undock_side_widget(self, widget) -> bool:
        """Remove a panel from the Manager dock without destroying it."""
        undock = getattr(self.manager, "undock_widget", None)
        if not callable(undock):
            return False
        ok = bool(undock(widget))
        if ok:
            sync = getattr(widget, "_sync_footer_chrome", None)
            if callable(sync):
                sync()
            if not self.side_docked_widgets():
                self.manager.setVisible(False)
                splitter = getattr(self, "_main_splitter", None)
                if splitter is not None:
                    sizes = splitter.sizes()
                    if len(sizes) >= 2:
                        splitter.setSizes([sizes[0] + sizes[1], 0])
        return ok

    def close_side_dock_widget(self, widget) -> bool:
        """Close and destroy a panel docked in the Manager."""
        if not self.is_side_docked(widget):
            return False
        closer = getattr(widget, "on_docked_plot_closing", None)
        if callable(closer):
            closer()
        self.undock_side_widget(widget)
        try:
            widget.close()
            widget.deleteLater()
        except RuntimeError:
            pass
        return True

    def is_side_docked(self, widget) -> bool:
        check = getattr(self.manager, "is_docked", None)
        return callable(check) and bool(check(widget))

    def side_docked_widgets(self) -> list:
        lister = getattr(self.manager, "docked_widgets", None)
        if callable(lister):
            return list(lister())
        return []

    def _widen_manager_for_side_dock(self) -> None:
        splitter = getattr(self, "_main_splitter", None)
        if splitter is None:
            return
        sizes = splitter.sizes()
        if len(sizes) < 2:
            return
        if sizes[1] >= 380:
            return
        extra = 380 - sizes[1]
        splitter.setSizes([max(sizes[0] - extra, 400), 380])

    def _float_side_docks(self) -> None:
        """Reparent Manager-docked panels into floating windows before this viewer closes."""
        for widget in list(self.side_docked_widgets()):
            app = getattr(widget, "parent_app", None)
            factory = getattr(widget, "create_floating_dialog", None)
            self.undock_side_widget(widget)
            if app is None or not callable(factory):
                continue
            dlg = factory(app)
            from .pose_browser import PoseBrowserDialog

            if isinstance(dlg, PoseBrowserDialog):
                setattr(app, "_pose_browser_dialog", dlg)
                slot = getattr(app, "_on_pose_browser_dialog_destroyed", None)
                if callable(slot):
                    try:
                        dlg.destroyed.disconnect(slot)
                    except TypeError:
                        pass
                    dlg.destroyed.connect(slot)
            try:
                dlg.show()
            except RuntimeError:
                pass

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._sync_dock_viewer_action()
        prepare = getattr(self.viewer, "prepare_to_show", None)
        if callable(prepare):
            prepare()
        if not self._canvas_bootstrapped:
            self.schedule_canvas_bootstrap()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        if not self.confirm_close_or_save_to_session():
            event.ignore()
            return
        self._float_side_docks()
        clearer = getattr(self, "clear_dock_pose", None)
        if callable(clearer):
            clearer()
        shutdown = getattr(self.viewer, "shutdown_web", None)
        if callable(shutdown):
            shutdown()
        self._canvas_bootstrapped = False
        self._waiting_for_web = False
        super().closeEvent(event)
