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

"""Batch 2D structure rendering for the main table."""

from __future__ import annotations

import threading

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox
from ..chem.molecule_conversion import is_rdkit_mol
from ..chem.reaction_file_io import looks_like_reaction_smarts, parse_reaction_smarts
from ..chem.structure_2d_depiction import ReactionDrawSpec
from ..platform_support.config import load_config
from ..table.structure_depiction_layout import (
    reaction_depict_size,
    structure_depict_height,
    structure_depict_width,
)
from ..workers import (
    STRUCTURE_PAYLOAD_TAG,
    Render2DBatchHeldJob,
    Render2DBatchProcessWorker,
)
from .strings import TOOL_RENDER_2D
from .background_activity import RENDER2D_PROCESS_JOB_ID


class TableBuildRender:
    def _build_render2d_tasks_from_mols(
        self,
        base_w: int,
        base_h: int,
        allowed_oids: set[int] | None = None,
    ) -> tuple[list, dict[int, int]]:
        """Build render tasks from ``self._app.mols`` (O(n) with O(1) row lookup; used after file/SQL ingest).

        Structures stay serialized. The render subprocesses rebuild each one themselves, so
        hydrating RDKit mols here only to re-pickle them in the worker costs seconds of GUI
        freeze on large tables.
        """
        renders: list = []
        row_by_oid: dict[int, int] = {}
        row_for_oid = self._app._table_model.logical_row_for_oid
        zoom_w, zoom_h = structure_depict_width() * 2, structure_depict_height() * 2
        for oid, payload in self._iter_render2d_structure_payloads():
            if allowed_oids is not None and oid not in allowed_oids:
                continue
            row = row_for_oid(oid)
            if row < 0:
                continue
            rw, rh = (zoom_w, zoom_h) if oid in self._app.zoomed_ids else (base_w, base_h)
            renders.append((oid, payload, rw, rh))
            row_by_oid[oid] = row
        return renders, row_by_oid

    def _iter_render2d_structure_payloads(self):
        """Yield ``(oid, payload)`` for every stored structure, preferring unhydrated payloads.

        ``payload`` is a :data:`STRUCTURE_PAYLOAD_TAG` tuple when the store can hand over raw
        bytes, otherwise a live mol (plain-dict stores used by tests and older sessions).
        """
        store = self._app.mols
        bulk = getattr(store, "iter_structure_payloads", None)
        if not callable(bulk):
            for oid in list(store):
                mol = store.get(int(oid))
                if mol is not None:
                    yield int(oid), mol
            return
        for oid, blob, smiles in bulk():
            if not blob and not smiles:
                continue
            yield oid, (STRUCTURE_PAYLOAD_TAG, blob or b"", smiles.encode("utf-8"))

    def _build_render2d_tasks_in_table_order(
        self,
        src: str,
        base_w: int,
        base_h: int,
        allowed_oids: set[int] | None = None,
    ) -> tuple[list, dict[int, int]]:
        """Collect (oid, mol, w, h) tasks in current visual row order (top to bottom) and oid→row map."""
        renders = []
        row_by_oid: dict[int, int] = {}
        if src != "Structure" and src not in self._app.headers:
            return [], {}
        for r in range(self._app._table_model.rowCount()):
            t0 = self._app._table_model.cell_text(r, 0)
            if not t0.isdigit():
                continue
            oid = int(t0)
            if allowed_oids is not None and oid not in allowed_oids:
                continue
            if src == "Structure":
                mol = self._app.mols.get(oid)
                if mol is None:
                    mol = self._app._mol_for_structure_row(r)
                if mol is None:
                    continue
                self._app.mols[oid] = mol
                payload = mol
            else:
                payload = self._depict_payload_for_render2d_source(r, src)
                if payload is None:
                    continue
            zoomed = oid in self._app.zoomed_ids
            if isinstance(payload, ReactionDrawSpec):
                rw, rh = reaction_depict_size(zoomed=zoomed)
            elif zoomed:
                rw, rh = structure_depict_width() * 2, structure_depict_height() * 2
            else:
                rw, rh = base_w, base_h
            renders.append((oid, payload, rw, rh))
            row_by_oid[oid] = r
        return renders, row_by_oid

    def _build_render2d_tasks_for_oids(
        self,
        oids: list[int],
        base_w: int,
        base_h: int,
    ) -> tuple[list, dict[int, int]]:
        """Build render tasks for explicit oids (O(n) in ``oids``; used after bulk external append)."""
        renders: list = []
        row_by_oid: dict[int, int] = {}
        for oid in oids:
            row = self._app._table_model.logical_row_for_oid(int(oid))
            if row < 0:
                continue
            mol = self._app.mols.get(int(oid))
            if mol is None:
                mol = self._app._mol_for_structure_row(row)
            if mol is None:
                continue
            self._app.mols[int(oid)] = mol
            rw, rh = (
                (structure_depict_width() * 2, structure_depict_height() * 2)
                if int(oid) in self._app.zoomed_ids
                else (base_w, base_h)
            )
            renders.append((int(oid), mol, rw, rh))
            row_by_oid[int(oid)] = row
        return renders, row_by_oid

    def _try_auto_render_all_structures_after_ingest(self) -> bool:
        """Queue 2D renders for every row with an in-memory Structure mol (file ingest, SQL, or session)."""
        if getattr(self._app, "_render2d_batch_active", False):
            return False
        if not self._app.headers or self._app._table_model.rowCount() == 0:
            return False
        n_rows = self._app._table_model.rowCount()
        cfg = load_config()
        max_auto = int(cfg.auto_render_2d_max_rows)
        if max_auto > 0 and n_rows > max_auto:
            self._app.status_label.setText(
                f"Loaded {n_rows:,} rows — auto 2D render skipped (limit {max_auto:,}). "
                "Use Tools → Render 2D for visible or selected rows."
            )
            return False
        self._app.status_label.setText(f"{TOOL_RENDER_2D}: collecting structures…")
        base_w, base_h = structure_depict_width(), structure_depict_height()
        renders, row_by_oid = self._build_render2d_tasks_from_mols(base_w, base_h, None)
        if not renders:
            # Session restore may have rows before mols are keyed; rebuild from table cells.
            renders, row_by_oid = self._build_render2d_tasks_in_table_order(
                "Structure", base_w, base_h, None
            )
        if not renders:
            return False
        self._app._render2d_after_ingest = True
        self._start_render_2d_batch(renders, row_by_oid, "Structure")
        return True

    def _auto_render2d_blocks_workspace_reveal(self, n_rows: int | None = None) -> bool:
        """Ingest reveal stays independent of auto Render 2D.

        Session Open waits on ``_session_waiting_for_render`` instead. ``n_rows`` is
        accepted for call-site compatibility.
        """
        _ = n_rows
        return False

    def _restore_render2d_batch_environment(self) -> None:
        """Re-enable sorting and thread pool after a Render 2D run (or if cleared mid-batch)."""
        self._app._render2d_accept_session = None
        self._app._render2d_pending = {}
        self._app._render2d_batch_oids_ordered = []
        self._app._render2d_snapshot = None
        self._app._render2d_eager_flush_queue = None
        self._app._render2d_eager_flush_idx = 0
        self._app._render2d_eager_uniform_height = False
        self._app._render2d_row_by_oid = None
        pix_target = getattr(self._app, "_render2d_pixmap_target", None)
        self._app._render2d_pixmap_target = None
        self._app._render2d_column_pixmap_mode = True
        self._resize_columns_after_render2d(pix_target)
        finishing_batch = bool(getattr(self._app, "_render2d_batch_active", False))
        if finishing_batch:
            pending = getattr(self._app, "_pending_session_table_layout", None)
            restore_chrome = getattr(self._app, "_restore_session_table_chrome", None)
            if pending and callable(restore_chrome):
                restore_chrome(pending)
            elif pending:
                restore = getattr(self._app, "_restore_table_layout", None)
                if callable(restore):
                    restore(pending)
            restore_ws = getattr(self._app, "_restore_pending_workspace_layout", None)
            if callable(restore_ws):
                restore_ws()
            finish_ws = getattr(self._app, "_finish_deferred_session_workspace_restore", None)
            if callable(finish_ws):
                from PySide6.QtCore import QTimer

                QTimer.singleShot(0, finish_ws)
        try:
            self._app.table.setUpdatesEnabled(True)
        except Exception:
            pass
        if self._app._render2d_saved_sort_enabled is not None:
            try:
                self._app.table.setSortingEnabled(self._app._render2d_saved_sort_enabled)
            except Exception:
                pass
            self._app._render2d_saved_sort_enabled = None
        self._app._render2d_batch_active = False
        self._app._render2d_cancel_event = None
        hub = getattr(self._app, "background_activity", None)
        if hub is not None:
            hub.notify_changed()
        done_ev = getattr(self._app, "_render2d_batch_done_event", None)
        if done_ev is not None:
            done_ev.set()
        pq = getattr(self._app, "process_queue", None)
        if pq is not None:
            pq.schedule_resume()
        on_ingest = getattr(self, "_ingest_on_render2d_batch_finished", None)
        if callable(on_ingest):
            on_ingest()
        on_session = getattr(self._app, "_session_on_render2d_batch_finished", None)
        if callable(on_session):
            on_session()

    def _running_process_queue_title(self) -> str:
        """Title of the serial process-queue job, or ``""`` if none is running."""
        pq = getattr(self._app, "process_queue", None)
        if pq is None or not pq.has_running_job():
            return ""
        snap = pq.snapshot() if hasattr(pq, "snapshot") else {}
        return str((snap.get("running") or {}).get("title") or "")

    def _render2d_shares_ui_with_queue_job(self) -> bool:
        """True when Render 2D is drawing while another serial tool owns the status line."""
        title = self._running_process_queue_title()
        return bool(title) and "render 2d" not in title.lower()

    def cancel_render_2d_batch(self) -> bool:
        """Stop a Tools → Render 2D batch: no further chunks, workers skip drawing if not started."""
        if not self._app._render2d_batch_active:
            return False
        ev = getattr(self._app, "_render2d_cancel_event", None)
        if ev is not None:
            ev.set()
        self._app._render2d_queue = None
        self._app._render2d_accept_session = None
        self._app._render2d_pending.clear()
        self._app._render2d_batch_oids_ordered.clear()
        self._app._render2d_eager_flush_queue = None
        self._app._render2d_eager_flush_idx = 0
        self._app._render2d_eager_uniform_height = False
        if getattr(self._app, "_render2d_lazy_flush", False) and not getattr(
            self._app, "_render2d_pixmap_target", None
        ):
            self._app._table_model.clear_structure_png_store()
        snap = getattr(self._app, "_render2d_snapshot", None)
        target = getattr(self._app, "_render2d_pixmap_target", None)
        if snap:
            column_pixmap_mode = getattr(self._app, "_render2d_column_pixmap_mode", True)
            set_pixmap = (
                self._app._table_model.set_column_pixmap
                if column_pixmap_mode
                else self._app._table_model.set_cell_pixmap
            )
            for oid, pm in snap.items():
                if target:
                    set_pixmap(oid, target, pm)
                else:
                    self._app._table_model.set_structure_pixmap(oid, pm)
        self._app._render2d_snapshot = None
        self._app._render2d_lazy_flush = False
        self._app._render2d_eager_flush_queue = None
        self._app._render2d_eager_flush_idx = 0
        self._app._render2d_eager_uniform_height = False
        self._app._import_progress_active = False
        if not self._render2d_shares_ui_with_queue_job():
            self._app._clear_tool_progress()
        self._restore_render2d_batch_environment()
        return True

    def run_render_2d_structures(self) -> None:
        """Queue 2D structure renders for all rows (after deferred load)."""
        if not self._app.headers or self._app._table_model.rowCount() == 0:
            QMessageBox.information(
                self._app, TOOL_RENDER_2D, "Load a table with at least one row first."
            )
            return
        if self._app._render2d_batch_active:
            QMessageBox.warning(
                self._app,
                TOOL_RENDER_2D,
                "A 2D render is already running. Wait for it to finish or cancel it from Processes.",
            )
            return
        candidates = self._app.chemistry_tool_structure_sources()
        from .dialogs import Render2DStructureDialog

        rd = Render2DStructureDialog(candidates, len(self._app._selected_logical_rows()), self._app)
        self._app._prepare_tool_dialog(rd)
        rd.setAttribute(Qt.WA_DeleteOnClose, True)
        rd.accepted.connect(lambda *_, d=rd: self._on_render_2d_dialog_accepted(d))
        rd.show()

    def _on_render_2d_dialog_accepted(self, rd) -> None:
        src = rd.chosen_source()
        only_selected = rd.only_selected_rows()
        allowed_oids = self._app._selected_oids_set() if only_selected else None
        if self._app._abort_if_only_selected_but_empty(only_selected, allowed_oids, TOOL_RENDER_2D):
            return
        if not self._render2d_shares_ui_with_queue_job():
            self._app.status_label.setText(f"{TOOL_RENDER_2D}: collecting structures…")
        base_w, base_h = structure_depict_width(), structure_depict_height()
        renders, row_by_oid = self._build_render2d_tasks_in_table_order(
            src, base_w, base_h, allowed_oids
        )
        if not renders:
            QMessageBox.information(
                self._app,
                TOOL_RENDER_2D,
                "No valid structures were found for the selected source.",
            )
            self._app.status_label.setText("No structures rendered.")
            return
        self._start_render_2d_batch(
            renders, row_by_oid, src, column_pixmap_mode=(src != "Structure")
        )

    def _start_render_2d_batch(
        self,
        renders,
        row_by_oid,
        src: str = "Structure",
        *,
        column_pixmap_mode: bool = True,
        queue_title_prefix: str = "",
    ) -> None:
        """Start a batch 2D render.

        When the serial process queue is idle, the job is queued (and typically starts
        immediately). When another tool is already running, the render starts off-queue
        so structures can be drawn without waiting for that tool to finish.
        """
        if getattr(self._app, "_render2d_batch_active", False):
            return
        if self._render2d_shares_ui_with_queue_job():
            self._begin_render2d_batch_impl(
                renders,
                row_by_oid,
                src,
                column_pixmap_mode=column_pixmap_mode,
            )
            return
        title = f"{queue_title_prefix}render 2D ({len(renders)} rows)".strip()
        payload = (renders, row_by_oid, src, column_pixmap_mode)
        self._app.process_queue.enqueue(
            title,
            lambda ev, p=payload: Render2DBatchHeldJob(self._app, p, ev),
        )

    def _begin_render2d_batch_impl(
        self,
        renders,
        row_by_oid,
        src: str = "Structure",
        *,
        column_pixmap_mode: bool = True,
        cancel_event: threading.Event | None = None,
    ) -> None:
        """Start batch 2D rendering on the GUI thread (called from :class:`Render2DBatchHeldJob`)."""
        if cancel_event is not None and cancel_event.is_set():
            return
        self._app._render2d_session_id += 1
        self._app._render2d_batch_session_tag = self._app._render2d_session_id
        self._app._render2d_accept_session = self._app._render2d_batch_session_tag
        self._app._render2d_pixmap_target = None if src == "Structure" else src
        self._app._render2d_column_pixmap_mode = bool(column_pixmap_mode)
        if self._app._render2d_pixmap_target and self._app._render2d_column_pixmap_mode:
            self._app._table_model.register_pixmap_column(self._app._render2d_pixmap_target)
        self._app._render2d_saved_sort_enabled = self._app.table.isSortingEnabled()
        self._app.table.setSortingEnabled(False)
        self._app._render2d_batch_active = True
        self._app._render2d_row_by_oid = row_by_oid
        oids = [oid for oid, _, _, _ in renders]
        self._app._render2d_batch_oids_ordered = oids
        self._app._render2d_pending = {}
        structure_column = self._app._render2d_pixmap_target is None
        after_ingest = bool(getattr(self._app, "_render2d_after_ingest", False))
        self._app._render2d_after_ingest = False
        cfg = load_config()
        if after_ingest and structure_column:
            lazy_structure = len(oids) >= int(cfg.structure_render_lazy_after_ingest_min_rows)
        else:
            lazy_structure = self._render2d_use_lazy_structure_flush(
                len(oids), structure_column=structure_column
            )
        self._app._render2d_lazy_flush = lazy_structure
        skip_snapshot = after_ingest or lazy_structure
        tgt = self._app._render2d_pixmap_target
        if tgt:
            if self._app._render2d_column_pixmap_mode:
                self._app._render2d_snapshot = self._app._table_model.snapshot_column_pixmaps(
                    tgt, oids
                )
                clear_pixmap = self._app._table_model.set_column_pixmap
            else:
                self._app._render2d_snapshot = {
                    oid: self._app._table_model.cell_pixmap_copy(oid, tgt) for oid in oids
                }
                clear_pixmap = self._app._table_model.set_cell_pixmap
            for oid in oids:
                clear_pixmap(oid, tgt, None)
        elif lazy_structure:
            self._app._render2d_snapshot = {}
            self._app._table_model.clear_structure_png_store()
            self._app._table_model.clear_structure_pixmaps_for_oids(oids, emit=False)
        else:
            if skip_snapshot:
                self._app._render2d_snapshot = {}
            elif len(oids) <= cfg.structure_render_lazy_min_rows:
                self._app._render2d_snapshot = self._app._table_model.snapshot_structure_pixmaps(
                    oids
                )
            else:
                self._app._render2d_snapshot = {}
            self._app._table_model.clear_structure_pixmaps_for_oids(oids, emit=False)
        if structure_column and not lazy_structure:
            self._app._table_model.notify_structure_column_changed()
        self._app._render2d_progress_last_emit = 0.0
        self._app._render2d_progress_last_done = 0
        self._app._import_progress_active = True
        self._app._import_render_goal = len(renders)
        self._app._import_render_done = 0
        if not self._render2d_shares_ui_with_queue_job():
            self._app._on_tool_progress(
                TOOL_RENDER_2D, 0, len(renders), job_id=RENDER2D_PROCESS_JOB_ID
            )
        self._app._render2d_cancel_event = (
            cancel_event if cancel_event is not None else threading.Event()
        )
        self._app._render2d_queue = None
        hub = getattr(self._app, "background_activity", None)
        if hub is not None:
            hub.notify_changed()
        self._app._render_threadpool.start(
            Render2DBatchProcessWorker(
                renders,
                self._app.signals,
                self._app._render2d_cancel_event,
                self._app._render2d_batch_session_tag,
            )
        )

    def _render2d_source_header_for_column(self, col: int) -> str:
        """Header used as Render 2D source and pixmap target (clicked column, else Structure)."""
        if 0 <= col < len(self._app.headers):
            return self._app.headers[col]
        return "Structure"

    def _depict_payload_for_render2d_source(self, row: int, src: str):
        """Molecule or reaction SMARTS to draw for one row from the chosen source column."""
        if row < 0 or row >= self._app._table_model.rowCount():
            return None
        if src == "Structure":
            return self._app._mol_for_structure_row(row)
        if src not in self._app.headers:
            return None
        ci = self._app.headers.index(src)
        if self._app._table_model.is_pixmap_data_column(src):
            raw = (self._app._table_model.backing_value_for_row_header(row, src) or "").strip()
        else:
            raw = (self._app.cell_text(row, ci) or "").strip()
            if not raw:
                raw = (self._app._table_model.backing_value_for_row_header(row, src) or "").strip()
        if not raw:
            return None
        if looks_like_reaction_smarts(raw) and parse_reaction_smarts(raw) is not None:
            return ReactionDrawSpec(raw)
        return self._app._mol_from_structure_text(raw)

    def _mol_for_render2d_source(self, row: int, src: str) -> object | None:
        """Molecule to draw for one row from the chosen source column."""
        payload = self._depict_payload_for_render2d_source(row, src)
        if is_rdkit_mol(payload):
            return payload
        return None

    def run_render_2d_for_table_row(self, row: int, col: int | None = None) -> None:
        """Run Render 2D for one row: read chemistry from ``col`` and write the pixmap into that column."""
        if not self._app.headers or self._app._table_model.rowCount() == 0:
            QMessageBox.information(
                self._app, TOOL_RENDER_2D, "Load a table with at least one row first."
            )
            return
        if self._app._render2d_batch_active:
            QMessageBox.warning(
                self._app,
                TOOL_RENDER_2D,
                "A 2D render is already running. Wait for it to finish or cancel it from Processes.",
            )
            return
        if row < 0 or row >= self._app._table_model.rowCount():
            return
        t0 = self._app._table_model.cell_text(row, 0)
        oid = int(t0) if t0.isdigit() else None
        if oid is None:
            QMessageBox.information(
                self._app, TOOL_RENDER_2D, "Could not resolve this row’s compound id."
            )
            return
        src = self._render2d_source_header_for_column(col if col is not None else -1)
        payload = self._depict_payload_for_render2d_source(row, src)
        if payload is None:
            QMessageBox.information(
                self._app,
                TOOL_RENDER_2D,
                f"No structure could be read from column “{src}” for this row.",
            )
            return
        if src == "Structure" and is_rdkit_mol(payload):
            self._app.mols[oid] = payload
        pixmap_mode = src != "Structure" and self._app._table_model.is_pixmap_data_column(src)
        base_w, base_h = structure_depict_width(), structure_depict_height()
        renders, row_by_oid = self._build_render2d_tasks_in_table_order(src, base_w, base_h, {oid})
        if not renders:
            QMessageBox.information(
                self._app,
                TOOL_RENDER_2D,
                f"No structure could be read from column “{src}” for this row.",
            )
            return
        self._start_render_2d_batch(renders, row_by_oid, src, column_pixmap_mode=pixmap_mode)
