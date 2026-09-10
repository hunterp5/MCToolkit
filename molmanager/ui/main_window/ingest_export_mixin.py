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

from __future__ import annotations

import re
import threading
from contextlib import nullcontext

from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QFileDialog, QMessageBox

from ...config import load_config
from ...workers import ExportWorker, UniversalLoadWorker
from ..strings import LOADING_DETAIL_APPEND, LOADING_DETAIL_READING_DISK


class IngestExportMixin:
    def open_file_dialog(self):
        f_filter = "All Supported (*.sdf *.mol *.csv *.smi *.txt *.tdt *.pdb);;SDF/Mol (*.sdf *.mol);;SMILES (*.smi *.txt *.csv);;TDT (*.tdt);;PDB (*.pdb)"
        path, _ = QFileDialog.getOpenFileName(self, "Open File", "", f_filter)
        if path:
            self.load_file(path)

    def open_import_file_dialog(self) -> None:
        f_filter = "All Supported (*.sdf *.mol *.csv *.smi *.txt *.tdt *.pdb);;SDF/Mol (*.sdf *.mol);;SMILES (*.smi *.txt *.csv);;TDT (*.tdt);;PDB (*.pdb)"
        path, _ = QFileDialog.getOpenFileName(self, "Import Data", "", f_filter)
        if path:
            self.import_file(path)

    def load_file(self, path: str) -> None:
        self._ingest_append_mode = False
        self._structure_field_override = None
        self.clear_all()
        self._apply_table_only_layout_for_file_load()
        self._set_ingest_loading(True)
        self._structures_queued = 0
        self._import_building_progress_shown = False
        self._table_stack.setCurrentIndex(0)
        self._loading_detail.setText(LOADING_DETAIL_READING_DISK)
        self.status_label.setText("Reading file…")
        self._ensure_structure_choice_event().set()
        batch_size = load_config().ingest_worker_batch_size
        self.process_queue.enqueue(
            f"Open file: {path}",
            lambda ev, p=path, s=self.signals, sce=self._structure_choice_event, bs=batch_size: UniversalLoadWorker(
                p, s, batch_size=bs, cancel_event=ev, structure_choice_event=sce
            ),
        )

    def _apply_table_only_layout_for_file_load(self) -> None:
        """Give the table the full workspace when replacing the session from a file."""
        from .workspace_layout import LAYOUT_TABLE_ONLY

        mgr = getattr(self, "_workspace_layout", None)
        if mgr is None or mgr.layout_id == LAYOUT_TABLE_ONLY:
            return
        apply = getattr(self, "apply_workspace_layout", None)
        if callable(apply):
            apply(LAYOUT_TABLE_ONLY)

    def import_file(self, path: str) -> None:
        """Load molecules from disk and append them to the current table (merge columns as needed)."""
        self._pending_batches = []
        self._processing_batches = False
        self._last_batch_received = False
        self._structure_field_override = None
        self._ingest_append_mode = True
        self._set_ingest_loading(True)
        self._structures_queued = 0
        self._import_building_progress_shown = False
        self._table_stack.setCurrentIndex(0)
        self._loading_detail.setText(
            LOADING_DETAIL_APPEND
        )
        self.status_label.setText("Importing…")
        self._ensure_structure_choice_event().set()
        batch_size = load_config().ingest_worker_batch_size
        self.process_queue.enqueue(
            f"Import data: {path}",
            lambda ev, p=path, s=self.signals, sce=self._structure_choice_event, bs=batch_size: UniversalLoadWorker(
                p, s, batch_size=bs, cancel_event=ev, structure_choice_event=sce
            ),
        )

    def _ensure_structure_choice_event(self) -> threading.Event:
        ev = getattr(self, "_structure_choice_event", None)
        if ev is None:
            ev = threading.Event()
            ev.set()
            self._structure_choice_event = ev
        return ev

    def _merge_import_headers(self, incoming: list[str]) -> None:
        """Extend ``self.headers`` / the table model with columns from an appended file."""
        old_tail = list(self.headers[2:]) if len(self.headers) > 2 else []
        inc_tail = list(incoming[2:]) if len(incoming) > 2 else []
        seen = set(old_tail)
        merged_tail = list(old_tail)
        for h in inc_tail:
            if h not in seen:
                seen.add(h)
                merged_tail.append(h)
        self.table.setSortingEnabled(False)
        old_set = set(old_tail)
        for h in merged_tail:
            if h not in old_set:
                nc = self._table_model.columnCount()
                self._table_model.insert_column_at(nc, h, None)
                old_set.add(h)
        self.headers = ["ID_HIDDEN", "Structure"] + merged_tail

    def run_export(self, selected=False):
        if self._table_model.rowCount() == 0:
            return
        if getattr(self, "_export_busy", False):
            QMessageBox.warning(self, "Export", "An export is already in progress.")
            return
        # Export in current visual column order (but always include ID/Structure first).
        vis_cols = self._visual_logical_columns()
        ordered_headers = [self.headers[i] for i in vis_cols if i < len(self.headers)]
        t_heads = ["ID_HIDDEN", "Structure"] + [
            h for h in ordered_headers if h not in ("ID_HIDDEN", "Structure")
        ]
        if selected:
            # Prefer logical selection (OID override / Qt / model highlights) so tool
            # picks like Diverse Subset export correctly even when Qt selection was cleared.
            oids = sorted(int(o) for o in self._selected_oids_set())
            if not oids:
                QMessageBox.information(
                    self,
                    "Export Selected",
                    "No rows are selected. Select one or more rows in the table first.",
                )
                return
            t_mols = {oid: self.mols.get(oid) for oid in oids}
        else:
            oids_all = self._table_model.all_oids_in_order()
            t_mols = {oid: self.mols.get(oid) for oid in oids_all}
        f_filter = "SDF (*.sdf);;Molfile (*.mol);;SMILES (*.smi);;CSV (*.csv);;TDT (*.tdt);;PDB (*.pdb)"
        path, sel_f = QFileDialog.getSaveFileName(self, "Export Data", "", f_filter)
        if path:
            # Robustly infer the extension even if the Qt filter string is empty/unexpected.
            ext = ""
            m = re.search(r"\(([^)]+)\)", sel_f or "")
            if m:
                # e.g. "*.sdf" or "*.sdf *.mol" -> take first token
                tok = (m.group(1).split() or [""])[0]
                ext = tok.replace("*", "").strip()
            if not ext:
                # Fall back to what user typed.
                ext = (("." + path.split(".")[-1]) if "." in path else "")
            if not ext:
                # Last resort: default to .sdf
                ext = ".sdf"
            if not path.lower().endswith(ext.lower()):
                path += ext
            h_map = {h: i for i, h in enumerate(self.headers)}
            oids_list = list(t_mols.keys())
            row_cache = {oid: self.get_row_by_id(oid) for oid in oids_list}
            self._export_busy = True
            self._export_prep = {
                "path": path,
                "ext": ext,
                "t_mols": t_mols,
                "t_heads": t_heads,
                "h_map": h_map,
                "oids": oids_list,
                "rows": row_cache,
                "t_data": {},
                "idx": 0,
                "chunk": 48,
                "cols": [h for h in t_heads if h in self.headers],
            }
            self._on_tool_progress("Preparing export…", 0, max(len(oids_list), 1))
            QTimer.singleShot(0, self._export_snapshots_continue)

    def _export_snapshots_continue(self) -> None:
        prep = self._export_prep
        if not prep:
            return
        try:
            oids = prep["oids"]
            h_map = prep["h_map"]
            cols = prep["cols"]
            n = len(oids)
            chunk = prep["chunk"]
            start = prep["idx"]
            end = min(start + chunk, n)
            perf = getattr(self, "_perf", None)
            scope = perf.track if perf is not None else (lambda *_args, **_kwargs: nullcontext())
            with scope("export.snapshot_chunk"):
                for j in range(start, end):
                    oid = oids[j]
                    r = prep["rows"].get(oid, -1)
                    if r != -1:
                        prep["t_data"][oid] = {h: self._export_cell_text(r, h_map[h]) for h in cols}
                    else:
                        prep["t_data"][oid] = {h: "" for h in cols}
            prep["idx"] = end
            self._on_tool_progress("Preparing export…", end, max(n, 1))
            if end < n:
                QTimer.singleShot(0, self._export_snapshots_continue)
                return
            path = prep["path"]
            ext = prep["ext"]
            t_data = prep["t_data"]
            t_mols = prep["t_mols"]
            t_heads = prep["t_heads"]
            self._export_prep = None
            self.process_queue.enqueue(
                f"Export to {path}",
                lambda ev, p=path, e=ext, m=t_mols, h=t_heads, d=t_data, s=self.signals: ExportWorker(
                    p, e, m, h, d, s, cancel_event=ev
                ),
            )
        except Exception as e:
            self._export_prep = None
            self._export_busy = False
            self._clear_tool_progress()
            QMessageBox.warning(self, "Export", str(e))
            self.status_label.setText("Ready")
