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

"""Filter panel UI, global numeric bounds sync, and table row visibility filtering."""

from __future__ import annotations

import logging
import time
from contextlib import nullcontext

from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QDialog, QMessageBox

from ...config import MolManagerConfig, load_config
from ...filter_compute import build_sqlite_where, fetch_matching_oids
from ...utils import mol_to_canonical_smiles, safe_float
from ...workers import FilterApplyWorker, SubstructureFilterWorker
from ..background_jobs import register_background_job, unregister_background_job
from .cards import (
    CategoryFilterCard,
    FilterCard,
    SubstructureFilterCard,
    TextFilterCard,
    next_default_filter_title,
)

logger = logging.getLogger(__name__)


class FilterPanelMixin:
    """Expects ``headers``, ``_table_model``, ``table``, ``mols``, ``filters``, ``f_panel``,
    ``f_container``, ``global_bounds``, ``status_label``, ``threadpool``, ``_apply_filters_timer``,
    and optional ``_substructure_filter_signals`` on ``self`` (provided by ``ChemicalTableApp``).
    """

    def _clear_filter_target_smiles_cache(self) -> None:
        """Drop cached MolToSmiles results (e.g. after wholesale ``mols`` replacement)."""
        self._filter_target_smiles_cache = None
        self._substructure_target_mol_cache = {}

    def _smiles_for_substructure_target(self, oid: int, mol) -> str:
        """Stable SMILES string for filter worker targets; cache per (oid, mol object id)."""
        if mol is None:
            return ""
        cache = getattr(self, "_filter_target_smiles_cache", None)
        if cache is None:
            cache = {}
            self._filter_target_smiles_cache = cache
        mid = id(mol)
        t = cache.get(oid)
        if t is not None and t[0] == mid:
            return t[1]
        smi = mol_to_canonical_smiles(mol)
        cache[oid] = (mid, smi)
        return smi

    def _filterable_data_column_names(self) -> list[str]:
        return [h for h in self.headers[2:] if h and not self._table_model.is_pixmap_data_column(h)]

    def _filter_specs_for_sqlite(self) -> list[dict]:
        """Serializable filter specs for SQL pushdown (substructure cards may be present but disabled)."""
        specs: list[dict] = []
        for f in self.filters:
            if isinstance(f, SubstructureFilterCard):
                specs.append({"kind": "substructure", "enabled": f.filter_enabled()})
                continue
            if isinstance(f, CategoryFilterCard):
                specs.append(
                    {
                        "kind": "category",
                        "enabled": f.filter_enabled(),
                        "column": f.column_name(),
                        "values": sorted(f.checked_values()),
                    }
                )
                continue
            if isinstance(f, FilterCard):
                cfg = f.get_cfg()
                specs.append(
                    {
                        "kind": "numeric",
                        "enabled": bool(cfg.get("enabled", True)),
                        "column": cfg.get("p"),
                        "min": float(cfg.get("min", 0.0)),
                        "max": float(cfg.get("max", 0.0)),
                        "inverted": bool(cfg.get("inverted", False)),
                    }
                )
                continue
            if isinstance(f, TextFilterCard):
                cfg = f.get_cfg()
                specs.append(
                    {
                        "kind": "text",
                        "enabled": bool(cfg.get("enabled", True)),
                        "column": cfg.get("p"),
                        "text": str(cfg.get("text", "") or ""),
                        "case_sensitive": bool(cfg.get("case_sensitive", False)),
                        "partial_match": bool(cfg.get("partial_match", True)),
                        "inverted": bool(cfg.get("inverted", False)),
                    }
                )
                continue
            specs.append({"kind": "unknown", "enabled": True})
        return specs

    def _sqlite_filter_where_clause(self) -> tuple[str, tuple] | None:
        """Try SQL pushdown for simple enabled filters; return None when unsupported."""
        ensure_sqlite = getattr(self, "_ensure_sqlite_store_current", None)
        if callable(ensure_sqlite) and not ensure_sqlite():
            return None
        return build_sqlite_where(self._filter_specs_for_sqlite(), headers=self.headers)

    def _sqlite_filter_matched_oids(self) -> frozenset[int] | None:
        """Try SQL pushdown for simple enabled filters; return None when unsupported."""
        where = self._sqlite_filter_where_clause()
        if where is None:
            return None
        store = getattr(self, "_sqlite_store", None)
        if store is None:
            return None
        where_sql, args = where
        cfg = load_config()
        page = max(1000, int(cfg.sqlite_backend_page_size))
        return fetch_matching_oids(
            store.db_path,
            where_sql,
            args,
            page_size=page,
        )

    def calculate_global_bounds(self, *, on_complete=None) -> None:
        """Scan numeric columns and refresh filter/plot axis bounds."""
        self._bounds_on_complete = on_complete
        self._bounds_chunk_gen = int(getattr(self, "_bounds_chunk_gen", 0)) + 1
        self._bounds_chunk_active = False
        n = self._table_model.rowCount()
        cfg = load_config()
        if n >= int(cfg.bounds_async_min_rows):
            self._begin_chunked_global_bounds()
            return
        self._apply_global_bounds_sync()
        self._finish_bounds_calculation()

    def _finish_bounds_calculation(self) -> None:
        """Invoke optional ingest/deferred callback or update status when bounds are ready."""
        cb = getattr(self, "_bounds_on_complete", None)
        self._bounds_on_complete = None
        if cb is not None:
            QTimer.singleShot(0, cb)
            return
        if hasattr(self, "status_label") and not getattr(self, "_render2d_batch_active", False):
            cur = self.status_label.text()
            if cur.startswith("Preparing filters"):
                n = self._table_model.rowCount()
                from ..strings import STATUS_READY_RENDER_2D

                self.status_label.setText(STATUS_READY_RENDER_2D if n else "Ready.")

    def _set_bounds_prep_progress(self, message: str) -> None:
        """Show bounds-prep progress on the loading page during ingest."""
        if getattr(self, "_ingest_prep_before_reveal", False) and hasattr(self, "_loading_detail"):
            self._loading_detail.setText(message)
        if hasattr(self, "status_label") and not getattr(self, "_render2d_batch_active", False):
            self.status_label.setText(message.replace("\n", " — "))

    def _apply_global_bounds_sync(self) -> None:
        self.global_bounds = self._table_model.numeric_bounds_by_column()
        self._refresh_bounds_on_filter_cards()

    def _refresh_bounds_on_filter_cards(self) -> None:
        data_cols = self._filterable_data_column_names()
        struct_srcs = None
        get_srcs = getattr(self, "chemistry_tool_structure_sources", None)
        if callable(get_srcs):
            struct_srcs = get_srcs()
        for f in self.filters:
            if isinstance(f, FilterCard):
                f.update_prop_list(list(self.global_bounds.keys()))
            elif isinstance(f, (TextFilterCard, CategoryFilterCard)):
                f.update_prop_list(data_cols)
            elif isinstance(f, SubstructureFilterCard) and struct_srcs is not None:
                f.set_structure_sources(struct_srcs)
        refresh_plot_axes = getattr(self, "_refresh_active_plot_axis_columns", None)
        if callable(refresh_plot_axes):
            refresh_plot_axes()

    def _begin_chunked_global_bounds(self) -> None:
        headers = self._table_model.list_bounds_data_headers()
        if not headers:
            self._apply_global_bounds_sync()
            self._finish_bounds_calculation()
            return
        self._bounds_chunk_active = True
        self._bounds_chunk_headers = headers
        self._bounds_chunk_col_i = 0
        self._bounds_chunk_row_i = 0
        self._bounds_chunk_acc: dict[str, dict] = {}
        gen = int(self._bounds_chunk_gen)
        self._set_bounds_prep_progress(f"Preparing filters…\n(0/{len(headers)} columns)")
        QTimer.singleShot(0, lambda g=gen: self._bounds_chunk_step(g))

    def _bounds_chunk_step(self, gen: int) -> None:
        if gen != int(getattr(self, "_bounds_chunk_gen", -1)):
            return
        if not getattr(self, "_bounds_chunk_active", False):
            return
        cfg = load_config()
        row_budget = int(cfg.bounds_chunk_rows)
        deadline = time.monotonic() + max(0.005, int(cfg.ingest_gui_time_budget_ms) / 1000.0)
        headers = self._bounds_chunk_headers
        ci = int(self._bounds_chunk_col_i)
        n_rows = self._table_model.rowCount()
        processed = 0
        while ci < len(headers) and processed < row_budget and time.monotonic() < deadline:
            header = headers[ci]
            start = int(self._bounds_chunk_row_i)
            remain = row_budget - processed
            end = min(start + remain, n_rows)
            acc = self._bounds_chunk_acc.get(header)
            self._bounds_chunk_acc[header] = self._table_model.merge_numeric_bounds_chunk(
                header, start, end, acc
            )
            processed += end - start
            if end >= n_rows:
                if header in self._bounds_chunk_acc and self._bounds_chunk_acc[header] is None:
                    self._bounds_chunk_acc.pop(header, None)
                ci += 1
                self._bounds_chunk_row_i = 0
            else:
                self._bounds_chunk_row_i = end
        self._bounds_chunk_col_i = ci
        if ci < len(headers):
            self._set_bounds_prep_progress(f"Preparing filters…\n({ci}/{len(headers)} columns)")
            QTimer.singleShot(0, lambda g=gen: self._bounds_chunk_step(g))
            return
        self._bounds_chunk_active = False
        self._table_model.install_numeric_bounds_cache(self._bounds_chunk_acc)
        self.global_bounds = dict(self._bounds_chunk_acc)
        self._refresh_bounds_on_filter_cards()
        self._finish_bounds_calculation()

    def schedule_calculate_global_bounds(self, *, delay_ms: int | None = None) -> None:
        """Debounce full-table bounds scans after bulk load/ingest (keeps UI responsive)."""
        timer = getattr(self, "_bounds_recalc_timer", None)
        if timer is None:
            return
        cfg = load_config()
        ms = int(delay_ms if delay_ms is not None else cfg.filter_debounce_default_ms)
        timer.stop()
        timer.start(max(0, ms))

    def _filters_include_substructure(self) -> bool:
        return any(
            isinstance(f, SubstructureFilterCard) and f.filter_enabled() for f in self.filters
        )

    def apply_filters(self) -> None:
        """Coalesce expensive filter passes on large tables (slider drags)."""
        mark = getattr(self, "_mark_session_dirty", None)
        if callable(mark):
            mark()
        n = self._table_model.rowCount()
        cfg = load_config()
        # Substructure matching runs RDKit per row — debounce earlier and slightly longer while typing SMARTS.
        if self._filters_include_substructure():
            threshold, delay_ms = (
                cfg.filter_debounce_substructure_rows,
                cfg.filter_debounce_substructure_ms,
            )
        else:
            threshold, delay_ms = cfg.filter_debounce_default_rows, cfg.filter_debounce_default_ms
        if n < threshold:
            self._apply_filters_impl(cfg)
            return
        self._apply_filters_timer.stop()
        self._apply_filters_timer.start(delay_ms)

    def _invalidate_substructure_async_jobs(self) -> None:
        """Drop in-flight substructure jobs (completion handler will no-op)."""
        self._substructure_job_gen = int(getattr(self, "_substructure_job_gen", 0)) + 1
        self._substructure_job_smarts = None
        self._substructure_job_source = None

    def _invalidate_filter_jobs(self) -> None:
        """Drop in-flight SQL/chunked filter jobs (completion handler will no-op)."""
        self._filter_job_gen = int(getattr(self, "_filter_job_gen", 0)) + 1
        self._filter_pending_substructure = None
        timer = getattr(self, "_chunked_filter_timer", None)
        if timer is not None:
            timer.stop()
        self._chunked_filter_state = None
        self._unregister_filter_background_job()

    def _unregister_filter_background_job(self, job_gen: int | None = None) -> None:
        job_id = getattr(self, "_filter_bg_job_id", None)
        if job_id is None:
            return
        if job_gen is not None and job_id != f"filter-{job_gen}":
            return
        unregister_background_job(self, job_id)
        self._filter_bg_job_id = None

    def _on_filter_apply_finished(self, job_gen: int, matched) -> None:
        self._unregister_filter_background_job(job_gen)
        if job_gen != getattr(self, "_filter_job_gen", 0):
            return
        finish = getattr(self, "_finish_tool_progress", None)
        if callable(finish):
            finish("Applying filters", status_message=None)
        sub = getattr(self, "_filter_pending_substructure", None)
        self._filter_pending_substructure = None
        oids = matched if isinstance(matched, frozenset) else frozenset()
        self._apply_filters_impl_sync(sub, sqlite_oids=oids)

    def _on_filter_apply_failed(self, job_gen: int, msg: str) -> None:
        self._unregister_filter_background_job(job_gen)
        if job_gen != getattr(self, "_filter_job_gen", 0):
            return
        finish = getattr(self, "_finish_tool_progress", None)
        if callable(finish):
            finish("Applying filters", status_message=None)
        logger.warning("Filter apply job failed: %s", msg)
        pending = getattr(self, "_filter_pending_substructure", None)
        self._filter_pending_substructure = None
        self._start_chunked_filter_apply(pending)

    def _start_async_sqlite_filter_apply(
        self,
        substructure_matches: tuple[str, frozenset] | None,
    ) -> None:
        where = self._sqlite_filter_where_clause()
        store = getattr(self, "_sqlite_store", None)
        if where is None or store is None:
            self._start_chunked_filter_apply(substructure_matches)
            return
        where_sql, args = where
        self._invalidate_filter_jobs()
        gen = self._filter_job_gen
        self._filter_pending_substructure = substructure_matches
        n_rows = self._table_model.rowCount()
        cfg = load_config()
        sigs = getattr(self, "_filter_apply_signals", None)
        if sigs is None:
            self._apply_filters_impl_sync(substructure_matches)
            return
        job_id = f"filter-{gen}"
        self._filter_bg_job_id = job_id
        register_background_job(self, job_id, f"Applying filters ({n_rows:,} rows)")
        begin = getattr(self, "_begin_tool_progress", None)
        if callable(begin):
            begin("Applying filters", n_rows)
        worker_signals = getattr(self, "signals", None)
        progress_state = getattr(self, "_tool_progress_state", None)
        self.threadpool.start(
            FilterApplyWorker(
                gen,
                str(store.db_path),
                where_sql,
                args,
                max(1000, int(cfg.sqlite_backend_page_size)),
                sigs,
                progress_state=progress_state,
                worker_signals=worker_signals,
            )
        )

    def _start_chunked_filter_apply(
        self,
        substructure_matches: tuple[str, frozenset] | None,
    ) -> None:
        self._invalidate_filter_jobs()
        gen = self._filter_job_gen
        n_rows = self._table_model.rowCount()
        self._chunked_filter_state = {
            "job_gen": gen,
            "row": 0,
            "n_rows": n_rows,
            "visible_oids": set(),
            "substructure_matches": substructure_matches,
            "sqlite_oids": self._sqlite_filter_matched_oids(),
        }
        begin = getattr(self, "_begin_tool_progress", None)
        if callable(begin):
            begin("Applying filters", n_rows)
        timer = getattr(self, "_chunked_filter_timer", None)
        if timer is None:
            self._apply_filters_impl_sync(substructure_matches)
            return
        timer.start(0)

    def _chunked_filter_step(self) -> None:
        state = getattr(self, "_chunked_filter_state", None)
        if not state:
            return
        if state["job_gen"] != getattr(self, "_filter_job_gen", 0):
            state.clear()
            self._chunked_filter_state = None
            return
        cfg = load_config()
        chunk = max(64, int(cfg.filter_chunk_rows))
        n_rows = int(state["n_rows"])
        start = int(state["row"])
        end = min(n_rows, start + chunk)
        override_smarts = None
        override_source = None
        override_oids = None
        sub = state.get("substructure_matches")
        if sub:
            override_smarts, override_source, override_oids = self._unpack_substructure_matches(sub)
        sqlite_oids = state.get("sqlite_oids")
        h_map = {h: i for i, h in enumerate(self.headers)}
        visible_oids: set[int] = state["visible_oids"]
        for r in range(start, end):
            hide = False
            oid = self._table_model.row_oid(r)
            if sqlite_oids is not None:
                hide = oid not in sqlite_oids
            for f in [] if sqlite_oids is not None else self.filters:
                if isinstance(f, SubstructureFilterCard):
                    if not f.filter_enabled():
                        continue
                    inv = f.filter_inverted()
                    if override_oids is not None and self._substructure_override_matches_card(
                        f, override_smarts, override_source
                    ):
                        matched = oid in override_oids
                        if inv:
                            if matched:
                                hide = True
                                break
                        elif not matched:
                            hide = True
                            break
                        continue
                    mol = self._mol_for_substructure_filter_row(r, f.structure_source())
                    matched = f.match_mol(mol)
                    if inv:
                        if matched:
                            hide = True
                            break
                    elif not matched:
                        hide = True
                        break
                    continue
                if isinstance(f, TextFilterCard):
                    if not f.filter_enabled():
                        continue
                    if not f.row_matches(r):
                        hide = True
                        break
                    continue
                if isinstance(f, CategoryFilterCard):
                    if not f.filter_enabled():
                        continue
                    if not f.row_matches(r):
                        hide = True
                        break
                    continue
                if not isinstance(f, FilterCard):
                    continue
                fcfg = f.get_cfg()
                if not fcfg.get("enabled", True):
                    continue
                prop = fcfg.get("p")
                if not prop or prop not in h_map:
                    continue
                v = safe_float(self._table_model.value_for_header(r, prop))
                if v is None:
                    hide = True
                    break
                lo, hi = fcfg["min"], fcfg["max"]
                inside = lo <= v <= hi
                if fcfg.get("inverted", False):
                    if inside:
                        hide = True
                        break
                elif not inside:
                    hide = True
                    break
            if not hide:
                visible_oids.add(oid)
        state["row"] = end
        state["visible_oids"] = visible_oids
        on_progress = getattr(self, "_on_tool_progress", None)
        if callable(on_progress):
            on_progress("Applying filters…", end, n_rows)
        if end >= n_rows:
            self._chunked_filter_state = None
            finish = getattr(self, "_finish_tool_progress", None)
            if callable(finish):
                finish("Applying filters", status_message=None)
            if (
                sqlite_oids is not None
                and override_oids is not None
                and override_smarts is not None
            ):
                visible_oids = self._apply_substructure_override_to_visible(
                    frozenset(sqlite_oids),
                    override_smarts,
                    override_oids,
                    override_source=override_source,
                )
            elif (
                override_oids is not None
                and override_smarts is not None
                and sqlite_oids is None
                and len([f for f in self.filters if f.filter_enabled()]) == 1
            ):
                for f in self.filters:
                    if isinstance(f, SubstructureFilterCard) and f.filter_enabled():
                        if not self._substructure_override_matches_card(
                            f, override_smarts, override_source
                        ):
                            break
                        inv = f.filter_inverted()
                        visible_oids = (
                            {oid for oid in self.mols if oid not in override_oids}
                            if inv
                            else set(override_oids)
                        )
                        break
            self._finalize_filter_apply(set(visible_oids), n_rows)
            return
        timer = getattr(self, "_chunked_filter_timer", None)
        if timer is not None:
            timer.start(0)

    def _finalize_filter_apply(self, visible_oids: set[int], n_rows: int) -> None:
        proxy = self._filter_proxy_model
        table = getattr(self, "table", None)
        if table is not None:
            table.setUpdatesEnabled(False)
        try:
            proxy.set_visible_oids(frozenset(visible_oids))
        finally:
            if table is not None:
                table.setUpdatesEnabled(True)
        invalid_smarts_msg = None
        for f in self.filters:
            if isinstance(f, SubstructureFilterCard):
                sm = (f.smarts_edit.text() or "").strip()
                if sm and f._compiled_query() is None:
                    invalid_smarts_msg = "Substructure filter: invalid SMARTS."
                    break
        vis = len(visible_oids)
        if invalid_smarts_msg:
            self.status_label.setText(invalid_smarts_msg)
        else:
            self.status_label.setText(f"Showing {vis} / {len(self.mols)} molecules")
        schedule_replot = getattr(self, "_schedule_active_plots_replot", None)
        if callable(schedule_replot):
            schedule_replot(force=True)

    def _substructure_filter_targets(
        self, structure_source: str = "Structure"
    ) -> list[tuple[int, object]]:
        """(oid, Mol) per row for ``SubstructureFilterWorker``.

        Prefer in-memory mols for ``Structure``; for other sources resolve via
        ``_mol_for_structure_tool_oid`` (same as chemistry tools) so SMILES/InChI
        columns work without overwriting the Structure cache.
        """
        src = (structure_source or "Structure").strip() or "Structure"
        targets: list[tuple[int, object]] = []
        resolve = getattr(self, "_mol_for_structure_tool_oid", None)
        mols = getattr(self, "mols", None) or {}
        for r in range(self._table_model.rowCount()):
            oid = int(self._table_model.row_oid(r))
            mol = None
            if callable(resolve):
                mol = resolve(oid, src)
            elif src == "Structure":
                mol = mols.get(oid)
            targets.append((oid, mol))
        return targets

    def _mol_for_substructure_filter_row(self, row: int, structure_source: str):
        """Molecule used when evaluating a substructure filter card on *row*."""
        oid = int(self._table_model.row_oid(row))
        src = (structure_source or "Structure").strip() or "Structure"
        resolve = getattr(self, "_mol_for_structure_tool_oid", None)
        if callable(resolve):
            return resolve(oid, src)
        if src == "Structure":
            return (getattr(self, "mols", None) or {}).get(oid)
        return None

    def _substructure_override_matches_card(
        self,
        card: SubstructureFilterCard,
        override_smarts: str | None,
        override_source: str | None,
    ) -> bool:
        if override_smarts is None:
            return False
        if override_smarts != (card.smarts_edit.text() or "").strip():
            return False
        if override_source is not None and override_source != card.structure_source():
            return False
        return True

    def _unregister_substructure_background_job(self, job_gen: int) -> None:
        job_id = getattr(self, "_substructure_bg_job_id", None)
        if job_id == f"substructure-{job_gen}":
            unregister_background_job(self, job_id)
            self._substructure_bg_job_id = None

    def _on_substructure_filter_finished(self, job_gen: int, matched) -> None:
        self._unregister_substructure_background_job(job_gen)
        if job_gen != getattr(self, "_substructure_job_gen", 0):
            return
        dispatched = getattr(self, "_substructure_job_smarts", None) or ""
        dispatched_src = getattr(self, "_substructure_job_source", None) or "Structure"
        ss_cards = [
            f for f in self.filters if isinstance(f, SubstructureFilterCard) and f.filter_enabled()
        ]
        if len(ss_cards) != 1:
            self._route_filter_apply(None)
            return
        card = ss_cards[0]
        current = (card.smarts_edit.text() or "").strip()
        if current != dispatched or card.structure_source() != dispatched_src:
            self.apply_filters()
            return
        oids = matched if isinstance(matched, frozenset) else frozenset()
        finish = getattr(self, "_finish_tool_progress", None)
        if callable(finish):
            finish("Filtering substructure", status_message=None)
        self._route_filter_apply((dispatched, dispatched_src, oids))

    def _on_substructure_filter_failed(self, job_gen: int, msg: str) -> None:
        self._unregister_substructure_background_job(job_gen)
        if job_gen != getattr(self, "_substructure_job_gen", 0):
            return
        logger.warning("Substructure filter job failed: %s", msg)
        self._invalidate_substructure_async_jobs()
        self._route_filter_apply(None)

    def _apply_substructure_override_to_visible(
        self,
        base: frozenset[int],
        override_smarts: str,
        override_oids: frozenset[int],
        *,
        override_source: str | None = None,
    ) -> set[int]:
        for f in self.filters:
            if not isinstance(f, SubstructureFilterCard) or not f.filter_enabled():
                continue
            if not self._substructure_override_matches_card(f, override_smarts, override_source):
                continue
            inv = f.filter_inverted()
            if inv:
                return {oid for oid in base if oid not in override_oids}
            return {oid for oid in base if oid in override_oids}
        return set(base)

    def _unpack_substructure_matches(
        self, substructure_matches: tuple | None
    ) -> tuple[str | None, str | None, frozenset | None]:
        """Return ``(smarts, structure_source, matched_oids)`` from a job result tuple."""
        if not substructure_matches:
            return None, None, None
        if len(substructure_matches) >= 3:
            return substructure_matches[0], substructure_matches[1], substructure_matches[2]
        return substructure_matches[0], "Structure", substructure_matches[1]

    def _route_filter_apply(self, substructure_matches: tuple | None) -> None:
        """Pick sync, async SQLite, or chunked apply based on table size and filter mix."""
        cfg = load_config()
        n_rows = self._table_model.rowCount()
        if n_rows >= cfg.filter_async_min_rows:
            where = self._sqlite_filter_where_clause()
            if where is not None:
                self._start_async_sqlite_filter_apply(substructure_matches)
                return
            self._start_chunked_filter_apply(substructure_matches)
            return
        self._apply_filters_impl_sync(substructure_matches)

    def _apply_filters_impl_sync(
        self,
        substructure_matches: tuple | None,
        *,
        sqlite_oids: frozenset[int] | None = None,
    ) -> None:
        """Apply all filters on the UI thread.

        If ``substructure_matches`` is ``(smarts, structure_source, oids)``, use that
        for the matching SMARTS card instead of re-matching on the UI thread.
        """
        n_rows = self._table_model.rowCount()
        proxy = self._filter_proxy_model
        perf = getattr(self, "_perf", None)
        scope = perf.track if perf is not None else (lambda *_args, **_kwargs: nullcontext())
        if not self.filters:
            with scope("filters.apply_sync"):
                proxy.set_visible_oids(None)
            self.status_label.setText(f"Showing {n_rows} / {len(self.mols)} molecules")
            schedule_replot = getattr(self, "_schedule_active_plots_replot", None)
            if callable(schedule_replot):
                schedule_replot(force=True)
            return

        override_smarts, override_source, override_oids = self._unpack_substructure_matches(
            substructure_matches
        )
        if sqlite_oids is None:
            sqlite_oids = self._sqlite_filter_matched_oids()

        h_map = {h: i for i, h in enumerate(self.headers)}
        vis = 0
        visible_oids: set[int] = set()
        table = getattr(self, "table", None)
        if table is not None:
            table.setUpdatesEnabled(False)
        try:
            with scope("filters.apply_sync"):
                if sqlite_oids is not None and override_oids is None:
                    visible_oids = set(sqlite_oids)
                    vis = len(visible_oids)
                elif (
                    sqlite_oids is not None
                    and override_oids is not None
                    and override_smarts is not None
                ):
                    visible_oids = self._apply_substructure_override_to_visible(
                        sqlite_oids,
                        override_smarts,
                        override_oids,
                        override_source=override_source,
                    )
                    vis = len(visible_oids)
                elif (
                    override_oids is not None
                    and override_smarts is not None
                    and sqlite_oids is None
                    and len([f for f in self.filters if f.filter_enabled()]) == 1
                ):
                    for f in self.filters:
                        if isinstance(f, SubstructureFilterCard) and f.filter_enabled():
                            if not self._substructure_override_matches_card(
                                f, override_smarts, override_source
                            ):
                                break
                            inv = f.filter_inverted()
                            visible_oids = (
                                {oid for oid in self.mols if oid not in override_oids}
                                if inv
                                else set(override_oids)
                            )
                            vis = len(visible_oids)
                            break
                else:
                    for r in range(n_rows):
                        hide = False
                        oid = self._table_model.row_oid(r)
                        if sqlite_oids is not None:
                            hide = oid not in sqlite_oids
                        for f in [] if sqlite_oids is not None else self.filters:
                            if isinstance(f, SubstructureFilterCard):
                                if not f.filter_enabled():
                                    continue
                                inv = f.filter_inverted()
                                if (
                                    override_oids is not None
                                    and self._substructure_override_matches_card(
                                        f, override_smarts, override_source
                                    )
                                ):
                                    matched = oid in override_oids
                                    if inv:
                                        if matched:
                                            hide = True
                                            break
                                    elif not matched:
                                        hide = True
                                        break
                                    continue
                                mol = self._mol_for_substructure_filter_row(r, f.structure_source())
                                matched = f.match_mol(mol)
                                if inv:
                                    if matched:
                                        hide = True
                                        break
                                elif not matched:
                                    hide = True
                                    break
                                continue
                            if isinstance(f, TextFilterCard):
                                if not f.filter_enabled():
                                    continue
                                if not f.row_matches(r):
                                    hide = True
                                    break
                                continue
                            if isinstance(f, CategoryFilterCard):
                                if not f.filter_enabled():
                                    continue
                                if not f.row_matches(r):
                                    hide = True
                                    break
                                continue
                            if not isinstance(f, FilterCard):
                                continue
                            cfg = f.get_cfg()
                            if not cfg.get("enabled", True):
                                continue
                            prop = cfg.get("p")
                            if not prop or prop not in h_map:
                                continue
                            v = safe_float(self._table_model.value_for_header(r, prop))
                            if v is None:
                                hide = True
                                break
                            lo, hi = cfg["min"], cfg["max"]
                            inside = lo <= v <= hi
                            if cfg.get("inverted", False):
                                if inside:
                                    hide = True
                                    break
                            elif not inside:
                                hide = True
                                break
                        if not hide:
                            visible_oids.add(oid)
                            vis += 1
        finally:
            if table is not None:
                table.setUpdatesEnabled(True)
        self._finalize_filter_apply(visible_oids, n_rows)

    def _apply_filters_impl(self, cfg: MolManagerConfig | None = None) -> None:
        if cfg is None:
            cfg = load_config()
        n_rows = self._table_model.rowCount()
        if self.filters and not self._filters_include_substructure():
            ensure_sqlite = getattr(self, "_ensure_sqlite_store_current", None)
            if callable(ensure_sqlite) and not ensure_sqlite():
                self._sqlite_rebuild_pending_filters = True
                if n_rows >= cfg.filter_async_min_rows:
                    self._invalidate_substructure_async_jobs()
                    self._start_chunked_filter_apply(None)
                    return
                return
        if not self.filters:
            self._invalidate_substructure_async_jobs()
            self._invalidate_filter_jobs()
            self._apply_filters_impl_sync(None)
            return

        ss_cards = [
            f for f in self.filters if isinstance(f, SubstructureFilterCard) and f.filter_enabled()
        ]
        thresh = cfg.substructure_async_rows

        if len(ss_cards) == 1:
            card = ss_cards[0]
            smarts = (card.smarts_edit.text() or "").strip()
            src = card.structure_source()
            if smarts and n_rows >= thresh and card._compiled_query() is not None:
                self._invalidate_filter_jobs()
                self._substructure_job_gen = int(getattr(self, "_substructure_job_gen", 0)) + 1
                gen = self._substructure_job_gen
                self._substructure_job_smarts = smarts
                self._substructure_job_source = src
                perf = getattr(self, "_perf", None)
                scope = (
                    perf.track if perf is not None else (lambda *_args, **_kwargs: nullcontext())
                )
                with scope("filters.substructure_targets"):
                    targets = self._substructure_filter_targets(src)
                sigs = getattr(self, "_substructure_filter_signals", None)
                if sigs is None:
                    self._route_filter_apply(None)
                    return
                job_id = f"substructure-{gen}"
                self._substructure_bg_job_id = job_id
                register_background_job(self, job_id, f"Substructure filter ({n_rows:,} rows)")
                begin = getattr(self, "_begin_tool_progress", None)
                if callable(begin):
                    begin("Filtering substructure", n_rows)
                worker_signals = getattr(self, "signals", None)
                progress_state = getattr(self, "_tool_progress_state", None)
                self.threadpool.start(
                    SubstructureFilterWorker(
                        gen,
                        smarts,
                        targets,
                        sigs,
                        progress_state=progress_state,
                        worker_signals=worker_signals,
                    )
                )
                return

        self._invalidate_substructure_async_jobs()
        self._route_filter_apply(None)

    def add_filter_card(self, initial_property: str | None = None):
        if isinstance(initial_property, bool):
            initial_property = None
        if not self.headers:
            return
        props = list(self.global_bounds.keys())
        if not props:
            props = ["SMILES"]
        init = initial_property if initial_property and initial_property in props else None
        self.f_panel.setVisible(True)
        card = FilterCard(props, self, initial_property=init)
        card.set_filter_title(next_default_filter_title(self.filters, FilterCard))
        card.changed.connect(self.apply_filters)
        card.removed.connect(lambda c: self.remove_filter(c))
        self.f_container.addWidget(card)
        self.filters.append(card)
        self.apply_filters()
        self._sync_filter_panel_scroll_content()

    def add_text_filter_card(self, initial_column: str | None = None):
        if isinstance(initial_column, bool):
            initial_column = None
        if not self.headers:
            return
        cols = self._filterable_data_column_names()
        if not cols:
            QMessageBox.warning(self, "Add Filter", "No text columns are available.")
            return
        self.f_panel.setVisible(True)
        card = TextFilterCard(cols, self)
        card.set_filter_title(next_default_filter_title(self.filters, TextFilterCard))
        card.changed.connect(self.apply_filters)
        card.removed.connect(lambda c: self.remove_filter(c))
        self.f_container.addWidget(card)
        self.filters.append(card)
        if initial_column and card.cb.findText(initial_column) >= 0:
            card.set_column(initial_column)
        self.apply_filters()
        self._sync_filter_panel_scroll_content()

    def add_category_filter_card(self, initial_column: str | None = None):
        if isinstance(initial_column, bool):
            initial_column = None
        if not self.headers:
            return
        cols = self._filterable_data_column_names()
        if not cols:
            QMessageBox.warning(self, "Add Filter", "No text columns are available.")
            return
        self.f_panel.setVisible(True)
        card = CategoryFilterCard(cols, self)
        card.set_filter_title(next_default_filter_title(self.filters, CategoryFilterCard))
        card.changed.connect(self.apply_filters)
        card.removed.connect(lambda c: self.remove_filter(c))
        self.f_container.addWidget(card)
        self.filters.append(card)
        if initial_column and card.cb.findText(initial_column) >= 0:
            card.set_column(initial_column)
        self.apply_filters()
        self._sync_filter_panel_scroll_content()

    def open_add_filter_dialog(self) -> None:
        """Show a dialog to choose which filter type to add."""
        from ..dialogs.add_filter import AddFilterDialog

        if not self.headers:
            return
        dlg = AddFilterDialog(self)
        if dlg.exec_() != QDialog.Accepted:
            return
        kind = dlg.selected_kind()
        if kind == "substructure":
            self.add_substructure_filter_card()
        elif kind == "slider":
            self.add_filter_card()
        elif kind == "text":
            self.add_text_filter_card()
        elif kind == "category":
            self.add_category_filter_card()

    def add_substructure_filter_card(self, *_args, **_kwargs):
        if not self.headers:
            return
        self.f_panel.setVisible(True)
        sources = ["Structure"]
        get_srcs = getattr(self, "chemistry_tool_structure_sources", None)
        if callable(get_srcs):
            sources = get_srcs() or sources
        card = SubstructureFilterCard(structure_sources=sources)
        card.set_filter_title(next_default_filter_title(self.filters, SubstructureFilterCard))
        card.changed.connect(self.apply_filters)
        card.removed.connect(lambda c: self.remove_filter(c))
        self.f_container.addWidget(card)
        self.filters.append(card)
        self.apply_filters()
        self._sync_filter_panel_scroll_content()

    def remove_filter(self, card):
        if card in self.filters:
            self.filters.remove(card)
            card.deleteLater()
            self.apply_filters()
            self._sync_filter_panel_scroll_content()

    def reorder_filter_card(self, card, target_index: int) -> None:
        """Move ``card`` so it sits at ``target_index`` among the other filter cards."""
        if card not in self.filters:
            return
        others = [f for f in self.filters if f is not card]
        n = len(others)
        target_index = max(0, min(int(target_index), n))
        new_order = list(others)
        new_order.insert(target_index, card)
        if new_order == self.filters:
            return
        self.filters = new_order
        self.f_container.removeWidget(card)
        self.f_container.insertWidget(target_index, card)
        self._sync_filter_panel_scroll_content()

    def delete_all_filters_from_panel(self) -> None:
        """Remove every filter card from the panel (same as deleting each card)."""
        for card in list(self.filters):
            self.remove_filter(card)

    def _sync_filter_panel_scroll_content(self) -> None:
        """Refresh scroll-area geometry after cards are added or the panel is shown."""
        scroll = getattr(self, "_filter_scroll", None)
        if scroll is None:
            return
        clamp = getattr(scroll, "_clamp_host_width", None)
        if callable(clamp):
            clamp()
        host = getattr(self, "_filter_cards_host", None)
        if host is not None:
            host.updateGeometry()
        scroll.updateGeometry()

    def toggle_filter_panel(self) -> None:
        """Show or hide the filter panel and resync card width when opening."""
        self.f_panel.setVisible(not self.f_panel.isVisible())
        if self.f_panel.isVisible():
            QTimer.singleShot(0, self._sync_filter_panel_scroll_content)

    def enable_all_filters_keep_panel(self) -> None:
        """Turn on every filter card but leave the filter panel open."""
        for f in self.filters:
            f.restore_filter_flags(enabled=True, inverted=f.filter_inverted())
        self.apply_filters()

    def disable_all_filters_keep_panel(self) -> None:
        """Turn off every filter card but leave the filter panel open."""
        for f in self.filters:
            f.restore_filter_flags(enabled=False, inverted=f.filter_inverted())
        self.apply_filters()

    def close_filter_panel_and_disable_filters(self) -> None:
        """Hide the filter panel and turn off every filter card (cards remain; re-enable with On)."""
        self.disable_all_filters_keep_panel()
        self.f_panel.setVisible(False)

    def close_filter_panel_keep_filters(self) -> None:
        """Hide the filter panel only; active filters keep affecting the table."""
        self.f_panel.setVisible(False)
