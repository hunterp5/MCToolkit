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

"""File ingest, SQLite rebuild, and 2D structure rendering."""

from __future__ import annotations

import logging
import time
from contextlib import nullcontext

from PyQt5.QtCore import QEventLoop, Qt, QTimer
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import (
    QApplication,
    QMessageBox,
)


from ...config import load_config
from ...confs_codec import demote_v1_cell_to_sidecar, mol_has_3d_coordinates, pack_confs_cell
from ...ingest_text import is_ingest_cell_batch
from ...display_constants import (
    STRUCTURE_COLUMN_HORIZONTAL_PADDING,
    structure_column_minimum_width,
    structure_depiict_height,
    structure_depiict_width,
    structure_row_default_height,
)
from ...structure_render_store import StructureRenderStore
from ..structure_pixmap import pixmap_from_structure_render_png
from ..strings import (
    LOADING_DETAIL_AFTER_FILE_READ,
    STATUS_READY_RENDER_2D,
    TOOL_RENDER_2D,
    loaded_session_status,
)
from ...storage import SqliteTableStore
from ...workers import (
    SqliteRebuildWorker,
)
from ..compound_table_model import CompoundTableModel

from rdkit import Chem

logger = logging.getLogger(__name__)

class IngestRenderMixin:
    def _abort_if_only_selected_but_empty(
        self, only_selected: bool, allowed: set | frozenset | None, title: str
    ) -> bool:
        """Return True if the user should stop (warning shown for empty selection)."""
        if only_selected and not allowed:
            QMessageBox.warning(
                self,
                title,
                "\u201cSelected Rows Only\u201d is checked but nothing is selected.",
            )
            return True
        return False

    def _on_structure_source_probe(self, headers: list) -> None:
        """Worker paused after first record; pick structure column before bulk read."""
        incoming = list(headers)
        if self._ingest_append_mode and self._table_model.rowCount() > 0:
            self._merge_import_headers(incoming)
        else:
            self.headers = incoming
        from ...import_structure import structure_source_picker_candidates
        from ..dialogs.structure_source import StructureSourcePickerDialog

        struct_cols = structure_source_picker_candidates(self.headers)
        if len(struct_cols) >= 2:
            picked, ok = StructureSourcePickerDialog.pick_column(self, struct_cols)
            if ok and picked:
                self._structure_field_override = picked
            elif not ok:
                self._structure_field_override = None
        ev = getattr(self, "_structure_choice_event", None)
        if ev is not None:
            ev.set()

    def _maybe_start_ingest_processing(self) -> None:
        if self._processing_batches:
            return
        if not self._pending_batches and not self._last_batch_received:
            return
        self._processing_batches = True
        QTimer.singleShot(0, self._process_next_chunk)

    def _ingest_use_silent_model(self) -> bool:
        return bool(load_config().ingest_silent_model_append)

    def _ingest_use_sqlite_incremental(self) -> bool:
        return bool(load_config().ingest_sqlite_incremental)

    def _sqlite_data_headers(self) -> list[str]:
        return [h for h in self.headers[2:] if h and not self._table_model.is_pixmap_data_column(h)]

    def _ingest_sqlite_entries_from_rows(
        self,
        new_rows: list[tuple[int, dict[str, str]]],
        data_headers: list[str],
    ) -> list[tuple[int, dict[str, str]]]:
        return [
            (int(oid), {h: str(cells.get(h, "") or "") for h in data_headers})
            for oid, cells in new_rows
        ]

    def _ingest_sqlite_begin_bulk(self) -> None:
        store = getattr(self, "_sqlite_store", None)
        if store is None or not self._ingest_use_sqlite_incremental():
            return
        data_headers = self._sqlite_data_headers()
        if self._ingest_append_mode and self._table_model.rowCount() > 0:
            if frozenset(store.headers) != frozenset(data_headers):
                return
            self._ingest_sqlite_bulk_active = True
            self._ingest_sqlite_bulk_headers = list(data_headers)
            self._ingest_sqlite_paused_dirty = True
            return
        try:
            store.begin_bulk_load(self.headers)
        except Exception:
            logger.exception("Failed to begin incremental SQLite ingest")
            self._ingest_sqlite_bulk_active = False
            self._ingest_sqlite_paused_dirty = False
            return
        self._ingest_sqlite_bulk_active = True
        self._ingest_sqlite_bulk_headers = list(data_headers)
        self._ingest_sqlite_paused_dirty = True

    def _ingest_sqlite_append_batch(self, new_rows: list[tuple[int, dict[str, str]]]) -> None:
        if not getattr(self, "_ingest_sqlite_bulk_active", False) or not new_rows:
            return
        store = getattr(self, "_sqlite_store", None)
        headers = getattr(self, "_ingest_sqlite_bulk_headers", None)
        if store is None or not headers:
            return
        try:
            store.append_bulk_rows(self._ingest_sqlite_entries_from_rows(new_rows, headers))
        except Exception:
            logger.exception("Incremental SQLite ingest append failed")
            self._ingest_sqlite_bulk_active = False
            self._ingest_sqlite_paused_dirty = False
            self._sqlite_store_dirty = True

    def _ingest_sqlite_finalize_bulk(self) -> bool:
        """Return True when the SQLite mirror is ready and no rebuild is needed."""
        if not getattr(self, "_ingest_sqlite_bulk_active", False):
            self._ingest_sqlite_paused_dirty = False
            return False
        store = getattr(self, "_sqlite_store", None)
        self._ingest_sqlite_bulk_active = False
        self._ingest_sqlite_paused_dirty = False
        self._ingest_sqlite_bulk_headers = None
        if store is None:
            return False
        if store.bulk_loading:
            try:
                store.finalize_bulk_load()
            except Exception:
                logger.exception("Failed to finalize incremental SQLite ingest")
                self._sqlite_store_dirty = True
                return False
        self._sqlite_store_dirty = False
        return True

    def _ingest_begin_silent_if_needed(self) -> None:
        if self._ingest_use_silent_model() and not self._table_model.silent_appending:
            self._table_model.begin_silent_appends()

    def _ingest_append_batch_items(self, items: list, new_rows: list[tuple[int, dict[str, str]]]) -> None:
        """Convert one worker batch (mol blobs or cell dicts) into pending table rows."""
        if is_ingest_cell_batch(items):
            for cells in items:
                oid = self.next_oid
                self.next_oid += 1
                new_rows.append((oid, dict(cells)))
            return
        override_field = getattr(self, "_structure_field_override", None)
        for item in items:
            blob, cells = self._split_ingest_item(item)
            if override_field:
                m, precomputed = self._resolve_override_ingest_mol(blob, cells, override_field)
            else:
                m = self._coerce_ingest_mol(blob)
                precomputed = cells
            oid = self.next_oid
            self.next_oid += 1
            new_rows.append((oid, self._ingest_store_mol(oid, m, precomputed_cells=precomputed)))

    def _resolve_override_ingest_mol(self, blob, cells, field: str):
        """Apply a structure-column override during ingest, reading the field from the cell dict.

        Ingest blobs carry structure only (no properties), so the override source column is taken
        from the worker-built cells. When it parses, cells are recomputed from the override mol
        (matching the non-blob behavior); otherwise the parsed structure and its cells are kept.
        """
        raw = (cells.get(field) or "").strip() if isinstance(cells, dict) else ""
        if raw:
            nm = self._mol_from_structure_text(raw)
            if nm is not None:
                return nm, None
        return self._coerce_ingest_mol(blob), cells

    @staticmethod
    def _split_ingest_item(item):
        """Return ``(blob_or_mol, precomputed_cells)`` from a worker ingest item."""
        if isinstance(item, tuple):
            return item[0], item[1]
        return item, None

    @staticmethod
    def _coerce_ingest_mol(item) -> Chem.Mol | None:
        """Rebuild a live RDKit mol from an ingest blob (worker sends binary to avoid UI freezes)."""
        if isinstance(item, (bytes, bytearray)):
            try:
                return Chem.Mol(bytes(item))
            except Exception:
                return None
        return item

    def _ingest_store_mol(
        self, oid: int, mol: Chem.Mol, precomputed_cells: dict[str, str] | None = None
    ) -> dict[str, str]:
        """
        Store *mol* for row *oid*.

        When the molecule carries 3D coordinates, pack them into ``confs`` (for View
        Conformers) and keep a 2D depiction in ``self.mols`` for the Structure column.

        *precomputed_cells* are row cells built off the GUI thread by the load worker; when
        provided they are used verbatim (avoids re-reading every property on the GUI thread).
        """
        cells = dict(precomputed_cells) if precomputed_cells is not None else self._row_cells_from_mol(mol)
        if mol is not None and mol_has_3d_coordinates(mol):
            from ..mol_viewer_3d import prepare_mol_2d

            self._ensure_columns(["confs"])
            try:
                n_conf = int(mol.GetNumConformers())
            except Exception:
                n_conf = 0
            packed = pack_confs_cell(
                {
                    "ok": True,
                    "op": "ingest",
                    "n_kept": n_conf,
                    "n_packed": n_conf,
                },
                mol,
            )
            light, b64 = demote_v1_cell_to_sidecar(packed, "confs")
            sc = getattr(self, "_confs_blocks_sidecar", None)
            if sc is None:
                self._confs_blocks_sidecar = {}
                sc = self._confs_blocks_sidecar
            if b64 is not None:
                sc[(int(oid), "confs")] = b64
            depict = prepare_mol_2d(mol)
            self.mols[oid] = depict if depict is not None else mol
            cells["confs"] = light
            return cells
        self.mols[oid] = mol
        return cells

    def on_file_loaded(self, mols_list, headers, is_first, is_last):
        # Append batch to pending queue and schedule incremental processing
        if is_first:
            self._clear_filter_target_smiles_cache()
            incoming = list(headers)
            if self._ingest_append_mode and self._table_model.rowCount() > 0:
                self._merge_import_headers(incoming)
            else:
                self.headers = incoming
                self.table.setSortingEnabled(False)
                self._table_model.clear_rows()
                self._table_model.set_headers(list(self.headers))
                self.table.setColumnHidden(0, True)
            if self._table_stack.currentIndex() == 0:
                self._loading_detail.setText(LOADING_DETAIL_AFTER_FILE_READ)
            self._ingest_begin_silent_if_needed()
            self._ingest_sqlite_begin_bulk()
        if mols_list:
            self._pending_batches.append((mols_list, is_last))
        if is_last:
            self._last_batch_received = True
        if mols_list and not self._processing_batches:
            self._ingest_begin_silent_if_needed()
        self._maybe_start_ingest_processing()

    def _process_next_chunk(self, chunk_size: int | None = None):
        cfg = load_config()
        if chunk_size is None:
            chunk_size = int(cfg.ingest_gui_chunk_size)
        budget_s = max(0.005, int(cfg.ingest_gui_time_budget_ms) / 1000.0)
        deadline = time.monotonic() + budget_s
        processed = 0
        perf = getattr(self, "_perf", None)
        scope = perf.track if perf is not None else (lambda *_args, **_kwargs: nullcontext())
        try:
            self.table.setUpdatesEnabled(False)
        except Exception:
            pass
        # Consume each worker batch in small sub-slices, re-checking the time budget between them,
        # so a single tick stays near ``ingest_gui_time_budget_ms`` even as per-row cost grows
        # (mol rebuild + property extraction + SQLite). This keeps the UI smooth during ingest.
        sub_slice = max(32, min(int(chunk_size), int(cfg.ingest_gui_subslice_rows)))
        try:
            with scope("ingest.process_chunk"):
                while self._pending_batches and processed < chunk_size and time.monotonic() < deadline:
                    mols_list, is_last = self._pending_batches[0]
                    step = min(len(mols_list), sub_slice, max(0, int(chunk_size - processed)))
                    if step:
                        take = mols_list[:step]
                        new_rows: list[tuple[int, dict[str, str]]] = []
                        self._ingest_append_batch_items(take, new_rows)
                        self._table_model.append_rows_batch(new_rows, defer_color_cache=True)
                        self._ingest_sqlite_append_batch(new_rows)
                        processed += len(new_rows)
                        del mols_list[:step]
                    if not mols_list:
                        self._pending_batches.pop(0)
                        if is_last:
                            self._last_batch_received = True
            if processed:
                n = self._table_model.rowCount()
                self.status_label.setText(f"Loaded {n:,} molecules — preparing table…")
                if self._table_stack.currentIndex() == 0:
                    self._loading_detail.setText(
                        f"Building table…\n{n} molecule(s); 2D structures draw before the workspace is shown"
                    )
                if getattr(self, "_ingest_loading", False) and not self._import_building_progress_shown:
                    self._import_building_progress_shown = True
                    self._on_tool_progress("Building table…", -1, -1)
        finally:
            try:
                self.table.setUpdatesEnabled(True)
            except Exception:
                pass

        if self._pending_batches:
            QTimer.singleShot(0, lambda: self._process_next_chunk(chunk_size))
        elif self._last_batch_received:
            QTimer.singleShot(0, self._finalize_ingest_on_gui_thread)
        else:
            self._processing_batches = False

    def _finalize_ingest_on_gui_thread(self) -> None:
        """Finish ingest on the loading page; reveal once filters and auto 2D are ready."""
        if self._table_model.silent_appending:
            self._table_model.end_silent_appends()
        if not self._ingest_sqlite_finalize_bulk():
            if getattr(self, "_sqlite_store", None) is not None:
                self._sqlite_store_dirty = True
            else:
                self._rebuild_sqlite_store_from_model()
        self.table.setSortingEnabled(False)
        self._structures_queued = 0
        self._ingest_prep_before_reveal = True
        try:
            self.table.setUpdatesEnabled(False)
        except Exception:
            pass
        self._import_progress_active = False
        self._clear_tool_progress(status_message=None)
        self._ingest_append_mode = False
        self._last_batch_received = False
        self._processing_batches = False
        n = self._table_model.rowCount()
        self._loading_detail.setText(
            f"Table built ({n:,} row(s)).\nPreparing table, then {TOOL_RENDER_2D}…"
        )
        if "confs" in self.headers or "superpose" in self.headers:
            QTimer.singleShot(0, self._migrate_legacy_confs_cells_to_sidecar)
        QTimer.singleShot(0, self._deferred_post_ingest_follow_up)

    def _deferred_post_ingest_follow_up(self) -> None:
        """Runs on the loading page: color caches, bounds, auto 2D, then reveal the table."""
        headers = self._table_model.pending_color_cache_headers()
        if headers:
            self._post_ingest_color_headers = headers
            self._post_ingest_color_idx = 0
            QTimer.singleShot(0, self._post_ingest_color_cache_step)
            return
        self._post_ingest_after_color_caches()

    def _post_ingest_color_cache_step(self) -> None:
        headers = getattr(self, "_post_ingest_color_headers", None) or []
        idx = int(getattr(self, "_post_ingest_color_idx", 0))
        if idx < len(headers):
            if getattr(self, "_ingest_prep_before_reveal", False):
                self._loading_detail.setText(
                    f"Preparing conditional formatting…\n({idx + 1}/{len(headers)} columns)"
                )
            self._table_model._rebuild_column_color_cache(headers[idx])
            self._post_ingest_color_idx = idx + 1
            QTimer.singleShot(0, self._post_ingest_color_cache_step)
            return
        self._post_ingest_color_headers = []
        self._post_ingest_after_color_caches()

    def _post_ingest_after_color_caches(self) -> None:
        """Finish filter bounds, then auto Render 2D; reveal only when both are done."""
        self._ingest_waiting_for_render = False
        if getattr(self, "_ingest_prep_before_reveal", False):
            self._loading_detail.setText("Preparing filters…")
        self.calculate_global_bounds(on_complete=self._post_ingest_after_bounds)

    def _post_ingest_after_bounds(self) -> None:
        """Start auto Render 2D after bounds are ready; hold the overlay until it finishes."""
        n = self._table_model.rowCount()
        self._loading_detail.setText(f"{TOOL_RENDER_2D}…\n{n:,} row(s)")
        started_render = self._try_auto_render_all_structures_after_ingest()
        if started_render and self._auto_render2d_blocks_workspace_reveal(n):
            self._ingest_waiting_for_render = True
            return
        keep_status = "auto 2D render skipped" in (self.status_label.text() or "")
        self._reveal_table_after_ingest_prep(keep_status=keep_status)

    def _ingest_on_render2d_batch_finished(self) -> None:
        """Reveal the workspace after auto Render 2D (or cancel) completes for a file load."""
        if not getattr(self, "_ingest_waiting_for_render", False):
            return
        self._ingest_waiting_for_render = False
        self._reveal_table_after_ingest_prep()

    def _reveal_table_after_ingest_prep(self, *, keep_status: bool = False) -> None:
        """Switch from the loading page to the table once prep and auto 2D are finished."""
        self._ingest_prep_before_reveal = False
        self._ingest_waiting_for_render = False
        self._set_ingest_loading(False)
        self._set_workspace_stack_index(1)
        finish_clean = getattr(self, "_finish_session_clean_if_pending", None)
        if callable(finish_clean):
            finish_clean()
        app = QApplication.instance()
        if app is not None:
            app.processEvents(QEventLoop.ExcludeUserInputEvents)
        try:
            self.table.setUpdatesEnabled(True)
        except Exception:
            pass
        if keep_status:
            return
        n = self._table_model.rowCount()
        self.status_label.setText(STATUS_READY_RENDER_2D if n else "Ready.")

    def _rebuild_sqlite_store_from_model(self) -> None:
        """Synchronous rebuild (clear table, tests). Large tables use ``_schedule_sqlite_rebuild``."""
        store = getattr(self, "_sqlite_store", None)
        if store is None:
            return
        self._sqlite_rebuild_in_progress = True
        data_headers = [h for h in self.headers[2:] if h and not self._table_model.is_pixmap_data_column(h)]
        entries = self._table_model.export_rows_for_sqlite(data_headers)
        perf = getattr(self, "_perf", None)
        scope = perf.track if perf is not None else (lambda *_args, **_kwargs: nullcontext())
        try:
            with scope("sqlite.rebuild"):
                store.rebuild(self.headers, entries)
            self._sqlite_store_dirty = False
        finally:
            self._sqlite_rebuild_in_progress = False

    def _schedule_sqlite_rebuild(self) -> None:
        """Chunk-export row text on the GUI, then write/index SQLite in a worker."""
        store = getattr(self, "_sqlite_store", None)
        if store is None or self._sqlite_rebuild_in_progress:
            return
        sigs = getattr(self, "_sqlite_rebuild_signals", None)
        pool = getattr(self, "threadpool", None)
        if sigs is None or pool is None:
            self._rebuild_sqlite_store_from_model()
            return
        self._sqlite_rebuild_gen = int(getattr(self, "_sqlite_rebuild_gen", 0)) + 1
        gen = self._sqlite_rebuild_gen
        self._sqlite_rebuild_in_progress = True
        data_headers = [h for h in self.headers[2:] if h and not self._table_model.is_pixmap_data_column(h)]
        import os
        import tempfile
        from pathlib import Path

        fd, db_path = tempfile.mkstemp(prefix="MOLMANAGER_sqlite_", suffix=".sqlite3")
        try:
            os.close(fd)
        except OSError:
            pass
        self._sqlite_rebuild_pending_path = Path(db_path)
        n_rows = self._table_model.rowCount()
        from ..background_jobs import register_background_job

        job_id = f"sqlite-rebuild-{gen}"
        self._sqlite_rebuild_bg_job_id = job_id
        register_background_job(self, job_id, f"Indexing table ({n_rows:,} rows)")
        begin = getattr(self, "_begin_tool_progress", None)
        if callable(begin):
            begin("Indexing table", max(1, n_rows))
        chunk = max(500, load_config().ingest_gui_chunk_size)
        self._sqlite_export_ctx = {
            "gen": gen,
            "data_headers": data_headers,
            "row_idx": 0,
            "n_rows": n_rows,
            "chunk": chunk,
            "db_path": str(db_path),
            "signals": sigs,
            "entries": [],
            "headers": list(self.headers),
        }
        self.status_label.setText(f"Indexing table… (0/{n_rows:,} rows)")
        QTimer.singleShot(0, self._sqlite_export_chunk_step)

    def _sqlite_export_chunk_step(self) -> None:
        ctx = getattr(self, "_sqlite_export_ctx", None)
        if not ctx or ctx.get("gen") != getattr(self, "_sqlite_rebuild_gen", -1):
            self._sqlite_export_ctx = None
            return
        if not self._sqlite_rebuild_in_progress:
            self._sqlite_export_ctx = None
            return
        data_headers = ctx["data_headers"]
        row_idx = int(ctx["row_idx"])
        n_rows = int(ctx["n_rows"])
        chunk = int(ctx["chunk"])
        end = min(row_idx + chunk, n_rows)
        slice_rows = self._table_model.export_rows_for_sqlite_slice(data_headers, row_idx, end)
        entries: list = ctx["entries"]
        entries.extend(slice_rows)
        ctx["row_idx"] = end
        on_prog = getattr(self, "_on_tool_progress", None)
        if callable(on_prog):
            on_prog("Indexing table…", end, max(1, n_rows))
        else:
            self.status_label.setText(f"Indexing table… ({end:,}/{n_rows:,} rows)")
        if end < n_rows:
            QTimer.singleShot(0, self._sqlite_export_chunk_step)
            return
        gen = int(ctx["gen"])
        db_path = ctx["db_path"]
        sigs = ctx["signals"]
        headers = list(ctx.get("headers") or self.headers)
        exported = list(entries)
        self._sqlite_export_ctx = None
        pool = getattr(self, "threadpool", None)
        if pool is None:
            self._sqlite_rebuild_in_progress = False
            finish = getattr(self, "_finish_tool_progress", None)
            if callable(finish):
                finish("Indexing table", status_message=None)
            return
        self.status_label.setText(f"Indexing table… (writing {len(exported):,} rows)")
        prog = getattr(self, "_tool_progress_state", None)
        pool.start(
            SqliteRebuildWorker(
                gen,
                headers,
                exported,
                db_path,
                sigs,
                stream_finalize=False,
                progress_state=prog,
            )
        )

    def _unregister_sqlite_rebuild_background_job(self, job_gen: int) -> None:
        from ..background_jobs import unregister_background_job

        job_id = getattr(self, "_sqlite_rebuild_bg_job_id", None)
        if job_id == f"sqlite-rebuild-{job_gen}":
            unregister_background_job(self, job_id)
            self._sqlite_rebuild_bg_job_id = None

    def _on_sqlite_rebuild_finished(self, job_gen: int, db_path: str) -> None:
        self._unregister_sqlite_rebuild_background_job(job_gen)
        if job_gen != getattr(self, "_sqlite_rebuild_gen", -1):
            return
        finish = getattr(self, "_finish_tool_progress", None)
        if callable(finish):
            finish("Indexing table", status_message=None)
        try:
            new_store = SqliteTableStore(db_path)
            old = getattr(self, "_sqlite_store", None)
            self._sqlite_store = new_store
            if old is not None:
                try:
                    old.close()
                except Exception:
                    pass
            self._sqlite_store_dirty = False
        except Exception:
            logger.exception("Failed to swap SQLite row store after background rebuild")
        finally:
            self._sqlite_rebuild_in_progress = False
            self._sqlite_rebuild_pending_path = None
        if getattr(self, "_sqlite_rebuild_stale", False):
            self._sqlite_rebuild_stale = False
            self._sqlite_store_dirty = True
            self._schedule_sqlite_rebuild()
            return
        n_rows = self._table_model.rowCount()
        if getattr(self, "_sqlite_rebuild_pending_filters", False):
            self._sqlite_rebuild_pending_filters = False
            self.apply_filters()
        elif n_rows:
            self.status_label.setText(loaded_session_status(n_rows))

    def _on_sqlite_rebuild_failed(self, job_gen: int, msg: str) -> None:
        self._unregister_sqlite_rebuild_background_job(job_gen)
        if job_gen != getattr(self, "_sqlite_rebuild_gen", -1):
            return
        finish = getattr(self, "_finish_tool_progress", None)
        if callable(finish):
            finish("Indexing table", status_message=None)
        logger.warning("SQLite rebuild failed: %s", msg)
        self._sqlite_rebuild_in_progress = False
        self._sqlite_rebuild_pending_path = None
        self._sqlite_rebuild_pending_filters = False
        self.status_label.setText("Table indexing failed — filters may be slow until data changes.")

    def _view_row_to_source_row(self, view_row: int) -> int:
        """Map a table view row index to the source ``CompoundTableModel`` row."""
        proxy = getattr(self, "_filter_proxy_model", None)
        if proxy is not None:
            src = proxy.mapToSource(proxy.index(int(view_row), 0))
            if src.isValid():
                return int(src.row())
        return int(view_row)

    def apply_structure_table_layout(self) -> None:
        """Sync Structure column row/column chrome to the current depiction size."""
        if not hasattr(self, "table") or self.table is None:
            return
        row_h = structure_row_default_height()
        col = CompoundTableModel.STRUCTURE_COL
        vh = self.table.verticalHeader()
        if vh is not None:
            vh.setDefaultSectionSize(row_h)
        zoomed = bool(getattr(self, "zoomed_ids", None))
        min_col = structure_column_minimum_width(zoomed=zoomed)
        self.table.set_structure_column_minimum_width(min_col)
        if int(self.table.columnWidth(col)) < min_col:
            self.table.setColumnWidth(col, min_col)
        if hasattr(self, "_table_model") and self._table_model is not None:
            self._table_model.notify_structure_column_changed()
        self.table.viewport().update()

    def apply_structure_depiict_size(self, width: int, height: int, *, persist: bool = True) -> None:
        """Apply depiction size from Settings and optionally re-render the Structure column."""
        from ...display_constants import set_structure_depiict_size

        set_structure_depiict_size(width, height, persist=persist)
        self.apply_structure_table_layout()
        if persist:
            self.rerender_structure_column_for_new_size()

    def rerender_structure_column_for_new_size(self) -> None:
        """Re-draw Structure cells after depiction size changed in Settings."""
        if not hasattr(self, "_table_model") or self._table_model.rowCount() <= 0:
            if hasattr(self, "_table_model") and self._table_model is not None:
                self._table_model.notify_structure_column_changed()
            return
        if getattr(self, "_render2d_batch_active", False) or self.process_queue.has_running_job():
            if hasattr(self, "status_label"):
                self.status_label.setText(
                    "Structure size saved. Re-draw structures when the current job finishes."
                )
            return
        self.zoomed_ids.clear()
        w, h = structure_depiict_width(), structure_depiict_height()
        renders, row_by_oid = self._build_render2d_tasks_in_table_order("Structure", w, h, None)
        self._table_model.clear_structure_png_store()
        if not renders:
            self._table_model.notify_structure_column_changed()
            return
        self._start_render_2d_batch(
            renders,
            row_by_oid,
            "Structure",
            column_pixmap_mode=False,
            queue_title_prefix="structure resize ",
        )

    def _sync_structure_column_width_for_zoom_state(self) -> None:
        """Set Structure column width from zoom state (O(1), no full-table scan)."""
        zoomed = bool(getattr(self, "zoomed_ids", None))
        need = structure_column_minimum_width(zoomed=zoomed)
        self.table.set_structure_column_minimum_width(need)
        col = CompoundTableModel.STRUCTURE_COL
        if int(self.table.columnWidth(col)) != need:
            self.table.setColumnWidth(col, need)

    def _normal_structure_pixmap_for_oid(self, oid: int) -> QPixmap | None:
        """Best-effort 1× depiction: PNG store, else scale down the in-memory pixmap."""
        store = self._table_model._structure_png_store
        if store is not None and store.has_png(oid):
            pm = store.pixmap(oid)
            if pm is not None and not pm.isNull():
                return pm
        current = self._table_model.structure_pixmap_for_oid(oid)
        if current is None or current.isNull():
            return None
        w, h = structure_depiict_width(), structure_depiict_height()
        if current.width() <= w and current.height() <= h:
            return current
        return current.scaled(w, h, Qt.KeepAspectRatio, Qt.SmoothTransformation)

    def _try_restore_structure_zoom_out(self, oid: int, view_row: int) -> bool:
        """Restore normal-size structure depiction without re-rendering when possible."""
        pm = self._normal_structure_pixmap_for_oid(oid)
        if pm is None or pm.isNull():
            return False
        self._table_model.set_structure_pixmap(oid, pm)
        self.table.setRowHeight(int(view_row), structure_depiict_height())
        self._sync_structure_column_width_for_zoom_state()
        return True

    def _sync_structure_column_width_for_pixmap(self, pm: QPixmap | None, fallback_w: int) -> None:
        """Grow the Structure column to fit the pixmap + padding (never shrink — avoids fighting user resizes)."""
        col = CompoundTableModel.STRUCTURE_COL
        pad = STRUCTURE_COLUMN_HORIZONTAL_PADDING
        pix_w = int(pm.width()) if pm is not None and not pm.isNull() else int(fallback_w)
        need = max(1, pix_w + pad)
        cur = int(self.table.columnWidth(col))
        if need > cur:
            self.table.setColumnWidth(col, need)
        if need > self.table.structure_column_minimum_width():
            self.table.set_structure_column_minimum_width(need)

    def _sync_data_pixmap_column_width(self, header_name: str, pm: QPixmap | None, fallback_w: int) -> None:
        try:
            col = self.headers.index(header_name)
        except ValueError:
            return
        pad = STRUCTURE_COLUMN_HORIZONTAL_PADDING
        pix_w = int(pm.width()) if pm is not None and not pm.isNull() else int(fallback_w)
        need = max(1, pix_w + pad)
        cur = int(self.table.columnWidth(col))
        if need > cur:
            self.table.setColumnWidth(col, need)

    def _render2d_batch_session_accepted(self, batch_session) -> bool:
        """False when a render result belongs to a superseded / cancelled batch."""
        rs = 0 if batch_session is None else int(batch_session)
        if rs == 0:
            return True
        cur = getattr(self, "_render2d_accept_session", None)
        return cur is not None and rs == cur

    def on_render2d_rows_ready(self, rows, batch_session) -> None:
        """Store one batch of subprocess render results (see ``WorkerSignals.rendered_batch``).

        The per-molecule path below does the same work one row at a time; batching keeps the GUI
        thread from being the bottleneck when tens of thousands of rows are drawn.
        """
        if not rows or not self._render2d_batch_session_accepted(batch_session):
            return
        pending = self._render2d_pending
        for oid, img, success, w, h in rows:
            oid = int(oid)
            if success and self._resolve_structure_row_for_oid(oid) != -1:
                pending[oid] = (bytes(img), True, int(w), int(h))
            else:
                pending[oid] = (b"", False, int(w), int(h))
        self._advance_render2d_batch_progress(len(rows))

    def _advance_render2d_batch_progress(self, n_done: int) -> None:
        """Report render progress and finish the batch once every row has landed."""
        if not getattr(self, "_import_progress_active", False) or self._import_render_goal <= 0:
            return
        self._import_render_done += int(n_done)
        done = min(self._import_render_done, self._import_render_goal)
        total_g = self._import_render_goal
        if getattr(self, "_render2d_batch_active", False):
            now = time.monotonic()
            last_t = float(getattr(self, "_render2d_progress_last_emit", 0.0))
            last_d = int(getattr(self, "_render2d_progress_last_done", 0))
            step = max(1, total_g // 50)
            if done <= 1 or done >= total_g or (done - last_d) >= step or (now - last_t) >= 0.12:
                self._render2d_progress_last_emit = now
                self._render2d_progress_last_done = done
                self._on_tool_progress(TOOL_RENDER_2D, done, total_g)
        else:
            self._on_tool_progress(TOOL_RENDER_2D, done, total_g)
        if self._import_render_done >= self._import_render_goal:
            self._import_progress_active = False
            self._clear_tool_progress()
            self.status_label.setText("Ready")
            self._flush_render2d_batch_results()
            self._restore_render2d_batch_environment()

    def on_row_ready(self, idx, props, img, success, w, h, batch_session=None):
        if not self._render2d_batch_session_accepted(batch_session):
            return

        row = self._resolve_structure_row_for_oid(int(idx))
        oid = int(idx)
        pix_target = getattr(self, "_render2d_pixmap_target", None)
        batch = getattr(self, "_render2d_batch_active", False)
        if success and row != -1:
            if batch:
                self._render2d_pending[oid] = (bytes(img), True, int(w), int(h))
            else:
                pm = pixmap_from_structure_render_png(img, w, h)
                if pix_target:
                    if getattr(self, "_render2d_column_pixmap_mode", True):
                        self._table_model.register_pixmap_column(pix_target)
                        self._table_model.set_column_pixmap(oid, pix_target, pm)
                    else:
                        self._table_model.set_cell_pixmap(oid, pix_target, pm)
                else:
                    self._table_model.set_structure_pixmap(oid, pm)
                if self.table.rowHeight(row) != h:
                    self.table.setRowHeight(row, h)
                if pix_target:
                    self._sync_data_pixmap_column_width(pix_target, pm, w)
                else:
                    self._sync_structure_column_width_for_pixmap(pm, w)
                if props:
                    updates = {name: str(props.get(name, "")) for name in self.headers[2:] if name in props}
                    if updates:
                        self._table_model.set_cell_text_batch(oid, updates)
                if not pix_target and oid not in self.zoomed_ids:
                    self._sync_structure_column_width_for_zoom_state()
        else:
            if batch:
                self._render2d_pending[oid] = (b"", False, int(w), int(h))

        self._advance_render2d_batch_progress(1)

    def _resize_columns_after_render2d(self, pix_target: str | None) -> None:
        """Set structure / pixmap column width from depict size (O(1), safe for huge tables)."""
        # Session restore owns column widths until chrome is fully reapplied.
        if getattr(self, "_pending_session_table_layout", None):
            return
        pad = STRUCTURE_COLUMN_HORIZONTAL_PADDING
        need = max(1, int(structure_depiict_width()) + pad)
        try:
            if pix_target:
                col = self.headers.index(pix_target)
                if self.table.columnWidth(col) < need:
                    self.table.setColumnWidth(col, need)
            else:
                self._sync_structure_column_width_for_pixmap(None, structure_depiict_width())
        except Exception:
            pass

    def _render2d_use_lazy_structure_flush(self, count: int, *, structure_column: bool) -> bool:
        if not structure_column:
            return False
        cfg = load_config()
        return count >= int(cfg.structure_render_lazy_min_rows)

    def _ensure_structure_lazy_scroll_hook(self) -> None:
        if getattr(self, "_structure_lazy_scroll_hooked", False):
            return
        try:
            self.table.verticalScrollBar().valueChanged.connect(self._on_structure_lazy_scroll)
            self._structure_lazy_scroll_hooked = True
        except Exception:
            pass

    def _on_structure_lazy_scroll(self, *_args) -> None:
        if not self._table_model.structure_png_store_active():
            return
        self._refresh_visible_structure_cells()

    def _refresh_visible_structure_cells(self) -> None:
        """Repaint only viewport-visible Structure cells (lazy PNG cache)."""
        m = self._table_model
        if m.rowCount() <= 0:
            return
        view = self.table
        try:
            r0 = view.rowAt(0)
            r1 = view.rowAt(max(0, view.viewport().height() - 1))
        except Exception:
            r0, r1 = 0, m.rowCount() - 1
        if r0 < 0:
            r0 = 0
        if r1 < 0:
            r1 = m.rowCount() - 1
        store = getattr(m, "_structure_png_store", None)
        if store is not None:
            keep: set[int] = set()
            for r in range(r0, r1 + 1):
                oid = m.row_oid(r)
                if store.has_png(oid):
                    keep.add(int(oid))
            store.trim_decoded_cache(keep_oids=keep)
        m.notify_structure_column_changed(r0, r1)

    def _flush_render2d_batch_results(self) -> None:
        """Apply buffered PNGs in slices so the GUI thread stays responsive."""
        if not getattr(self, "_render2d_batch_active", False):
            return
        pix_target = getattr(self, "_render2d_pixmap_target", None)
        column_pixmap_mode = getattr(self, "_render2d_column_pixmap_mode", True)
        lazy_structure = bool(getattr(self, "_render2d_lazy_flush", False)) and not pix_target

        queue = getattr(self, "_render2d_eager_flush_queue", None)
        if queue is None:
            self._render2d_accept_session = None
            ordered = list(getattr(self, "_render2d_batch_oids_ordered", []) or [])
            pending = getattr(self, "_render2d_pending", None) or {}
            if pix_target and column_pixmap_mode:
                self._table_model.register_pixmap_column(pix_target)
            set_pixmap = (
                self._table_model.set_column_pixmap
                if column_pixmap_mode
                else self._table_model.set_cell_pixmap
            )
            if lazy_structure:
                cfg = load_config()
                # Never cap below this completed batch size — otherwise Fast Prepare /
                # Tools → Render 2D silently drop earlier drawings (old default was 20k).
                cap = int(cfg.structure_render_png_max_entries)
                png_items: list[tuple[int, bytes]] = []
                for oid in ordered:
                    rec = pending.get(oid)
                    if not rec:
                        continue
                    img_b, ok, _rw, _rh = rec
                    if ok and img_b:
                        png_items.append((int(oid), bytes(img_b)))
                if cap > 0:
                    cap = max(cap, len(png_items))
                store = StructureRenderStore(
                    max_decoded_pixmaps=cfg.structure_render_pixmap_lru,
                    max_png_entries=cap,
                )
                if png_items:
                    store.ingest_batch(png_items)
                self._table_model.set_structure_png_store(store)
                self._ensure_structure_lazy_scroll_hook()
                self._render2d_eager_flush_queue = []
                self._render2d_eager_flush_idx = 0
                self._render2d_eager_uniform_height = False
            else:
                eager: list[tuple[int, QPixmap | None]] = []
                cfg = load_config()
                set_uniform_height = len(ordered) >= cfg.structure_render_lazy_min_rows
                for oid in ordered:
                    row = self._resolve_structure_row_for_oid(int(oid))
                    rec = pending.get(oid)
                    if not rec:
                        if pix_target:
                            set_pixmap(oid, pix_target, None)
                        else:
                            eager.append((int(oid), None))
                        continue
                    img_b, ok, rw, rh = rec
                    if not ok or row < 0:
                        if pix_target:
                            set_pixmap(oid, pix_target, None)
                        else:
                            eager.append((int(oid), None))
                        continue
                    pm = pixmap_from_structure_render_png(img_b, rw, rh)
                    if pix_target:
                        set_pixmap(oid, pix_target, pm)
                    else:
                        eager.append((int(oid), pm))
                    if row >= 0 and not set_uniform_height and self.table.rowHeight(row) != rh:
                        self.table.setRowHeight(row, rh)
                self._render2d_eager_flush_queue = eager if not pix_target else []
                self._render2d_eager_flush_idx = 0
                self._render2d_eager_uniform_height = bool(set_uniform_height and not pix_target)

        queue = getattr(self, "_render2d_eager_flush_queue", None) or []
        idx = int(getattr(self, "_render2d_eager_flush_idx", 0))
        if queue and idx < len(queue):
            chunk = 120
            try:
                self.table.setUpdatesEnabled(False)
            except Exception:
                pass
            try:
                slice_items = queue[idx : idx + chunk]
                self._table_model.apply_structure_pixmaps_batch(slice_items, emit=False)
            finally:
                try:
                    self.table.setUpdatesEnabled(True)
                except Exception:
                    pass
            self._render2d_eager_flush_idx = idx + len(slice_items)
            QTimer.singleShot(0, self._flush_render2d_batch_results)
            app = QApplication.instance()
            if app is not None:
                app.processEvents(QEventLoop.ExcludeUserInputEvents)
            return

        if queue and not pix_target:
            self._table_model.notify_structure_column_changed()
        if getattr(self, "_render2d_eager_uniform_height", False):
            default_rh = structure_row_default_height()
            vh = self.table.verticalHeader()
            try:
                vh.setSectionResizeMode(vh.Fixed)
                vh.setDefaultSectionSize(default_rh)
            except Exception:
                pass
        if lazy_structure:
            self._refresh_visible_structure_cells()

        self._render2d_pending = {}
        self._render2d_batch_oids_ordered = []
        self._render2d_snapshot = None
        self._render2d_lazy_flush = False
        self._render2d_eager_flush_queue = None
        self._render2d_eager_flush_idx = 0
        self._render2d_eager_uniform_height = False

    def on_cell_double_click(self, view_row, c):
        if c != 1:
            return
        src_row = self._view_row_to_source_row(view_row)
        t0 = self._table_model.cell_text(src_row, 0)
        if not t0.isdigit():
            return
        oid = int(t0)
        mol = self._mol_for_structure_row(src_row)
        if mol is None:
            self.status_label.setText("No structure available for this row.")
            return
        if oid in self.zoomed_ids:
            self.zoomed_ids.remove(oid)
            if self._try_restore_structure_zoom_out(oid, view_row):
                return
            w, h = structure_depiict_width(), structure_depiict_height()
        else:
            self.zoomed_ids.add(oid)
            w, h = structure_depiict_width() * 2, structure_depiict_height() * 2
        self.start_render_worker(oid, mol, w, h)
