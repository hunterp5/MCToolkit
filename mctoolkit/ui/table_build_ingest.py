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

"""File ingest chunks, silent-model append, and post-ingest follow-up."""

from __future__ import annotations

import logging
import time
from contextlib import nullcontext

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from ..chem.molecule_conversion import mol_from_binary_blob
from ..conformers.conformer_column_codec import (
    is_packed_ensemble_header,
    make_sidecar_cell,
    mol_has_3d_coordinates,
)
from ..platform_support.config import load_config
from ..storage import ensure_confs_sidecar
from ..table.text_file_ingest import is_ingest_cell_batch
from .strings import LOADING_DETAIL_AFTER_FILE_READ, STATUS_READY_RENDER_2D, TOOL_RENDER_2D

logger = logging.getLogger(__name__)


class TableBuildIngest:
    def _on_structure_source_probe(self, headers: list) -> None:
        """Worker paused after first record; pick structure column before bulk read."""
        incoming = list(headers)
        if self._app._ingest_append_mode and self._app._table_model.rowCount() > 0:
            self._app._merge_import_headers(incoming)
        else:
            self._app.headers = incoming
        from ..chem.structure_source_headers import structure_source_picker_candidates
        from .dialogs.structure_source import StructureSourcePickerDialog

        struct_cols = structure_source_picker_candidates(self._app.headers)
        if len(struct_cols) >= 2:
            picked, ok = StructureSourcePickerDialog.pick_column(self._app, struct_cols)
            if ok and picked:
                self._app._structure_field_override = picked
            elif not ok:
                self._app._structure_field_override = None
        ev = getattr(self._app, "_structure_choice_event", None)
        if ev is not None:
            ev.set()

    def _maybe_start_ingest_processing(self) -> None:
        if self._app._processing_batches:
            return
        if not self._app._pending_batches and not self._app._last_batch_received:
            return
        self._app._processing_batches = True
        QTimer.singleShot(0, self._process_next_chunk)

    def _ingest_use_silent_model(self) -> bool:
        return bool(load_config().ingest_silent_model_append)

    def _ingest_use_sqlite_incremental(self) -> bool:
        return bool(load_config().ingest_sqlite_incremental)

    def _sqlite_data_headers(self) -> list[str]:
        return [
            h
            for h in self._app.headers[2:]
            if h and not self._app._table_model.is_pixmap_data_column(h)
        ]

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
        store = getattr(self._app, "_sqlite_store", None)
        if store is None or not self._ingest_use_sqlite_incremental():
            return
        data_headers = self._sqlite_data_headers()
        if self._app._ingest_append_mode and self._app._table_model.rowCount() > 0:
            if frozenset(store.headers) != frozenset(data_headers):
                return
            self._app._ingest_sqlite_bulk_active = True
            self._app._ingest_sqlite_bulk_headers = list(data_headers)
            self._app._ingest_sqlite_paused_dirty = True
            return
        try:
            store.begin_bulk_load(self._app.headers)
        except Exception:
            logger.exception("Failed to begin incremental SQLite ingest")
            self._app._ingest_sqlite_bulk_active = False
            self._app._ingest_sqlite_paused_dirty = False
            return
        self._app._ingest_sqlite_bulk_active = True
        self._app._ingest_sqlite_bulk_headers = list(data_headers)
        self._app._ingest_sqlite_paused_dirty = True

    def _ingest_sqlite_append_batch(self, new_rows: list[tuple[int, dict[str, str]]]) -> None:
        if not getattr(self._app, "_ingest_sqlite_bulk_active", False) or not new_rows:
            return
        store = getattr(self._app, "_sqlite_store", None)
        headers = getattr(self._app, "_ingest_sqlite_bulk_headers", None)
        if store is None or not headers:
            return
        try:
            store.append_bulk_rows(self._ingest_sqlite_entries_from_rows(new_rows, headers))
        except Exception:
            logger.exception("Incremental SQLite ingest append failed")
            self._app._ingest_sqlite_bulk_active = False
            self._app._ingest_sqlite_paused_dirty = False
            self._app._sqlite_store_dirty = True

    def _ingest_sqlite_finalize_bulk(self) -> bool:
        """Return True when the SQLite mirror is ready and no rebuild is needed."""
        if not getattr(self._app, "_ingest_sqlite_bulk_active", False):
            self._app._ingest_sqlite_paused_dirty = False
            return False
        store = getattr(self._app, "_sqlite_store", None)
        self._app._ingest_sqlite_bulk_active = False
        self._app._ingest_sqlite_paused_dirty = False
        self._app._ingest_sqlite_bulk_headers = None
        if store is None:
            return False
        if store.bulk_loading:
            try:
                store.finalize_bulk_load()
            except Exception:
                logger.exception("Failed to finalize incremental SQLite ingest")
                self._app._sqlite_store_dirty = True
                return False
        self._app._sqlite_store_dirty = False
        return True

    def _ingest_begin_silent_if_needed(self) -> None:
        if self._ingest_use_silent_model() and not self._app._table_model.silent_appending:
            self._app._table_model.begin_silent_appends()

    def _ingest_append_batch_items(
        self, items: list, new_rows: list[tuple[int, dict[str, str]]]
    ) -> None:
        """Convert one worker batch (mol blobs or cell dicts) into pending table rows."""
        if is_ingest_cell_batch(items):
            for cells in items:
                oid = self._app.next_oid
                self._app.next_oid += 1
                new_rows.append((oid, dict(cells)))
            return
        override_field = getattr(self._app, "_structure_field_override", None)
        # Structures go to the store in one write per batch; see ``_ingest_store_mol``.
        batch: list | None = (
            [] if callable(getattr(self._app.mols, "ingest_structures", None)) else None
        )
        for item in items:
            blob, cells = self._split_ingest_item(item)
            source_blob = blob if isinstance(blob, (bytes, bytearray)) else None
            if override_field:
                m, precomputed = self._resolve_override_ingest_mol(blob, cells, override_field)
                if precomputed is None:
                    # The override parsed a different column, so the worker blob is not this mol.
                    source_blob = None
            else:
                m = self._coerce_ingest_mol(blob)
                precomputed = cells
            oid = self._app.next_oid
            self._app.next_oid += 1
            new_rows.append(
                (
                    oid,
                    self._ingest_store_mol(
                        oid,
                        m,
                        precomputed_cells=precomputed,
                        source_blob=source_blob,
                        batch=batch,
                    ),
                )
            )
        if batch:
            self._app.mols.ingest_structures(batch)

    def _resolve_override_ingest_mol(self, blob, cells, field: str):
        """Apply a structure-column override during ingest, reading the field from the cell dict.

        Ingest blobs carry structure only (no properties), so the override source column is taken
        from the worker-built cells. When it parses, cells are recomputed from the override mol
        (matching the non-blob behavior); otherwise the parsed structure and its cells are kept.
        """
        raw = (cells.get(field) or "").strip() if isinstance(cells, dict) else ""
        if raw:
            nm = self._app._mol_from_structure_text(raw)
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
    def _coerce_ingest_mol(item) -> object | None:
        """Rebuild a live RDKit mol from an ingest blob (worker sends binary to avoid UI freezes)."""
        if isinstance(item, (bytes, bytearray)):
            return mol_from_binary_blob(item)
        return item

    def _ingest_store_mol(
        self,
        oid: int,
        mol: object,
        precomputed_cells: dict[str, str] | None = None,
        *,
        source_blob: bytes | None = None,
        batch: list | None = None,
    ) -> dict[str, str]:
        """
        Store *mol* for row *oid*.

        When the molecule carries 3D coordinates, pack them into ``confs`` (for View
        Conformers) and keep a 2D depiction in ``self._app.mols`` for the Structure column.

        *precomputed_cells* are row cells built off the GUI thread by the load worker; when
        provided they are used verbatim (avoids re-reading every property on the GUI thread).

        *batch*, when given, collects ``(oid, mol, blob, smiles)`` for one bulk store write
        instead of a per-row insert. *source_blob* is the load worker's already-serialized
        structure, reused so ingest never re-pickles a molecule the worker just pickled.
        """
        cells = (
            dict(precomputed_cells)
            if precomputed_cells is not None
            else self._app._row_cells_from_mol(mol)
        )
        if mol is not None and mol_has_3d_coordinates(mol):
            from .mol_viewer_3d import prepare_mol_2d

            self._app._ensure_columns(["confs"])
            try:
                n_conf = int(mol.GetNumConformers())
            except Exception:
                n_conf = 0
            meta = {
                "ok": True,
                "op": "ingest",
                "n_kept": n_conf,
                "n_packed": n_conf,
            }
            sc = ensure_confs_sidecar(self._app)
            sc.store_mol(int(oid), "confs", mol)
            light = make_sidecar_cell("confs", meta)
            depict = prepare_mol_2d(mol)
            # The depiction is a fresh 2D copy, so the worker blob does not describe it.
            self._ingest_remember_mol(
                oid, depict if depict is not None else mol, None, cells, batch
            )
            cells["confs"] = light
            return cells
        self._ingest_remember_mol(oid, mol, source_blob, cells, batch)
        return cells

    def _ingest_remember_mol(
        self,
        oid: int,
        mol: object | None,
        source_blob: bytes | None,
        cells: dict[str, str],
        batch: list | None,
    ) -> None:
        """Hand one ingested structure to the molecule store, batched when the store supports it."""
        if batch is None:
            self._app.mols[oid] = mol
            return
        if mol is None:
            return
        # The store keeps connection tables only. The worker blob matches that byte for byte
        # when the molecule carries no conformers; otherwise it has coordinates to strip.
        if source_blob is not None and mol.GetNumConformers():
            source_blob = None
        batch.append((int(oid), mol, source_blob, str(cells.get("SMILES") or "")))

    def on_file_loaded(self, mols_list, headers, is_first, is_last):
        # Append batch to pending queue and schedule incremental processing
        if is_first:
            self._app._clear_filter_target_smiles_cache()
            incoming = list(headers)
            if self._app._ingest_append_mode and self._app._table_model.rowCount() > 0:
                self._app._merge_import_headers(incoming)
            else:
                self._app.headers = incoming
                self._app.table.setSortingEnabled(False)
                self._app._table_model.clear_rows()
                self._app._table_model.set_headers(list(self._app.headers))
                self._app.table.setColumnHidden(0, True)
            if self._app._table_stack.currentIndex() == 0:
                self._app._loading_detail.setText(LOADING_DETAIL_AFTER_FILE_READ)
            self._ingest_begin_silent_if_needed()
            self._ingest_sqlite_begin_bulk()
        if mols_list:
            self._app._pending_batches.append((mols_list, is_last))
        if is_last:
            self._app._last_batch_received = True
        if mols_list and not self._app._processing_batches:
            self._ingest_begin_silent_if_needed()
        self._maybe_start_ingest_processing()

    def _process_next_chunk(self, chunk_size: int | None = None):
        cfg = load_config()
        if chunk_size is None:
            chunk_size = int(cfg.ingest_gui_chunk_size)
        budget_s = max(0.005, int(cfg.ingest_gui_time_budget_ms) / 1000.0)
        deadline = time.monotonic() + budget_s
        processed = 0
        perf = getattr(self._app, "_perf", None)
        scope = perf.track if perf is not None else (lambda *_args, **_kwargs: nullcontext())
        try:
            self._app.table.setUpdatesEnabled(False)
        except Exception:
            pass
        # Consume each worker batch in small sub-slices, re-checking the time budget between them,
        # so a single tick stays near ``ingest_gui_time_budget_ms`` even as per-row cost grows
        # (mol rebuild + property extraction + SQLite). This keeps the UI smooth during ingest.
        sub_slice = max(32, min(int(chunk_size), int(cfg.ingest_gui_subslice_rows)))
        try:
            with scope("ingest.process_chunk"):
                while (
                    self._app._pending_batches
                    and processed < chunk_size
                    and time.monotonic() < deadline
                ):
                    mols_list, is_last = self._app._pending_batches[0]
                    step = min(len(mols_list), sub_slice, max(0, int(chunk_size - processed)))
                    if step:
                        take = mols_list[:step]
                        new_rows: list[tuple[int, dict[str, str]]] = []
                        self._ingest_append_batch_items(take, new_rows)
                        self._app._table_model.append_rows_batch(new_rows, defer_color_cache=True)
                        self._ingest_sqlite_append_batch(new_rows)
                        processed += len(new_rows)
                        del mols_list[:step]
                    if not mols_list:
                        self._app._pending_batches.pop(0)
                        if is_last:
                            self._app._last_batch_received = True
            if processed:
                n = self._app._table_model.rowCount()
                self._app.status_label.setText(f"Loaded {n:,} molecules — preparing table…")
                if self._app._table_stack.currentIndex() == 0:
                    self._app._loading_detail.setText(
                        f"Building table…\n{n} molecule(s); 2D structures draw after the table is shown"
                    )
                if (
                    getattr(self._app, "_ingest_loading", False)
                    and not self._app._import_building_progress_shown
                ):
                    self._app._import_building_progress_shown = True
                    self._app._on_tool_progress("Building table…", -1, -1)
        finally:
            try:
                self._app.table.setUpdatesEnabled(True)
            except Exception:
                pass

        if self._app._pending_batches:
            QTimer.singleShot(0, lambda: self._process_next_chunk(chunk_size))
        elif self._app._last_batch_received:
            QTimer.singleShot(0, self._finalize_ingest_on_gui_thread)
        else:
            self._app._processing_batches = False

    def _finalize_ingest_on_gui_thread(self) -> None:
        """Finish ingest on the loading page; reveal once filters and auto 2D are ready."""
        if self._app._table_model.silent_appending:
            self._app._table_model.end_silent_appends()
        if not self._ingest_sqlite_finalize_bulk():
            if getattr(self._app, "_sqlite_store", None) is not None:
                self._app._sqlite_store_dirty = True
            else:
                self._rebuild_sqlite_store_from_model()
        self._app.table.setSortingEnabled(False)
        self._app._structures_queued = 0
        self._app._ingest_prep_before_reveal = True
        try:
            self._app.table.setUpdatesEnabled(False)
        except Exception:
            pass
        self._app._import_progress_active = False
        self._app._clear_tool_progress(status_message=None)
        self._app._ingest_append_mode = False
        self._app._last_batch_received = False
        self._app._processing_batches = False
        n = self._app._table_model.rowCount()
        self._app._loading_detail.setText(
            f"Table built ({n:,} row(s)).\nPreparing table, then {TOOL_RENDER_2D}…"
        )
        if any(is_packed_ensemble_header(h) for h in self._app.headers):
            QTimer.singleShot(0, self._app._migrate_legacy_confs_cells_to_sidecar)
        QTimer.singleShot(0, self._deferred_post_ingest_follow_up)

    def _deferred_post_ingest_follow_up(self) -> None:
        """Runs on the loading page: color caches and bounds, then reveal; auto 2D follows."""
        headers = self._app._table_model.pending_color_cache_headers()
        if headers:
            self._app._post_ingest_color_headers = headers
            self._app._post_ingest_color_idx = 0
            QTimer.singleShot(0, self._post_ingest_color_cache_step)
            return
        self._post_ingest_after_color_caches()

    def _post_ingest_color_cache_step(self) -> None:
        headers = getattr(self._app, "_post_ingest_color_headers", None) or []
        idx = int(getattr(self._app, "_post_ingest_color_idx", 0))
        if idx < len(headers):
            if getattr(self._app, "_ingest_prep_before_reveal", False):
                self._app._loading_detail.setText(
                    f"Preparing conditional formatting…\n({idx + 1}/{len(headers)} columns)"
                )
            self._app._table_model._rebuild_column_color_cache(headers[idx])
            self._app._post_ingest_color_idx = idx + 1
            QTimer.singleShot(0, self._post_ingest_color_cache_step)
            return
        self._app._post_ingest_color_headers = []
        self._post_ingest_after_color_caches()

    def _post_ingest_after_color_caches(self) -> None:
        """Finish filter bounds, then auto Render 2D; reveal after bounds are ready."""
        self._app._ingest_waiting_for_render = False
        if getattr(self._app, "_ingest_prep_before_reveal", False):
            self._app._loading_detail.setText("Preparing filters…")
        self._app.calculate_global_bounds(on_complete=self._post_ingest_after_bounds)

    def _post_ingest_after_bounds(self) -> None:
        """Start auto Render 2D after bounds; show the table without waiting on images."""
        n = self._app._table_model.rowCount()
        started_render = self._try_auto_render_all_structures_after_ingest()
        if started_render and self._auto_render2d_blocks_workspace_reveal(n):
            self._app._loading_detail.setText(f"{TOOL_RENDER_2D}…\n{n:,} row(s)")
            self._app._ingest_waiting_for_render = True
            return
        keep_status = started_render or "auto 2D render skipped" in (
            self._app.status_label.text() or ""
        )
        self._reveal_table_after_ingest_prep(keep_status=keep_status)

    def _ingest_on_render2d_batch_finished(self) -> None:
        """Reveal the workspace after auto Render 2D if ingest was waiting on it."""
        if not getattr(self._app, "_ingest_waiting_for_render", False):
            return
        self._app._ingest_waiting_for_render = False
        self._reveal_table_after_ingest_prep()

    def _reveal_table_after_ingest_prep(self, *, keep_status: bool = False) -> None:
        """Switch from the loading page to the table once rows and filter bounds are ready."""
        self._app._ingest_prep_before_reveal = False
        self._app._ingest_waiting_for_render = False
        self._app._set_ingest_loading(False)
        self._app._set_workspace_stack_index(1)
        finish_clean = getattr(self._app, "_finish_session_clean_if_pending", None)
        if callable(finish_clean):
            finish_clean()
        app = QApplication.instance()
        if app is not None:
            app.processEvents(QEventLoop.ExcludeUserInputEvents)
        try:
            self._app.table.setUpdatesEnabled(True)
        except Exception:
            pass
        if keep_status:
            return
        n = self._app._table_model.rowCount()
        self._app.status_label.setText(STATUS_READY_RENDER_2D if n else "Ready.")
