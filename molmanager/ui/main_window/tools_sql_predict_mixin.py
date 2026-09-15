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
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with MolManager.  If not, see <https://www.gnu.org/licenses/>.

"""Calculator, SQL load, external DB, and prediction dialogs."""

from __future__ import annotations

import logging
import re
import sys
import threading
import time
from contextlib import nullcontext

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import QApplication, QMessageBox

from rdkit import Chem

from ...config import load_config
from ...services.sql_load_policy import engine_kwargs_for_sql_load, sql_looks_destructive
from ...display_constants import structure_depiict_height, structure_depiict_width
from ...utils import redact_sqlalchemy_url, safe_float
from ...workers.sql_load_worker import SqlLoadParseResult, SqlLoadSignals, SqlLoadWorker
from ..analysis_job_support import (
    enqueue_process_queue_job,
    ensure_table_ready_for_tool,
    report_cancellable_job_failure,
)
from ..background_jobs import register_background_job, unregister_background_job
from ..threadpool_access import start_runnable_on_app_pool

from ..singleton_modeless_dialog import reuse_or_show_modeless_singleton
from ..strings import (
    TOOL_CALCULATOR,
    TOOL_PREDICT_SOM,
    TOOL_RANDOM_NUMBER,
    TOOL_SPLIT_COLUMN,
    loaded_sql_status,
)
from ...workers import (
    CustomCalcWorker,
)

logger = logging.getLogger(__name__)

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


def som_map_export_filename(oid: int, header: str = "SOM Map") -> str:
    """Default PNG filename for a SOM Map cell export."""
    stem = re.sub(r"[^\w\-]+", "_", (header or "SOM_Map").strip()).strip("_") or "SOM_Map"
    return f"{stem}_{int(oid)}.png"


def save_som_map_pixmap(pm: QPixmap, path: str) -> str | None:
    """Write *pm* as PNG, appending ``.png`` when needed. Returns the path or ``None``."""
    out = (path or "").strip()
    if not out or pm is None or pm.isNull():
        return None
    if not out.lower().endswith(".png"):
        out += ".png"
    if not pm.save(out, "PNG"):
        return None
    return out


class ToolsSqlPredictMixin:
    def _run_calculator_from_dialog(self, dlg) -> None:
        from ..dialogs import CalculatorDialog

        if not isinstance(dlg, CalculatorDialog):
            return
        self.new_c = dlg.name_input.text().strip()
        if not self.new_c:
            QMessageBox.warning(self, TOOL_CALCULATOR, "Enter a name for the new column.")
            return
        self.new_c = self._unique_table_column_names([self.new_c])[0]
        expr = dlg.expr_input.text().strip()
        if not expr:
            QMessageBox.warning(self, TOOL_CALCULATOR, "Enter an expression to evaluate.")
            return
        only_selected = dlg.only_selected_rows()
        allowed = self._selected_oids_set() if only_selected else None
        if self._abort_if_only_selected_but_empty(only_selected, allowed, TOOL_CALCULATOR):
            return
        numeric_vars = list(self.global_bounds.keys())
        h_map = {h: i for i, h in enumerate(self.headers)}
        oids_list = self._all_oids_in_table_order()
        if allowed is not None:
            oids_list = [o for o in oids_list if o in allowed]
        row_data = [
            (
                o,
                {
                    v: (self._table_cell_text(self.logical_row_for_oid(o), h_map[v]) or "0")
                    for v in numeric_vars
                },
            )
            for o in oids_list
        ]
        if not row_data:
            QMessageBox.information(
                self,
                TOOL_CALCULATOR,
                "No rows to process for this scope.",
            )
            self.status_label.setText("Ready.")
            return
        ps = self._tool_progress_state
        self._begin_tool_progress("Calculator…", len(row_data))
        self.process_queue.enqueue(
            f"Calculator ({len(row_data)} rows)",
            lambda ev, rd=row_data, ex=expr, sigs=self.signals, p=ps: CustomCalcWorker(
                rd, ex, sigs, cancel_event=ev, progress_state=p
            ),
        )

    def open_random_number_dialog(self) -> None:
        if not self.headers or self._table_model.rowCount() == 0:
            QMessageBox.information(
                self,
                TOOL_RANDOM_NUMBER,
                "Load a table with at least one row first.",
            )
            return
        from ..dialogs import RandomNumberDialog

        d = RandomNumberDialog(len(self._selected_logical_rows()), self)
        self._prepare_tool_dialog(d)
        d.setAttribute(Qt.WA_DeleteOnClose, True)
        d.accepted.connect(lambda *_, dlg=d: self._on_random_number_dialog_accepted(dlg))
        d.show()

    def open_random_molecule_dialog(self) -> None:
        from ..dialogs import RandomMoleculeDialog

        d = RandomMoleculeDialog(self)
        self._prepare_tool_dialog(d)
        d.setAttribute(Qt.WA_DeleteOnClose, True)
        d.show()

    def _on_random_number_dialog_accepted(self, d) -> None:
        from ...random_numbers import generate_random_values

        p = d.params()
        col = p.column_name
        if not col:
            QMessageBox.warning(self, TOOL_RANDOM_NUMBER, "Enter a name for the output column.")
            return
        only_selected = d.only_selected_rows()
        allowed = self._selected_oids_set() if only_selected else None
        if self._abort_if_only_selected_but_empty(only_selected, allowed, TOOL_RANDOM_NUMBER):
            return
        oids = self._all_oids_in_table_order()
        if allowed is not None:
            oids = [o for o in oids if o in allowed]
        if not oids:
            QMessageBox.information(self, TOOL_RANDOM_NUMBER, "No rows to process for this scope.")
            self.status_label.setText("Ready.")
            return
        try:
            values = generate_random_values(len(oids), p.params)
        except ValueError as exc:
            QMessageBox.warning(
                self, TOOL_RANDOM_NUMBER, str(exc) or "Invalid random-number settings."
            )
            return
        rows = [(int(oid), {col: text}) for oid, text in zip(oids, values)]
        written = self.on_calc_finished(rows, [col], progress_label=TOOL_RANDOM_NUMBER)
        final_col = written[0] if written else col
        self.status_label.setText(
            f'{TOOL_RANDOM_NUMBER}: column "{final_col}" updated ({len(rows)} row(s)).'
        )

    def open_calculator(self):
        if not self.headers:
            return
        if load_config().disable_custom_calc:
            QMessageBox.information(
                self,
                TOOL_CALCULATOR,
                "The calculator is disabled by policy (environment variable MOLMANAGER_DISABLE_CUSTOM_CALC).",
            )
            return
        numeric_vars = list(self.global_bounds.keys())
        from ..dialogs import CalculatorDialog

        def _factory():
            d = CalculatorDialog(numeric_vars, len(self._selected_logical_rows()), self)
            d.setModal(False)
            d.setAttribute(Qt.WA_DeleteOnClose, True)
            d.apply_requested.connect(lambda dlg=d: self._run_calculator_from_dialog(dlg))
            self._prepare_tool_dialog(d)
            return d

        reuse_or_show_modeless_singleton(
            self,
            "_calculator_dialog",
            _factory,
            self._on_calculator_dialog_destroyed,
            on_reused_visible=lambda dlg: self._sync_dialog_only_selected_scope(dlg),
        )

    def _on_sketcher_dialog_destroyed(self):
        self._sketcher_dialog = None

    def _on_calculator_dialog_destroyed(self):
        self._calculator_dialog = None

    def _on_data_analysis_dialog_destroyed(self):
        self._data_analysis_dialog = None

    def open_data_analysis(self):
        if not self.headers or self._table_model.rowCount() == 0:
            QMessageBox.information(
                self, "Data", "Open a file or add rows so the table has data to analyze."
            )
            return
        from ..data_analysis import DataAnalysisDialog

        def _factory() -> DataAnalysisDialog:
            dlg = DataAnalysisDialog(self)
            self._prepare_tool_dialog(dlg)
            return dlg

        def _on_reused(dlg: DataAnalysisDialog) -> None:
            self._sync_dialog_only_selected_scope(dlg)
            dlg._sync_selected_columns_only_scope()
            dlg.refresh_table_data()

        reuse_or_show_modeless_singleton(
            self,
            "_data_analysis_dialog",
            _factory,
            self._on_data_analysis_dialog_destroyed,
            on_reused_visible=_on_reused,
        )

    def open_split_column_dialog(self) -> None:
        if not self.headers or self._table_model.rowCount() == 0:
            QMessageBox.information(
                self,
                TOOL_SPLIT_COLUMN,
                "Open a file or add rows so the table has a column to split.",
            )
            return
        columns = self._filterable_data_column_names()
        if not columns:
            QMessageBox.information(
                self,
                TOOL_SPLIT_COLUMN,
                "No text columns are available to split.",
            )
            return
        from ..dialogs import SplitColumnDialog

        d = SplitColumnDialog(columns, len(self._selected_logical_rows()), self)
        self._prepare_tool_dialog(d)
        d.setAttribute(Qt.WA_DeleteOnClose, True)
        d.accepted.connect(lambda *_, dlg=d: self._on_split_column_dialog_accepted(dlg))
        d.show()

    def _on_split_column_dialog_accepted(self, d) -> None:
        from ...column_split import (
            MAX_SPLIT_COLUMNS,
            apply_keep_mode,
            output_column_names,
            pad_split_rows,
            split_column_values,
            split_width,
        )

        p = d.params()
        source = p.source_column
        if not source or source not in self.headers:
            QMessageBox.warning(self, TOOL_SPLIT_COLUMN, "Choose a column to split.")
            return
        only_selected = d.only_selected_rows()
        allowed = self._selected_oids_set() if only_selected else None
        if self._abort_if_only_selected_but_empty(only_selected, allowed, TOOL_SPLIT_COLUMN):
            return
        oids = self._all_oids_in_table_order()
        if allowed is not None:
            oids = [o for o in oids if o in allowed]
        if not oids:
            QMessageBox.information(self, TOOL_SPLIT_COLUMN, "No rows to process for this scope.")
            return
        try:
            ci = self.headers.index(source)
        except ValueError:
            QMessageBox.warning(self, TOOL_SPLIT_COLUMN, "Choose a column to split.")
            return
        texts: list[str] = []
        for oid in oids:
            row = self._table_model.logical_row_for_oid(int(oid))
            if row < 0:
                texts.append("")
                continue
            raw = self._table_model.backing_value_for_row_header(row, source) or ""
            if not raw:
                raw = self._table_cell_text(row, ci) or ""
            texts.append(raw)
        try:
            _delim, parts = split_column_values(texts, p.mode, custom=p.custom)
        except ValueError as exc:
            QMessageBox.warning(self, TOOL_SPLIT_COLUMN, str(exc) or "Could not split the column.")
            return
        keep = getattr(p, "keep", "all") or "all"
        if keep in ("largest", "smallest"):
            parts = apply_keep_mode(parts, keep)
        n_cols = split_width(parts)
        if keep == "all" and n_cols < 2:
            QMessageBox.information(
                self,
                TOOL_SPLIT_COLUMN,
                "No split fields were found. Check the separator and try again.",
            )
            return
        if n_cols < 1:
            QMessageBox.information(
                self,
                TOOL_SPLIT_COLUMN,
                "No values were found. Check the separator and try again.",
            )
            return
        truncated = any(len(row) > MAX_SPLIT_COLUMNS for row in parts)
        padded = pad_split_rows(parts, n_cols)
        if keep in ("largest", "smallest"):
            headers = [p.prefix or source]
        else:
            headers = output_column_names(p.prefix or source, n_cols)
        rows = [
            (int(oid), {headers[i]: padded[j][i] for i in range(n_cols)})
            for j, oid in enumerate(oids)
        ]
        written = self.on_calc_finished(rows, headers, progress_label=TOOL_SPLIT_COLUMN)
        extra = f" (capped at {n_cols})" if truncated else ""
        self.status_label.setText(
            f'{TOOL_SPLIT_COLUMN}: {len(written)} column(s) from "{source}"{extra}.'
        )

    def open_plot(self):
        if not self.headers:
            return
        # Prefer opening a new floating plotter so multiple PlotWidgets can be docked.
        dlg = self._create_plot_dialog()
        self._register_plot_dialog(dlg)
        self._sync_dialog_only_selected_scope(dlg)
        self._sync_active_plots_from_table_selection()
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()

    def open_sketcher(self, mol=None):
        # QAction.triggered passes False; never treat that as a molecule.
        if mol is not None and not isinstance(mol, Chem.Mol):
            mol = None
        from ..sketcher import SketcherDialog

        def _on_reuse(dlg):
            if mol is not None:
                dlg.load_structure_from_mol(mol)

        reuse_or_show_modeless_singleton(
            self,
            "_sketcher_dialog",
            lambda: SketcherDialog(self, initial_mol=mol),
            self._on_sketcher_dialog_destroyed,
            on_reused_visible=_on_reuse if mol is not None else None,
        )

    def open_molecule_3d(self, mol=None, *, source_oid=None):
        if mol is not None and not isinstance(mol, Chem.Mol):
            mol = None
        if mol is None:
            return
        from ..mol_viewer_3d import open_molecule_3d_viewer

        open_molecule_3d_viewer(mol, self, title="View in 3D", source_oid=source_oid)

    def open_molecule_2d(self, mol=None, *, source_oid=None):
        if mol is not None and not isinstance(mol, Chem.Mol):
            mol = None
        if mol is None:
            return
        from ..mol_viewer_3d import open_molecule_2d_viewer

        open_molecule_2d_viewer(mol, self, title="View in 2D", source_oid=source_oid)

    def open_external_db(self):
        from ..external import ExternalDBDialog

        reuse_or_show_modeless_singleton(
            self,
            "_external_db_dialog",
            lambda: ExternalDBDialog(self),
            self._on_external_db_dialog_destroyed,
        )

    def open_pubchem(self):
        from ..external import PubChemDialog

        reuse_or_show_modeless_singleton(
            self,
            "_pubchem_dialog",
            lambda: PubChemDialog(self),
            self._on_pubchem_dialog_destroyed,
        )

    def open_chembl(self):
        from ..external import ChEMBLDialog

        reuse_or_show_modeless_singleton(
            self,
            "_chembl_dialog",
            lambda: ChEMBLDialog(self),
            self._on_chembl_dialog_destroyed,
        )

    def open_patent_query(self):
        from ..external import PatentQueryDialog

        reuse_or_show_modeless_singleton(
            self,
            "_patent_query_dialog",
            lambda: PatentQueryDialog(self),
            self._on_patent_query_dialog_destroyed,
        )

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
        from ..smina_dock import SminaDockDialog

        dlg = reuse_or_show_modeless_singleton(
            self,
            "_smina_dock_dialog",
            lambda: SminaDockDialog(self),
            self._on_smina_dock_dialog_destroyed,
        )
        dlg.setAttribute(Qt.WA_DeleteOnClose, True)
        self._prepare_tool_dialog(dlg)

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

    def _ensure_columns(self, col_names: list[str]) -> None:
        """Ensure the table has these headers (adds columns to the right if needed)."""
        if not self.headers:
            self.headers = ["ID_HIDDEN", "Structure", "SMILES"]
            self._table_model.set_headers(list(self.headers))
            self.table.setColumnHidden(0, True)
        existing = {h: i for i, h in enumerate(self.headers)}
        to_add = [h for h in col_names if h not in existing]
        if to_add:
            col_at = len(self.headers)
            self.headers.extend(to_add)
            self._table_model.insert_columns_at(col_at, to_add, None)

    def add_row_from_external_record(self, smiles: str, fields: dict[str, str]) -> None:
        """Append a row with SMILES + additional fields; render structure when possible."""
        smiles = (smiles or "").strip()
        if not smiles:
            raise ValueError("Empty SMILES.")
        self._ensure_columns(["SMILES"] + list(fields.keys()))

        self.table.setSortingEnabled(False)
        oid = self.next_oid
        self.next_oid += 1
        row_cells: dict[str, str] = {}
        for h in self.headers[2:]:
            if h == "SMILES":
                row_cells[h] = smiles
            else:
                row_cells[h] = str(fields.get(h, "") or "")
        self._table_model.append_row(oid, row_cells)

        mol = Chem.MolFromSmiles(smiles)
        if mol is not None:
            self.mols[oid] = mol
            self.start_render_worker(oid, mol)

        self._sync_global_bounds_for_headers(list(fields.keys()), refresh_filters=False)
        self.table.setSortingEnabled(False)

    def add_rows_from_external_records_batch(
        self,
        records: list[tuple[str, dict[str, str]]],
        *,
        render_structures: bool = True,
    ) -> int:
        """Append many external rows with one model notification (ChEMBL/PubChem/protomer adds)."""
        if not records:
            return 0
        field_names: set[str] = set()
        for _smi, fields in records:
            field_names.update(fields.keys())
        self._ensure_columns(["SMILES"] + sorted(field_names))
        prepared = self._prepare_external_record_rows(records)
        if not prepared:
            return 0
        if len(prepared) == 1 or getattr(self, "_external_append_active", False):
            if len(prepared) > 1 and getattr(self, "_external_append_active", False):
                queue = getattr(self, "_external_append_queue", None)
                if queue is None:
                    self._external_append_queue = []
                    queue = self._external_append_queue
                queue.append((records, render_structures))
                return len(prepared)
            return self._add_external_records_batch_sync(
                prepared, sorted(field_names), render_structures=render_structures
            )
        self._external_append_active = True
        self._external_append_prepared = prepared
        self._external_append_index = 0
        self._external_append_field_names = sorted(field_names)
        self._external_append_render = render_structures
        self.table.setSortingEnabled(False)
        QTimer.singleShot(0, self._process_external_records_append_chunk)
        return len(prepared)

    def _prepare_external_record_rows(
        self, records: list[tuple[str, dict[str, str]]]
    ) -> list[tuple[int, dict[str, str]]]:
        prepared: list[tuple[int, dict[str, str]]] = []
        for smiles, fields in records:
            smiles = (smiles or "").strip()
            if not smiles:
                continue
            oid = self.next_oid
            self.next_oid += 1
            row_cells: dict[str, str] = {}
            for h in self.headers[2:]:
                if h == "SMILES":
                    row_cells[h] = smiles
                else:
                    row_cells[h] = str(fields.get(h, "") or "")
            prepared.append((oid, row_cells))
        return prepared

    def _add_external_records_batch_sync(
        self,
        prepared: list[tuple[int, dict[str, str]]],
        field_names: list[str],
        *,
        render_structures: bool,
    ) -> int:
        """Append external rows immediately (small batches or when a deferred append is active)."""
        self.table.setSortingEnabled(False)
        try:
            self.table.setUpdatesEnabled(False)
        except Exception:
            pass
        new_mols: list[tuple[int, Chem.Mol]] = []
        if render_structures:
            for oid, row_cells in prepared:
                smi = (row_cells.get("SMILES", "") or "").strip()
                if not smi:
                    continue
                mol = Chem.MolFromSmiles(smi)
                if mol is not None:
                    new_mols.append((oid, mol))
        cfg = load_config()
        defer_color = len(prepared) >= int(cfg.bulk_update_defer_color_cache_rows)
        self._table_model.append_rows_batch(prepared, defer_color_cache=defer_color)
        for oid, mol in new_mols:
            self.mols[oid] = mol
            self.start_render_worker(oid, mol)
        if defer_color:
            self._table_model.rebuild_column_color_caches_after_bulk_load()
        self._sync_global_bounds_for_headers(field_names, refresh_filters=False)
        try:
            self.table.setUpdatesEnabled(True)
        except Exception:
            pass
        self.table.setSortingEnabled(False)
        return len(prepared)

    def _process_external_records_append_chunk(self) -> None:
        prepared = getattr(self, "_external_append_prepared", None)
        if not prepared:
            self._external_append_active = False
            return
        cfg = load_config()
        chunk_size = int(cfg.ingest_gui_chunk_size)
        budget_s = max(0.005, int(cfg.ingest_gui_time_budget_ms) / 1000.0)
        deadline = time.monotonic() + budget_s
        start = int(getattr(self, "_external_append_index", 0))
        try:
            self.table.setUpdatesEnabled(False)
        except Exception:
            pass
        batch_rows: list[tuple[int, dict[str, str]]] = []
        while (
            start < len(prepared) and len(batch_rows) < chunk_size and time.monotonic() < deadline
        ):
            batch_rows.append(prepared[start])
            start += 1
        self._external_append_index = start
        if batch_rows:
            self._table_model.append_rows_batch(batch_rows, defer_color_cache=True)
        try:
            self.table.setUpdatesEnabled(True)
        except Exception:
            pass
        if start < len(prepared):
            QTimer.singleShot(0, self._process_external_records_append_chunk)
        else:
            QTimer.singleShot(0, self._finalize_external_records_append)

    def _finalize_external_records_append(self) -> None:
        prepared = getattr(self, "_external_append_prepared", None) or []
        field_names = list(getattr(self, "_external_append_field_names", []) or [])
        render_structures = bool(getattr(self, "_external_append_render", False))
        oids = [oid for oid, _ in prepared]
        for attr in (
            "_external_append_prepared",
            "_external_append_index",
            "_external_append_field_names",
            "_external_append_render",
        ):
            try:
                delattr(self, attr)
            except AttributeError:
                pass
        self._external_append_active = False
        self.table.setSortingEnabled(False)
        self._table_model.rebuild_column_color_caches_after_bulk_load()
        QTimer.singleShot(
            0,
            lambda: self._sync_global_bounds_for_headers(field_names, refresh_filters=False),
        )
        if render_structures and oids:
            self._external_append_render_oids = list(oids)
            self._external_append_render_tasks = []
            self._external_append_render_row_by_oid = {}
            self._external_append_render_index = 0
            QTimer.singleShot(0, self._external_append_render_tasks_chunk)
        else:
            self._drain_external_append_queue()

    def _external_append_render_tasks_chunk(self) -> None:
        oids = getattr(self, "_external_append_render_oids", None)
        if not oids:
            self._drain_external_append_queue()
            return
        idx = int(getattr(self, "_external_append_render_index", 0))
        chunk = 64
        slice_oids = oids[idx : idx + chunk]
        base_w, base_h = structure_depiict_width(), structure_depiict_height()
        tasks, row_map = self._build_render2d_tasks_for_oids(slice_oids, base_w, base_h)
        self._external_append_render_tasks.extend(tasks)
        self._external_append_render_row_by_oid.update(row_map)
        idx += len(slice_oids)
        self._external_append_render_index = idx
        if idx < len(oids):
            QTimer.singleShot(0, self._external_append_render_tasks_chunk)
            return
        renders = list(getattr(self, "_external_append_render_tasks", []) or [])
        row_by_oid = dict(getattr(self, "_external_append_render_row_by_oid", {}) or {})
        for attr in (
            "_external_append_render_oids",
            "_external_append_render_tasks",
            "_external_append_render_row_by_oid",
            "_external_append_render_index",
        ):
            try:
                delattr(self, attr)
            except AttributeError:
                pass
        if renders:
            self._start_render_2d_batch(
                renders,
                row_by_oid,
                "Structure",
                column_pixmap_mode=False,
            )
        self._drain_external_append_queue()

    def _drain_external_append_queue(self) -> None:
        queue = getattr(self, "_external_append_queue", None)
        if not queue:
            return
        records, render_structures = queue.pop(0)
        if not queue:
            try:
                delattr(self, "_external_append_queue")
            except AttributeError:
                pass
        self.add_rows_from_external_records_batch(records, render_structures=render_structures)

    def load_from_sql(
        self,
        *,
        url: str,
        query: str | None = None,
        table: str | None = None,
        limit: int = 50000,
        apply_limit: bool = True,
        clear_first: bool = True,
        read_only: bool = True,
    ) -> None:
        """Load a SQL query/table into the main table.

        Fetch + SMILES parse run off the GUI thread; table appends are chunked on the
        GUI thread (same pattern as session restore). If a SMILES column exists
        (case-insensitive), molecules are created and 2D structures are drawn
        automatically after apply.

        ``read_only`` (default True) opens SQLite with ``mode=ro`` and refuses queries that
        look destructive. Uncheck read-only in the External SQL dialog only when you
        intentionally need a write connection.
        """
        try:
            from sqlalchemy import create_engine, text
        except Exception as e:
            raise RuntimeError(
                "sqlalchemy is required for SQL loading. Install requirements-core.txt "
                "(or requirements.txt)."
            ) from e

        if bool(query) == bool(table):
            raise ValueError("Provide exactly one of: query or table.")

        if table is not None:
            tname = str(table).strip()
            if re.fullmatch(r"[A-Za-z0-9_]+", tname) is None:
                raise ValueError(
                    "SQL table name may only contain letters, digits, and underscores (identifier guard)."
                )
            table = tname

        if query and sql_looks_destructive(query):
            if read_only:
                raise ValueError(
                    "This SQL looks like it may modify the database. "
                    "Uncheck “Read-only connection” in the External SQL dialog only if you "
                    "intentionally need a write connection, then confirm the warning."
                )
            r = QMessageBox.warning(
                self,
                "Destructive SQL",
                "This SQL looks like it may modify the database (INSERT/UPDATE/DELETE/DROP/…). "
                "MolManager is meant for loading query results into the table.\n\n"
                "Continue and run this statement anyway?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if r != QMessageBox.Yes:
                return

        sql_cfg = load_config()
        hard_cap = sql_cfg.sql_max_rows_hard
        precowarn = sql_cfg.sql_precount_warn
        try:
            li = int(limit) if limit is not None else 0
        except (TypeError, ValueError):
            li = 0
        if li > hard_cap:
            li = hard_cap
        if li < 0:
            li = 0

        logger.debug("load_from_sql url=%s read_only=%s", redact_sqlalchemy_url(url), read_only)

        out_url, eng_kw = engine_kwargs_for_sql_load(
            url,
            read_only=bool(read_only),
            sqlite_timeout_s=sql_cfg.sqlite_timeout_s,
            pg_connect_timeout=sql_cfg.pg_connect_timeout,
        )
        page_size = max(128, int(sql_cfg.sqlite_backend_page_size))
        limit_eff = int(li) if apply_limit and li else 0

        # Precount warning stays on the GUI (needs a modal confirm).
        if apply_limit and limit_eff > 0 and precowarn > 0:
            eng = create_engine(out_url, **eng_kw)
            try:
                with eng.connect() as conn:
                    est = None
                    try:
                        if table:
                            crow = (
                                conn.execute(text(f"SELECT COUNT(*) AS c FROM {table}"))
                                .mappings()
                                .first()
                            )
                            est = int(crow["c"]) if crow and crow.get("c") is not None else None
                        else:
                            base = (query or "").strip().rstrip(";")
                            if base:
                                crow = (
                                    conn.execute(
                                        text(f"SELECT COUNT(*) AS c FROM ({base}) AS __chem_cnt")
                                    )
                                    .mappings()
                                    .first()
                                )
                                est = int(crow["c"]) if crow and crow.get("c") is not None else None
                    except Exception:
                        est = None
                    if est is not None and est >= precowarn:
                        r = QMessageBox.question(
                            self,
                            "Large SQL result",
                            f"The data source reports about {est:,} row(s). Up to {limit_eff:,} row(s) will be fetched, "
                            "which may use significant time and memory.\n\nContinue?",
                            QMessageBox.Yes | QMessageBox.No,
                            QMessageBox.No,
                        )
                        if r != QMessageBox.Yes:
                            return
            finally:
                eng.dispose()

        if table:
            sql = f"SELECT * FROM {table}"
            if apply_limit and limit_eff:
                sql += f" LIMIT {int(limit_eff)}"
        else:
            sql = query or ""
            if apply_limit and limit_eff:
                if re.search(r"\blimit\b", sql, flags=re.IGNORECASE) is None:
                    sql = f"SELECT * FROM ({sql}) AS subq LIMIT {int(limit_eff)}"

        self._sql_load_generation = int(getattr(self, "_sql_load_generation", 0)) + 1
        gen = self._sql_load_generation
        self._sql_load_busy = True
        self._sql_load_error = None
        self._sql_load_ctx = None
        self._sql_load_clear_first = bool(clear_first)

        progress_total = limit_eff if limit_eff > 0 else 1
        begin = getattr(self, "_begin_tool_progress", None)
        if callable(begin):
            begin("SQL load", progress_total)
        else:
            try:
                self.status_label.setText("SQL load: fetching…")
            except Exception:
                pass

        cancel_event = threading.Event()
        self._sql_load_cancel_event = cancel_event
        job_id = f"sql-load-{gen}"
        self._sql_load_job_id = job_id
        register_background_job(
            self,
            job_id,
            "SQL load…",
            cancel=cancel_event.set,
        )

        prog = getattr(self, "_tool_progress_state", None)
        signals = SqlLoadSignals(self)

        def _on_parsed(result, g=gen) -> None:
            self._on_sql_load_parsed(result, g)

        def _on_failed(message, g=gen) -> None:
            self._on_sql_load_failed(message, g)

        worker = SqlLoadWorker(
            url=out_url,
            engine_kwargs=eng_kw,
            sql=sql,
            page_size=page_size,
            limit_eff=limit_eff,
            apply_limit=bool(apply_limit),
            signals=signals,
            generation=gen,
            cancel_event=cancel_event,
            progress_state=prog,
        )
        if "pytest" in sys.modules:
            signals.finished.connect(_on_parsed, type=Qt.DirectConnection)
            signals.failed.connect(_on_failed, type=Qt.DirectConnection)
            worker.run()
            self._drain_sql_load()
            err = getattr(self, "_sql_load_error", None)
            if err:
                raise RuntimeError(err)
        else:
            signals.finished.connect(_on_parsed, type=Qt.QueuedConnection)
            signals.failed.connect(_on_failed, type=Qt.QueuedConnection)
            start_runnable_on_app_pool(self, worker)

    def _clear_sql_load_job(self) -> None:
        job_id = getattr(self, "_sql_load_job_id", None)
        if job_id:
            unregister_background_job(self, job_id)
        self._sql_load_job_id = None
        self._sql_load_cancel_event = None

    def _drain_sql_load(self, *, timeout_s: float = 60.0) -> None:
        """Process Qt events until SQL fetch/apply completes (tests / sync path)."""
        deadline = time.monotonic() + float(timeout_s)
        while time.monotonic() < deadline:
            busy = bool(getattr(self, "_sql_load_busy", False))
            busy = busy or getattr(self, "_sql_load_ctx", None) is not None
            if not busy:
                return
            QApplication.processEvents()
            time.sleep(0.001)
        raise TimeoutError("Timed out waiting for SQL load to finish.")

    def _on_sql_load_failed(self, message: str, generation: int) -> None:
        if generation != getattr(self, "_sql_load_generation", 0):
            return
        self._sql_load_busy = False
        self._sql_load_ctx = None
        self._clear_sql_load_job()
        finish = getattr(self, "_finish_tool_progress", None)
        if callable(finish):
            finish("SQL load", status_message=None)
        try:
            self.table.setUpdatesEnabled(True)
        except Exception:
            pass
        msg = message or "SQL load failed."
        self._sql_load_error = msg
        if "pytest" not in sys.modules:
            if msg == "Cancelled.":
                try:
                    self.status_label.setText("SQL load: cancelled.")
                except Exception:
                    pass
            else:
                QMessageBox.critical(self, "SQL load", msg)

    def _on_sql_load_parsed(self, result: object, generation: int) -> None:
        if generation != getattr(self, "_sql_load_generation", 0):
            return
        if not isinstance(result, SqlLoadParseResult):
            self._on_sql_load_failed("Invalid SQL load result.", generation)
            return
        prepared = list(result.prepared_rows or [])
        if not prepared:
            self._on_sql_load_failed("Query returned 0 rows.", generation)
            return

        perf = getattr(self, "_perf", None)
        scope = perf.track if perf is not None else (lambda *_args, **_kwargs: nullcontext())
        with scope("sql.apply_rows"):
            if getattr(self, "_sql_load_clear_first", True):
                self.clear_all()

            cols = list(result.columns or [])
            self.headers = ["ID_HIDDEN", "Structure"] + cols
            self.table.setSortingEnabled(False)
            try:
                self.table.setUpdatesEnabled(False)
            except Exception:
                pass
            self._table_model.clear_rows()
            self._table_model.set_headers(list(self.headers))
            self.table.setColumnHidden(0, True)
            try:
                self.mols = dict(result.mols or {})
            except Exception:
                self.mols = {}
            self._clear_filter_target_smiles_cache()
            self.global_bounds = {}
            self.next_oid = int(result.next_oid)

            chunk = max(64, int(load_config().ingest_gui_chunk_size))
            self._sql_load_ctx = {
                "gen": generation,
                "prepared_rows": prepared,
                "idx": 0,
                "chunk": chunk,
                "rows_hit_limit": bool(result.rows_hit_limit),
                "limit_eff": int(result.limit_eff),
            }
            n = len(prepared)
            on_prog = getattr(self, "_on_tool_progress", None)
            if callable(on_prog):
                on_prog("SQL load: applying…", 0, n)
            else:
                try:
                    self.status_label.setText(f"SQL load: applying… (0/{n:,})")
                except Exception:
                    pass
            # Keep busy until apply finishes.
            self._sql_load_busy = True
            QTimer.singleShot(0, self._sql_load_apply_step)

    def _sql_load_apply_step(self) -> None:
        ctx = getattr(self, "_sql_load_ctx", None)
        if not ctx or ctx.get("gen") != getattr(self, "_sql_load_generation", 0):
            try:
                self.table.setUpdatesEnabled(True)
            except Exception:
                pass
            self._sql_load_busy = False
            return
        cancel = getattr(self, "_sql_load_cancel_event", None)
        if cancel is not None and cancel.is_set():
            self._sql_load_ctx = None
            self._on_sql_load_failed("Cancelled.", int(ctx["gen"]))
            return

        prepared = ctx["prepared_rows"]
        i = int(ctx["idx"])
        chunk = int(ctx["chunk"])
        n = len(prepared)
        end = min(i + chunk, n)
        batch = prepared[i:end]
        if batch:
            self._table_model.append_rows_batch(batch, defer_color_cache=True)
        ctx["idx"] = end
        on_prog = getattr(self, "_on_tool_progress", None)
        if callable(on_prog):
            on_prog("SQL load: applying…", end, n)
        else:
            try:
                self.status_label.setText(f"SQL load: applying… ({end:,}/{n:,})")
            except Exception:
                pass
        if end < n:
            QTimer.singleShot(0, self._sql_load_apply_step)
            return

        rows_hit_limit = bool(ctx.get("rows_hit_limit"))
        limit_eff = int(ctx.get("limit_eff") or 0)
        self._sql_load_ctx = None
        self._sql_load_busy = False
        self._clear_sql_load_job()
        try:
            self.table.setUpdatesEnabled(True)
        except Exception:
            pass
        finish = getattr(self, "_finish_tool_progress", None)
        if callable(finish):
            finish("SQL load", status_message=None)

        if rows_hit_limit:
            QMessageBox.information(
                self,
                "SQL load",
                f"The result has {n:,} row(s), reaching the row limit ({limit_eff:,}). "
                "If you expected more rows, raise “Max rows” in the SQL dialog or adjust your query.",
            )

        if self._sqlite_store is not None:
            self._sqlite_store_dirty = True

        self.table.setSortingEnabled(False)
        smiles_loaded = any(str(h).lower() == "smiles" for h in (self.headers or []))
        QTimer.singleShot(0, lambda: self._deferred_sql_post_load_follow_up(n, smiles_loaded))

    def _deferred_sql_post_load_follow_up(self, nrows: int, smiles_loaded: bool) -> None:
        """Defer bounds scan and 2D batch so the SQL load dialog can close and the table can paint."""
        self._table_model.rebuild_column_color_caches_after_bulk_load()
        self.schedule_calculate_global_bounds(delay_ms=500)
        if smiles_loaded and self._try_auto_render_all_structures_after_ingest():
            self.status_label.setText(f"Loaded {nrows:,} row(s) from SQL — drawing 2D structures…")
        else:
            self.status_label.setText(
                loaded_sql_status(nrows)
                if smiles_loaded
                else f"Loaded {nrows:,} row(s) from SQL (no SMILES column)."
            )

    def open_fp_similarity(self):
        if not self.headers:
            return
        from ..dialogs import FPSimilarityDialog

        dlg = FPSimilarityDialog(self)
        self._prepare_tool_dialog(dlg)
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()

    def open_diverse_subset(self) -> None:
        if not self.headers:
            return
        from ..dialogs import DiverseSubsetDialog

        dlg = DiverseSubsetDialog(self)
        self._prepare_tool_dialog(dlg)
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()

    def _ensure_diverse_subset_signals(self):
        """Signals on the main window so diverse subset jobs survive dialog close."""
        sig = getattr(self, "_diverse_subset_signals", None)
        if sig is not None:
            return sig
        from ...workers import DiverseSubsetSignals

        sig = DiverseSubsetSignals(self)
        sig.finished.connect(self._on_diverse_subset_finished)
        sig.failed.connect(self._on_diverse_subset_failed)
        self._diverse_subset_signals = sig
        return sig

    def _on_diverse_subset_finished(
        self, picked_oids: list, column_rows: list, n_cached: int, n_computed: int
    ) -> None:
        from PyQt5.QtCore import QTimer

        self._finish_tool_progress("Diverse subset")
        ctx = getattr(self, "_diverse_subset_run_ctx", None) or {}
        picked = [int(o) for o in (picked_oids or [])]

        def _apply_results() -> None:
            col_name = (ctx.get("pending_column_name") or "").strip()
            if col_name and column_rows:
                m = self._table_model
                nc = m.columnCount()
                self.headers.append(col_name)
                m.insert_column_at(nc, col_name, None)
                try:
                    self.table.setUpdatesEnabled(False)
                except Exception:
                    pass
                try:
                    # Sparse write: only picked ranks (avoid BindingDB-scale full-column fill).
                    m.set_column_text_by_oids(
                        col_name,
                        [(int(oid), str(rank)) for oid, rank in column_rows],
                    )
                    self._sync_global_bounds_for_headers([col_name], refresh_filters=True)
                finally:
                    try:
                        self.table.setUpdatesEnabled(True)
                    except Exception:
                        pass
            # Select after column insert — inserting columns clears Qt selection.
            # Keep an OID override so Export Selected survives filter/header churn.
            if ctx.get("select_subset") and picked:
                source_rows: list[int] = []
                for oid in picked:
                    try:
                        row = self.logical_row_for_oid(int(oid))
                    except (TypeError, ValueError):
                        continue
                    if row >= 0:
                        source_rows.append(int(row))
                self._finish_oid_override_selection(
                    source_rows,
                    frozenset(int(o) for o in picked),
                    clear_oid_override=False,
                    extra_status="",
                )
            cache_note = ""
            if n_cached or n_computed:
                cache_note = f" ({n_cached} cached fingerprint(s), {n_computed} computed)"
            col_note = f" Column '{col_name}' added." if col_name else ""
            self.status_label.setText(
                f"Diverse subset: picked {len(picked)} compound(s).{cache_note}{col_note}"
            )

        QTimer.singleShot(0, _apply_results)

    def _on_diverse_subset_failed(self, msg: str) -> None:
        self._finish_tool_progress("Diverse subset")
        if msg == "Cancelled.":
            self.status_label.setText("Cancelled.")
        else:
            self.status_label.setText(f"Diverse subset failed: {msg or 'Computation failed.'}")

    def _ensure_pka_predictor_signals(self):
        """Signals live on the main window so pKa jobs survive dialog close."""
        sig = getattr(self, "_pka_predictor_signals", None)
        if sig is not None:
            return sig
        from ...workers import PKaPredictorSignals

        sig = PKaPredictorSignals(self)
        sig.finished.connect(self._on_pka_prediction_finished)
        sig.failed.connect(self._on_pka_prediction_failed)
        self._pka_predictor_signals = sig
        return sig

    def _on_pka_prediction_finished(self, results: list, include_pi: bool = False) -> None:
        table_rows = [(o, t, pi) for o, t, pi in results if o is not None]
        lone = [(t, pi) for o, t, pi in results if o is None]
        if table_rows:
            if include_pi:
                res = [(int(o), {"pKa": text, "pI": pi}) for o, text, pi in table_rows]
                headers = ["pKa", "pI"]
            else:
                res = [(int(o), {"pKa": text}) for o, text, _pi in table_rows]
                headers = ["pKa"]
            self.on_calc_finished(res, headers, progress_label="pKa prediction")
        if lone:
            pka_txt, pi_txt = lone[0]
            msg = f"pKa: {pka_txt}"
            if include_pi:
                msg = f"{msg}\npI: {pi_txt}"
            QMessageBox.information(self, "Predict pKa", msg)
        if not table_rows:
            self._finish_tool_progress("pKa prediction")

    def _on_pka_prediction_failed(self, msg: str) -> None:
        self._finish_tool_progress("pKa prediction")
        QMessageBox.warning(self, "Predict pKa", msg or "Prediction failed.")

    def open_pka_predictor(self) -> None:
        if not ensure_table_ready_for_tool(self, "Predict pKa"):
            return
        from ..dialogs import PKaPredictorDialog

        dlg = PKaPredictorDialog(self)
        self._prepare_tool_dialog(dlg)
        dlg.setAttribute(Qt.WA_DeleteOnClose, True)
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()

    def _ensure_permeability_predictor_signals(self):
        sig = getattr(self, "_permeability_predictor_signals", None)
        if sig is not None:
            return sig
        from ...workers import PermeabilityPredictorSignals

        sig = PermeabilityPredictorSignals(self)
        sig.finished.connect(self._on_permeability_prediction_finished, Qt.QueuedConnection)
        sig.failed.connect(self._on_permeability_prediction_failed, Qt.QueuedConnection)
        self._permeability_predictor_signals = sig
        return sig

    def schedule_permeability_prediction(
        self,
        src: str,
        *,
        only_selected: bool,
        output_columns: tuple[str, ...],
    ) -> None:
        """Gather rows and enqueue prediction on the next event-loop tick (keeps the dialog responsive)."""
        QTimer.singleShot(
            0,
            lambda: self._start_permeability_prediction(src, only_selected, output_columns),
        )

    def _start_permeability_prediction(
        self,
        src: str,
        only_selected: bool,
        output_columns: tuple[str, ...],
    ) -> None:
        from ...workers import PermeabilityPredictorWorker

        allowed = self._selected_oids_set() if only_selected else None
        if self._abort_if_only_selected_but_empty(only_selected, allowed, "Predict Permeability"):
            return
        rows_smi = self.collect_scoped_table_smiles(src, only_selected=only_selected)
        if not rows_smi:
            QMessageBox.information(
                self,
                "Predict Permeability",
                "No valid structures were found for this scope and source.",
            )
            return
        perm_signals = self._ensure_permeability_predictor_signals()
        n = len(rows_smi)
        prog = self._tool_progress_state
        enqueue_process_queue_job(
            self,
            "Predict Permeability",
            n,
            lambda ev, r=rows_smi, ws=self.signals, ps=perm_signals, c=output_columns, st=prog: (
                PermeabilityPredictorWorker(
                    r, ws, ps, cancel_event=ev, output_columns=c, progress_state=st
                )
            ),
            queue_label=f"Predict Permeability ({n} rows)",
        )

    def _on_permeability_prediction_finished(self, results: list) -> None:
        if not results:
            self._finish_tool_progress("Predict Permeability")
            return
        calc_h = list(results[0][1].keys())
        res = [(oid, row_d) for oid, row_d in results]
        self.on_calc_finished(res, calc_h, progress_label="Predict Permeability")

    def _on_permeability_prediction_failed(self, msg: str) -> None:
        self._finish_tool_progress("Predict Permeability")
        QMessageBox.warning(self, "Predict Permeability", msg or "Prediction failed.")

    def open_permeability_predictor(self) -> None:
        if not ensure_table_ready_for_tool(self, "Predict Permeability"):
            return
        from ..dialogs import PermeabilityPredictorDialog

        dlg = PermeabilityPredictorDialog(self)
        self._prepare_tool_dialog(dlg)
        dlg.setAttribute(Qt.WA_DeleteOnClose, True)
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()

    def _ensure_som_predictor_signals(self):
        sig = getattr(self, "_som_predictor_signals", None)
        if sig is not None:
            return sig
        from ...workers import SomPredictorSignals

        sig = SomPredictorSignals(self)
        sig.finished.connect(self._on_som_prediction_finished, Qt.QueuedConnection)
        sig.failed.connect(self._on_som_prediction_failed, Qt.QueuedConnection)
        self._som_predictor_signals = sig
        return sig

    def _host_unavailable(self) -> bool:
        try:
            from PyQt5 import sip

            if sip.isdeleted(self):
                return True
        except Exception:
            return True
        try:
            from ...workers.process_pool_utils import application_is_shutting_down

            return bool(application_is_shutting_down())
        except Exception:
            return False

    def _on_som_prediction_finished(self, results: list) -> None:
        if self._host_unavailable():
            return
        from ...som_prediction import SOM_MAP_COLUMN
        from ..structure_pixmap import pixmap_from_structure_render_png
        from ...display_constants import structure_depiict_height, structure_depiict_width
        from ..som_browser import records_from_worker_rows

        table_rows = [row for row in results if row and row[0] is not None]
        if table_rows:
            calc_h = list(table_rows[0][4]) if table_rows[0][4] else list(table_rows[0][1].keys())
            res = [(int(oid), cols) for oid, cols, _png, _atoms, _headers in table_rows]
            written = self.on_calc_finished(res, calc_h, progress_label=TOOL_PREDICT_SOM)
            map_col = written[0] if written else SOM_MAP_COLUMN
            if map_col in self.headers:
                self._table_model.register_pixmap_column(map_col)
            dw, dh = structure_depiict_width(), structure_depiict_height()
            last_pm = None
            for oid, _cols, png, _atoms, _headers in table_rows:
                if not png:
                    continue
                pm = pixmap_from_structure_render_png(png, dw, dh)
                if pm is not None and not pm.isNull():
                    self._table_model.set_column_pixmap(int(oid), map_col, pm)
                    last_pm = pm
                    view_row = self._resolve_structure_row_for_oid(int(oid))
                    if view_row != -1:
                        need_h = max(dh, int(pm.height()))
                        if int(self.table.rowHeight(view_row)) < need_h:
                            self.table.setRowHeight(int(view_row), need_h)
            sync_w = getattr(self, "_sync_data_pixmap_column_width", None)
            if callable(sync_w) and last_pm is not None:
                sync_w(map_col, last_pm, dw)
        else:
            self._finish_tool_progress(TOOL_PREDICT_SOM)

        records = records_from_worker_rows(results)
        if records:
            self._som_browse_records = list(records)
            self._open_som_browser(records)
        elif not table_rows:
            QMessageBox.information(
                self,
                TOOL_PREDICT_SOM,
                "No sites of metabolism were returned.",
            )
        notice = self._consume_partial_results_notice()
        if notice:
            self.status_label.setText(notice)

    def _on_som_browser_dialog_destroyed(self, *_args) -> None:
        from ..qt_widget_utils import qobject_is_deleted

        if qobject_is_deleted(self):
            return
        try:
            sender = self.sender()
        except RuntimeError:
            return
        current = getattr(self, "_som_browser_dialog", None)
        if sender is not None and current is not None and current is not sender:
            return
        self._som_browser_dialog = None

    def _discard_stale_som_browser_dialog(self) -> None:
        dlg = getattr(self, "_som_browser_dialog", None)
        if dlg is None:
            return
        try:
            from PyQt5 import sip

            if sip.isdeleted(dlg) or getattr(dlg, "_panel", None) is None:
                self._som_browser_dialog = None
                try:
                    dlg.close()
                    dlg.deleteLater()
                except RuntimeError:
                    pass
        except Exception:
            self._som_browser_dialog = None

    def _open_som_browser(self, records, *, focus_oid: int | None = None) -> None:
        from ..som_browser import SomBrowserDialog, SomBrowserWidget

        if self._host_unavailable():
            return
        self._som_browse_records = list(records or [])
        self._discard_stale_som_browser_dialog()

        def _focus(widget) -> None:
            if widget is None or focus_oid is None:
                return
            jump = getattr(widget, "jump_to_oid", None)
            if callable(jump):
                jump(int(focus_oid))

        for w in self.iter_docked_plot_widgets():
            if isinstance(w, SomBrowserWidget):
                mgr = self._workspace()
                if mgr is not None:
                    pane = mgr.pane_for_widget(w)
                    if pane is not None:
                        mgr.set_preferred_pane(pane)
                self.show_docked_plot_panel()
                w.set_records(records)
                _focus(w)
                w.raise_()
                self.status_label.setText(f"{TOOL_PREDICT_SOM}: focused in workspace pane.")
                return

        def _factory():
            dlg = SomBrowserDialog(self)
            dlg.set_records(records)
            _focus(getattr(dlg, "_panel", None))
            return dlg

        def _on_reused(dlg):
            dlg.set_records(records)
            _focus(getattr(dlg, "_panel", None))

        reuse_or_show_modeless_singleton(
            self,
            "_som_browser_dialog",
            _factory,
            self._on_som_browser_dialog_destroyed,
            on_reused_visible=_on_reused,
        )

    def open_som_browser_for_oid(self, oid: int | None) -> None:
        """Open the Predict SOM browser focused on one table row."""
        from ..som_browser import records_from_table

        records = list(getattr(self, "_som_browse_records", None) or ())
        missing = oid is not None and not any(r.oid == int(oid) for r in records)
        if not records or missing:
            table_recs = records_from_table(self)
            if table_recs:
                records = table_recs
                self._som_browse_records = list(records)
        if not records:
            QMessageBox.information(
                self,
                TOOL_PREDICT_SOM,
                "No SOM maps to browse. Run Predict SOM first.",
            )
            return
        self._open_som_browser(records, focus_oid=oid)

    def export_som_map_for_oid(self, oid: int, header: str) -> None:
        """Save the SOM Map cell image for one table row."""
        from PyQt5.QtWidgets import QFileDialog

        pm = self._table_model.column_pixmap_copy(int(oid), header)
        if pm is None or pm.isNull():
            QMessageBox.information(
                self,
                TOOL_PREDICT_SOM,
                "This cell has no SOM map image to export.",
            )
            return
        suggested = som_map_export_filename(int(oid), header)
        path, _sel = QFileDialog.getSaveFileName(
            self,
            "Export SOM Map",
            suggested,
            "PNG image (*.png);;All files (*.*)",
        )
        if not path:
            return
        written = save_som_map_pixmap(pm, path)
        if not written:
            QMessageBox.warning(self, TOOL_PREDICT_SOM, "Could not save the SOM map image.")
            return
        self.status_label.setText(f"Exported SOM map to {written}")

    def _on_som_prediction_failed(self, msg: str) -> None:
        if self._host_unavailable():
            return
        report_cancellable_job_failure(
            self,
            TOOL_PREDICT_SOM,
            msg,
            progress_label=TOOL_PREDICT_SOM,
            failure_fallback="Prediction failed.",
        )

    def open_som_predictor(self) -> None:
        if not ensure_table_ready_for_tool(self, TOOL_PREDICT_SOM):
            return
        from ..dialogs import SomPredictorDialog

        dlg = SomPredictorDialog(self)
        self._prepare_tool_dialog(dlg)
        dlg.setAttribute(Qt.WA_DeleteOnClose, True)
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()

    def open_protomer_generator(self) -> None:
        if not ensure_table_ready_for_tool(self, "Generate Protomers"):
            return
        from ..dialogs import ProtomerGeneratorDialog

        dlg = ProtomerGeneratorDialog(self)
        self._prepare_tool_dialog(dlg)
        dlg.setAttribute(Qt.WA_DeleteOnClose, True)
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()

    def on_custom_calc_finished(self, res):
        # If the expression failed for every row, don't add an all-error column.
        ok_any = False
        for _idx, val in res:
            t = (val or "").strip()
            if safe_float(t) is not None:
                ok_any = True
                break
        if not ok_any:
            QMessageBox.warning(
                self,
                TOOL_CALCULATOR,
                "The expression produced no numeric results (all rows failed). No column was added.",
            )
            self.status_label.setText(f"{TOOL_CALCULATOR}: no numeric results.")
            self._clear_tool_progress()
            return

        self._finish_tool_progress("Calculator…")
        self.on_calc_finished(
            [(int(oid), {self.new_c: str(val)}) for oid, val in res],
            [self.new_c],
            finish_progress=False,
        )
        self.status_label.setText(
            self._consume_partial_results_notice()
            or f'{TOOL_CALCULATOR}: column "{self.new_c}" updated.'
        )
