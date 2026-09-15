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

"""Smina dock, PDBQT/PDB prepare, and dock-results windows."""

from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QMessageBox

from rdkit import Chem

from ..singleton_modeless_dialog import reuse_or_show_modeless_singleton

_DOCK_RESULT_WINDOWS: list = []


def _copy_dock_pose_mols(mols: list) -> list:
    """Independent RDKit copies so the results viewer can reopen after the window is closed."""
    out: list = []
    for mol in mols or []:
        if mol is None:
            continue
        try:
            out.append(Chem.Mol(mol))
        except Exception:
            continue
    return out


class DockToolsMixin:
    def open_dock_results_window(
        self,
        mols: list,
        *,
        title: str = "Dock results",
        receptor_path: str | None = None,
    ):
        """Open a new main-table window populated with docked poses and Smina fields."""
        from ...dock_io import dock_result_headers
        from .chemical_table_app import ChemicalTableApp

        usable = [m for m in (mols or []) if m is not None]
        if not usable:
            return None
        self._last_dock_results = {
            "mols": _copy_dock_pose_mols(usable),
            "title": title,
            "receptor_path": (receptor_path or "").strip() or None,
        }
        act = getattr(self, "_act_dock_viewer", None)
        if act is not None:
            try:
                act.setEnabled(True)
            except RuntimeError:
                pass
        win = ChemicalTableApp()
        win.apply_dock_results_chrome()
        win.setWindowTitle(f"MolManager — {title}")
        win.setAttribute(Qt.WA_DeleteOnClose, True)
        headers = dock_result_headers(usable)
        win.headers = headers
        win._table_model.set_headers(list(headers))
        win.table.setColumnHidden(0, True)
        prepared: list[tuple[int, dict[str, str]]] = []
        pose_map: dict[int, Chem.Mol] = {}
        for mol in usable:
            oid = win.next_oid
            win.next_oid += 1
            pose_map[oid] = mol
            prepared.append((oid, win._ingest_store_mol(oid, mol)))
        win._dock_pose_mols = pose_map
        win._table_model.append_rows_batch(prepared, defer_color_cache=True)
        for oid, _cells in prepared:
            stored = win.mols.get(oid)
            if stored is not None:
                win.start_render_worker(oid, stored, skip_mol_props=True)
        rebuild = getattr(win._table_model, "rebuild_column_color_caches_after_bulk_load", None)
        if callable(rebuild):
            rebuild()
        schedule = getattr(win, "schedule_calculate_global_bounds", None)
        if callable(schedule):
            schedule()
        n = len(usable)
        win.status_label.setText(f"{n} docked pose(s).")
        win._install_dock_complex_pane(receptor_path)
        if n:
            win.select_table_rows([0])
            win._sync_dock_complex_viewer()
        win.show()
        win.raise_()
        win.activateWindow()
        _DOCK_RESULT_WINDOWS.append(win)
        if not hasattr(self, "_dock_result_windows"):
            self._dock_result_windows = []
        self._dock_result_windows.append(win)

        def _drop(*_a, w=win, parent=self) -> None:
            for lst in (_DOCK_RESULT_WINDOWS, getattr(parent, "_dock_result_windows", None)):
                if not lst:
                    continue
                try:
                    lst.remove(w)
                except ValueError:
                    pass

        try:
            win.destroyed.connect(_drop)
        except Exception:
            pass
        return win

    def _live_dock_result_windows(self) -> list:
        """Dock-results windows that still have a live C++ object."""
        from ..qt_widget_utils import qobject_is_deleted

        live: list = []
        for w in list(getattr(self, "_dock_result_windows", []) or []):
            if qobject_is_deleted(w):
                continue
            live.append(w)
        self._dock_result_windows = live
        return live

    def open_dock_results_viewer(self):
        """Raise the last docking results window, or recreate it after it was closed."""
        live = self._live_dock_result_windows()
        if live:
            win = live[-1]
            try:
                win.show()
                win.raise_()
                win.activateWindow()
            except RuntimeError:
                pass
            else:
                return win
        snap = getattr(self, "_last_dock_results", None) or {}
        mols = list(snap.get("mols") or [])
        if not mols:
            QMessageBox.information(
                self,
                "Dock Viewer",
                "No docking results to show. Run Smina first.",
            )
            return None
        return self.open_dock_results_window(
            _copy_dock_pose_mols(mols),
            title=str(snap.get("title") or "Dock results"),
            receptor_path=snap.get("receptor_path"),
        )

    def _install_dock_complex_pane(self, receptor_path: str | None) -> None:
        """Put a 3Dmol receptor+ligand view to the left of this table."""
        from PyQt5.QtWidgets import QSplitter

        from ..dock_complex_viewer import DockComplexEmbedView

        if getattr(self, "_dock_complex_viewer", None) is not None:
            viewer = self._dock_complex_viewer
            setter = getattr(viewer, "set_receptor_path", None)
            if callable(setter):
                setter(receptor_path)
            return
        content_h = getattr(self, "_content_h", None)
        workspace = getattr(self, "_workspace_column", None)
        if content_h is None or workspace is None:
            return
        viewer = DockComplexEmbedView(self)
        viewer.set_receptor_path(receptor_path)
        splitter = QSplitter(Qt.Horizontal)
        splitter.setObjectName("DockComplexSplitter")
        splitter.setChildrenCollapsible(False)
        content_h.removeWidget(workspace)
        splitter.addWidget(viewer)
        splitter.addWidget(workspace)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)
        splitter.setSizes([520, 980])
        content_h.insertWidget(0, splitter, 1)
        self._dock_complex_viewer = viewer
        self._dock_complex_splitter = splitter
        try:
            self.resize(max(self.width(), 1680), max(self.height(), 900))
        except Exception:
            pass

    def _dock_complex_current_oid(self) -> int | None:
        table = getattr(self, "table", None)
        model = getattr(self, "_table_model", None)
        if table is None or model is None:
            return None
        idx = table.currentIndex()
        if idx.isValid():
            proxy = getattr(self, "_filter_proxy_model", None)
            src = proxy.mapToSource(idx) if proxy is not None else idx
            try:
                return int(model.row_oid(src.row()))
            except Exception:
                pass
        oids = self._selected_oids_set() if hasattr(self, "_selected_oids_set") else set()
        if oids:
            return min(int(x) for x in oids)
        return None

    def _sync_dock_complex_viewer(self) -> None:
        viewer = getattr(self, "_dock_complex_viewer", None)
        if viewer is None:
            return
        pose_map = getattr(self, "_dock_pose_mols", None) or {}
        oid = self._dock_complex_current_oid()
        mol = pose_map.get(oid) if oid is not None else None
        if mol is None and pose_map:
            mol = next(iter(pose_map.values()))
        setter = getattr(viewer, "set_ligand_mol", None)
        if callable(setter):
            setter(mol)

    def open_smina_dock(self):
        from ..dialogs.smina_dock import SminaDockDialog

        dlg = reuse_or_show_modeless_singleton(
            self,
            "_smina_dock_dialog",
            lambda: SminaDockDialog(self),
            self._on_smina_dock_dialog_destroyed,
        )
        dlg.setAttribute(Qt.WA_DeleteOnClose, True)
        self._prepare_tool_dialog(dlg)
        return dlg

    def open_dock_prepare(self):
        from ..dialogs.pdbqt_generator import PdbqtGeneratorDialog

        dlg = reuse_or_show_modeless_singleton(
            self,
            "_pdbqt_generator_dialog",
            lambda: PdbqtGeneratorDialog(self),
            self._on_pdbqt_generator_dialog_destroyed,
        )
        dlg.setAttribute(Qt.WA_DeleteOnClose, True)
        self._prepare_tool_dialog(dlg)

    def open_dock_prepare_pdb(self):
        from ..dialogs.pdb_fixer import PdbFixerDialog

        dlg = reuse_or_show_modeless_singleton(
            self,
            "_pdb_fixer_dialog",
            lambda: PdbFixerDialog(self),
            self._on_pdb_fixer_dialog_destroyed,
        )
        dlg.setAttribute(Qt.WA_DeleteOnClose, True)
        self._prepare_tool_dialog(dlg)
