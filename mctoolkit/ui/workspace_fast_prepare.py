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

"""Fast Prepare adapter bound on ``WorkspaceTools.structure_prep`` (not a window base)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox

from ..platform_support.config import load_config
from ..table.structure_depiction_layout import structure_depict_height, structure_depict_width
from ..chem.molecule_conversion import mol_from_binary_blob
from ..workers.load_render import STRUCTURE_PAYLOAD_TAG
from .analysis_job_support import enqueue_process_queue_job


def _unpack_fast_prepare_row(row) -> tuple[int, bytes, str, str, bytes]:
    """Normalize worker rows to ``(oid, blob, fragments, smiles, png)``."""
    oid = int(row[0])
    blob = row[1] or b""
    fragments = str(row[2] or "") if len(row) > 2 else ""
    smiles = str(row[3] or "") if len(row) > 3 else ""
    png = row[4] if len(row) > 4 else b""
    return oid, blob, fragments, smiles, png or b""


class FastPrepareTools:
    def run_fast_prepare(self) -> None:
        if not self._app.headers or not self._app.mols:
            return
        from .dialogs import FastPrepareDialog

        candidates = self._app.chemistry_tool_structure_sources()
        n_sel = len(self._app._selected_logical_rows())
        dlg = FastPrepareDialog(candidates, self._app.headers, n_sel, self._app)
        self._app._prepare_tool_dialog(dlg)
        dlg.setAttribute(Qt.WA_DeleteOnClose, True)
        dlg.accepted.connect(lambda *_, d=dlg: self._on_fast_prepare_dialog_accepted(d))
        dlg.show()

    def _on_fast_prepare_dialog_accepted(self, dlg) -> None:
        cfg = dlg.config()
        allowed = self._app._selected_oids_set() if cfg.only_selected else None
        if self._app._abort_if_only_selected_but_empty(cfg.only_selected, allowed, "Fast Prepare"):
            return
        prepare_col = cfg.source_column if cfg.update_target else cfg.largest_column
        self._app._fast_prepare_source = prepare_col
        self._app._fast_prepare_allowed_oids = allowed
        self._app._fast_prepare_fragments_col = cfg.fragments_column
        self._app._fast_prepare_update_target = cfg.update_target
        self._enqueue_fast_prepare(
            cfg.source_column,
            prepare_col,
            only_selected=cfg.only_selected,
            neutralize=cfg.neutralize,
        )

    def _fast_prepare_target_is_text(self, prepare_col: str) -> bool:
        """True when the Fast Prepare output column holds SMILES text rather than a depiction.

        A column the dialog named but that does not exist yet (New Column mode) counts as text: it
        is created as a plain data column before the results are written.
        """
        if prepare_col == "Structure":
            return False
        return not (
            prepare_col in self._app.headers
            and self._app._table_model.is_pixmap_data_column(prepare_col)
        )

    def _enqueue_fast_prepare(
        self, src: str, prepare_col: str, *, only_selected: bool, neutralize: bool = False
    ) -> None:
        """Queue the fused disconnect (and optional neutralize) pass over the rows in scope."""
        from ..workers.fast_prepare import FastPrepareParams, FastPrepareWorker

        allowed = self._app._selected_oids_set() if only_selected else None
        oids_walk = self._app._all_oids_in_table_order()
        if allowed is not None:
            oids_walk = [o for o in oids_walk if o in allowed]

        # Same source split the disconnect job used: the Structure column reads store blobs, any
        # other column is read as cell text.
        is_smiles = src != "Structure"
        if is_smiles:
            col = self._app.headers.index(src)
            data: list[tuple] = []
            for oid in oids_walk:
                row = self._app.logical_row_for_oid(oid)
                if row == -1:
                    continue
                data.append((oid, self._app._table_cell_text(row, col)))
        else:
            data = self._fast_prepare_structure_items(oids_walk, src)

        if not data:
            QMessageBox.information(
                self._app,
                "Fast Prepare",
                "No rows match the current scope and structure field.",
            )
            self._app.status_label.setText("Ready.")
            return

        # Canonical SMILES is only needed when the output column stores text; computing it in the
        # child processes keeps MolToSmiles off the GUI thread.
        need_smiles = self._fast_prepare_target_is_text(prepare_col)
        need_png = prepare_col == "Structure"
        cfg = load_config()
        params = FastPrepareParams(
            is_smiles=is_smiles,
            need_smiles=need_smiles,
            neutralize=bool(neutralize),
            need_png=need_png,
            png_width=structure_depict_width() if need_png else 0,
            png_height=structure_depict_height() if need_png else 0,
            batch_size=int(cfg.fast_prepare_batch_size),
            process_pool_min_rows=int(cfg.fast_prepare_process_pool_min_rows),
        )
        enqueue_process_queue_job(
            self._app,
            "Fast prepare",
            len(data),
            lambda ev, d=data, p=params, s=self._app.signals, ps=self._app._tool_progress_state: (
                FastPrepareWorker(d, p, s, cancel_event=ev, progress_state=ps)
            ),
            queue_label="Fast prepare: prepare structures",
        )

    def _fast_prepare_structure_items(self, oids_walk: list[int], src: str) -> list[tuple]:
        """Snapshot Structure-column rows as store blobs so the GUI never hydrates RDKit mols.

        ``MolStore.get`` rebuilds a live molecule from SQLite. Doing that for every row on OK
        is what froze the window; the worker already accepts pickles.
        """
        wanted = set(oids_walk)
        store = self._app.mols
        bulk = getattr(store, "iter_structure_payloads", None)
        if callable(bulk):
            by_oid = {
                int(oid): (blob, smiles) for oid, blob, smiles in bulk() if int(oid) in wanted
            }
            items: list[tuple] = []
            for oid in oids_walk:
                rec = by_oid.get(int(oid))
                if rec is None:
                    continue
                blob, smiles = rec
                source_text = self._disconnect_source_text_for_oid(oid, src) or (
                    str(smiles).strip() or None
                )
                if not blob and not source_text:
                    continue
                items.append((int(oid), blob or b"", source_text))
            return items
        items = []
        for oid in oids_walk:
            mol = store.get(oid) if hasattr(store, "get") else None
            if mol is None:
                continue
            items.append((oid, mol, self._disconnect_source_text_for_oid(oid, src)))
        return items

    def on_fast_prepare_finished(self, results) -> None:
        """Apply fused disconnect + neutralize results without stalling the event loop.

        Molecules stay as binary blobs so the GUI thread does not rebuild RDKit objects.
        Large tables are written in ChunkedTableWriter slices so SQLite ingest and
        Structure-cell invalidation cannot freeze the window at job end.
        """
        from .chunked_table_write import ChunkedTableWriter

        self._app.table.setSortingEnabled(False)
        prepare_col = getattr(self._app, "_fast_prepare_source", "Structure")
        fragments_col = getattr(self._app, "_fast_prepare_fragments_col", "Fragments")
        update_target = getattr(self._app, "_fast_prepare_update_target", True)
        allowed_oids = getattr(self._app, "_fast_prepare_allowed_oids", None)
        self._app._fast_prepare_source = "Structure"
        self._app._fast_prepare_allowed_oids = None
        self._app._fast_prepare_fragments_col = "Fragments"
        self._app._fast_prepare_update_target = True

        self._ensure_disconnect_output_column(fragments_col)
        if not update_target:
            self._ensure_disconnect_output_column(prepare_col)

        target_is_text = self._fast_prepare_target_is_text(prepare_col)
        write_fragments = fragments_col in self._app.headers
        smiles_h = self._app._canonical_smiles_header_for_updates()
        sync_smiles_col = smiles_h is not None and smiles_h == prepare_col and target_is_text
        rows = list(results or [])
        state: dict = {"applied_png": False, "pixmap_oids": []}

        def write_chunk(start: int, end: int, _is_last: bool) -> None:
            structure_jobs: list[tuple[int, bytes, str]] = []
            pixmap_oids: list[int] = []
            text_rows: list[tuple[int, dict[str, str]]] = []
            png_items: list[tuple[int, bytes]] = []
            for row in rows[start:end]:
                oid_i, blob, fragments, smiles, png = _unpack_fast_prepare_row(row)
                values: dict[str, str] = {}
                if target_is_text:
                    values[prepare_col] = smiles
                    if sync_smiles_col and smiles_h:
                        values[smiles_h] = smiles
                elif blob:
                    structure_jobs.append((oid_i, blob, smiles or ""))
                    pixmap_oids.append(oid_i)
                    if png:
                        png_items.append((oid_i, png))
                if write_fragments:
                    values[fragments_col] = fragments
                if values:
                    text_rows.append((oid_i, values))
            self._store_fast_prepare_mols(structure_jobs)
            if png_items and self._apply_fast_prepare_pngs(png_items, prepare_col):
                state["applied_png"] = True
            state["pixmap_oids"].extend(pixmap_oids)
            self._write_fast_prepare_text_rows(text_rows)

        def on_done() -> None:
            self._fast_prepare_writer = None
            pixmap_oids = state["pixmap_oids"]
            applied_png = bool(state["applied_png"])
            if pixmap_oids and not applied_png:
                if prepare_col == "Structure":
                    self._app._table_model.drop_structure_pixmap_cache(pixmap_oids)
                    refresh = getattr(self._app, "_refresh_visible_structure_cells", None)
                    if callable(refresh):
                        refresh()
                    else:
                        self._app._table_model.notify_structure_column_changed()
                else:
                    for oid in pixmap_oids:
                        self._app._table_model.set_column_pixmap(oid, prepare_col, None)
            self._app.schedule_calculate_global_bounds()
            self._app._clear_tool_progress()
            if (
                rows
                and not target_is_text
                and not applied_png
                and not getattr(self._app, "_render2d_batch_active", False)
            ):
                renders, row_by_oid = self._fast_prepare_render_tasks(
                    rows, prepare_col, allowed_oids
                )
                if renders:
                    self._app.status_label.setText("Fast prepare: rendering 2D…")
                    self._app._start_render_2d_batch(
                        renders,
                        row_by_oid,
                        prepare_col,
                        column_pixmap_mode=(prepare_col != "Structure"),
                        queue_title_prefix="Fast prepare: ",
                    )
                    return
            self._app.status_label.setText(
                self._app._consume_partial_results_notice() or "Fast prepare done."
            )

        prev = getattr(self, "_fast_prepare_writer", None)
        if prev is not None:
            prev.cancel()
        cfg = load_config()
        chunk = max(64, int(cfg.fast_prepare_batch_size))
        writer = ChunkedTableWriter(
            table=self._app.table,
            total=len(rows),
            chunk=chunk,
            write_chunk=write_chunk,
            on_progress=lambda done, total: self._app.status_label.setText(
                f"Fast prepare: writing results… ({done:,}/{total:,})"
            ),
            on_done=on_done,
        )
        self._fast_prepare_writer = writer
        if len(rows) >= max(2, int(cfg.fast_prepare_process_pool_min_rows)):
            self._app.status_label.setText("Fast prepare: writing results…")
            writer.start()
            return
        writer.run_now()

    def _apply_fast_prepare_pngs(
        self, png_items: list[tuple[int, bytes]], prepare_col: str
    ) -> bool:
        """Upsert worker PNGs into the lazy Structure store. Return True when Render 2D is skipped.

        Reuses an existing store so selected-row jobs do not drop drawings for other rows, and
        never per-oid DELETE+commit the store we are about to replace (that was the end-of-job
        hitch).
        """
        if not png_items or prepare_col != "Structure":
            return False
        from ..storage.structure_render_store import StructureRenderStore

        model = self._app._table_model
        cfg = load_config()
        store = getattr(model, "_structure_png_store", None)
        if store is None:
            cap = int(cfg.structure_render_png_max_entries)
            if cap > 0:
                cap = max(cap, len(png_items))
            store = StructureRenderStore(
                max_decoded_pixmaps=cfg.structure_render_pixmap_lru,
                max_png_entries=cap,
            )
            model.set_structure_png_store(store)
            hook = getattr(self._app, "_ensure_structure_lazy_scroll_hook", None)
            if callable(hook):
                hook()
        store.ingest_batch(png_items)
        model.drop_structure_pixmap_cache([oid for oid, _png in png_items])
        refresh = getattr(self._app, "_refresh_visible_structure_cells", None)
        if callable(refresh):
            refresh()
        else:
            model.notify_structure_column_changed()
        return True

    def _store_fast_prepare_mols(self, jobs: list[tuple[int, bytes, str]]) -> None:
        """Write prepared structures into the mol store without hydrating them."""
        if not jobs:
            return
        store = self._app.mols
        ingest = getattr(store, "ingest_jobs", None)
        if callable(ingest):
            ingest(jobs)
            return
        for oid, blob, _smiles in jobs:
            mol = self._fast_prepare_mol_from_blob(blob)
            if mol is not None:
                store[oid] = mol

    def _write_fast_prepare_text_rows(self, text_rows: list[tuple[int, dict[str, str]]]) -> None:
        """Bulk-write fragment / SMILES cells with one ``dataChanged`` span per column block."""
        if not text_rows:
            return
        cols: list[str] = []
        seen: set[str] = set()
        for _oid, values in text_rows:
            for header_name in values:
                if header_name not in seen:
                    seen.add(header_name)
                    cols.append(header_name)
        model = self._app._table_model
        if len(cols) == 1:
            hdr = cols[0]
            model.set_column_text_by_oids(
                hdr, [(oid, values[hdr]) for oid, values in text_rows if hdr in values]
            )
            return
        model.apply_columns_values_bulk(cols, text_rows)

    def _fast_prepare_render_tasks(
        self,
        results,
        prepare_col: str,
        allowed_oids,
    ) -> tuple[list, dict[int, int]]:
        """Build Render 2D tasks from worker blobs (no GUI-thread ``Chem.Mol``)."""
        renders: list = []
        row_by_oid: dict[int, int] = {}
        base_w, base_h = structure_depict_width(), structure_depict_height()
        zoom_w, zoom_h = base_w * 2, base_h * 2
        zoomed = getattr(self._app, "zoomed_ids", ()) or ()
        row_for_oid = self._app._table_model.logical_row_for_oid
        for row in results:
            oid_i, blob, _fragments, smiles, _png = _unpack_fast_prepare_row(row)
            if allowed_oids is not None and oid_i not in allowed_oids:
                continue
            if not blob:
                continue
            row = row_for_oid(oid_i)
            if row < 0:
                continue
            rw, rh = (zoom_w, zoom_h) if oid_i in zoomed else (base_w, base_h)
            payload = (STRUCTURE_PAYLOAD_TAG, bytes(blob), (smiles or "").encode("utf-8"))
            renders.append((oid_i, payload, rw, rh))
            row_by_oid[oid_i] = row
        if prepare_col != "Structure" and not renders:
            return self._app._build_render2d_tasks_in_table_order(
                prepare_col, base_w, base_h, allowed_oids
            )
        return renders, row_by_oid

    @staticmethod
    def _fast_prepare_mol_from_blob(blob) -> object | None:
        """Rebuild a molecule from the worker's binary payload."""
        return mol_from_binary_blob(blob)  # type: ignore[return-value]
