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

import json
import logging
import os
import subprocess
import sys
import tempfile
import time

from PyQt5.QtCore import QTimer, Qt
from PyQt5.QtWidgets import QFileDialog, QMessageBox

from rdkit import Chem

from ...config import load_config
from ...confs_codec import deserialize_confs_sidecar, serialize_confs_sidecar
from ...microstate_cache import restore_ionization_sidecar, serialize_ionization_sidecar
from ...utils import mol_to_canonical_smiles
from ..strings import loaded_session_status
from ..widgets import CategoryFilterCard, FilterCard, SubstructureFilterCard, TextFilterCard

logger = logging.getLogger(__name__)


class SessionMixin:
    _SESSION_FORMAT = "molmanager_session"
    _SESSION_FORMAT_ALIASES = frozenset(
        {"molmanager_session", "MOLMANAGER_session", "chemmanager_session"}
    )
    _SESSION_VERSION = 1

    def _session_format_ok(self, fmt: object) -> bool:
        return isinstance(fmt, str) and fmt in self._SESSION_FORMAT_ALIASES

    def new_session(self) -> None:
        """Launch a new MolManager instance with nothing loaded."""
        try:
            subprocess.Popen([sys.executable, "-m", "molmanager"], close_fds=True)
        except Exception as e:
            QMessageBox.warning(self, "New Session", str(e))

    def duplicate_session(self) -> None:
        """Launch a new MolManager instance with the current table state."""
        try:
            path = self._write_session_bundle_file()
            subprocess.Popen(
                [sys.executable, "-m", "molmanager", "--load-session", path], close_fds=True
            )
        except Exception as e:
            QMessageBox.warning(self, "Duplicate Session", str(e))

    def _write_session_csv(self) -> str:
        """Serialize current table to a session CSV (includes all columns except Structure image)."""
        if not self.headers or self._table_model.rowCount() == 0:
            # Still create an empty session file.
            heads = ["SMILES"]
        else:
            # Ensure SMILES is first for readability.
            heads = [h for h in self.headers if h not in ("ID_HIDDEN", "Structure")]
            if "SMILES" in heads:
                heads.remove("SMILES")
                heads.insert(0, "SMILES")
            else:
                heads.insert(0, "SMILES")

        session_dir = os.path.join(tempfile.gettempdir(), "MolManagerSessions")
        os.makedirs(session_dir, exist_ok=True)
        fname = f"session_{time.strftime('%Y%m%d_%H%M%S')}_{os.getpid()}.csv"
        out_path = os.path.join(session_dir, fname)

        import csv

        with open(out_path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=heads)
            w.writeheader()
            for r in range(self._table_model.rowCount()):
                row: dict[str, str] = {}
                # Prefer existing SMILES cell; fall back to RDKit mol if present.
                smi = ""
                if "SMILES" in self.headers:
                    smi = self._table_cell_text(r, self.headers.index("SMILES"))
                if not smi:
                    idr = self._table_model.cell_text(r, 0)
                    if idr.isdigit():
                        mol = self._mol_for_structure_row(r)
                        if mol is not None:
                            smi = mol_to_canonical_smiles(mol)
                row["SMILES"] = smi

                for h in heads:
                    if h == "SMILES":
                        continue
                    if h in self.headers:
                        row[h] = self._export_cell_text(r, self.headers.index(h))
                    else:
                        row[h] = ""
                w.writerow(row)

        return out_path

    def _write_session_bundle_file(self) -> str:
        """Write a full session bundle (.cms JSON) under the temp session directory."""
        session_dir = os.path.join(tempfile.gettempdir(), "MolManagerSessions")
        os.makedirs(session_dir, exist_ok=True)
        fname = f"session_{time.strftime('%Y%m%d_%H%M%S')}_{os.getpid()}.cms"
        out_path = os.path.join(session_dir, fname)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(self._build_session_document(), f, separators=(",", ":"))
        return out_path

    def _build_session_document(self) -> dict:
        hh = self.table.horizontalHeader()
        n = self._table_model.columnCount()
        logical_order = sorted(range(n), key=lambda lg: hh.visualIndex(lg)) if n else []
        sort_col = None
        sort_asc = True
        sort_mode = None
        ss = getattr(self, "_session_sort", None)
        if isinstance(ss, dict) and ss.get("column") is not None:
            sc = ss["column"]
            if isinstance(sc, int) and 0 <= sc < n:
                sort_col = sc
                sort_asc = bool(ss.get("ascending", True))
                sort_mode = str(ss.get("mode") or "auto")
        rows_out: list[dict] = []
        for r in range(self._table_model.rowCount()):
            t0 = self._table_model.cell_text(r, 0)
            oid = int(t0) if t0.isdigit() else r
            cells: dict[str, str] = {}
            for ci, h in enumerate(self.headers):
                if h in ("ID_HIDDEN", "Structure"):
                    continue
                if self._table_model.is_pixmap_data_column(h):
                    cells[h] = self._table_model.backing_value_for_row_header(r, h)
                else:
                    cells[h] = self._table_cell_text(r, ci)
            if "SMILES" not in cells or not (cells.get("SMILES") or "").strip():
                mol = self._mol_for_structure_row(r)
                if mol is not None:
                    cells["SMILES"] = mol_to_canonical_smiles(mol)
            rows_out.append({"id": oid, "cells": cells})
        filters_out: list[dict] = []
        for f in self.filters:
            if isinstance(f, SubstructureFilterCard):
                cfg = f.get_cfg()
                filters_out.append(
                    {
                        "kind": "substructure",
                        "title": f.filter_title(),
                        "smarts": cfg.get("smarts", "") or "",
                        "structure_source": cfg.get("structure_source", "Structure") or "Structure",
                        "enabled": cfg.get("enabled", True),
                        "inverted": cfg.get("inverted", False),
                    }
                )
            elif isinstance(f, TextFilterCard):
                cfg = f.get_cfg()
                filters_out.append(
                    {
                        "kind": "text",
                        "title": f.filter_title(),
                        "property": cfg.get("p", "") or "",
                        "text": cfg.get("text", "") or "",
                        "enabled": cfg.get("enabled", True),
                        "inverted": cfg.get("inverted", False),
                        "case_sensitive": bool(cfg.get("case_sensitive", False)),
                        "partial_match": bool(cfg.get("partial_match", True)),
                    }
                )
            elif isinstance(f, CategoryFilterCard):
                cfg = f.get_cfg()
                filters_out.append(
                    {
                        "kind": "category",
                        "title": f.filter_title(),
                        "property": cfg.get("p", "") or "",
                        "values": list(cfg.get("values") or []),
                        "enabled": cfg.get("enabled", True),
                        "inverted": cfg.get("inverted", False),
                    }
                )
            elif isinstance(f, FilterCard):
                cfg = f.get_cfg()
                filters_out.append(
                    {
                        "kind": "range",
                        "title": f.filter_title(),
                        "property": cfg.get("p", ""),
                        "min": cfg.get("min"),
                        "max": cfg.get("max"),
                        "enabled": cfg.get("enabled", True),
                        "inverted": cfg.get("inverted", False),
                    }
                )
        return {
            "format": self._SESSION_FORMAT,
            "version": self._SESSION_VERSION,
            "headers": list(self.headers),
            "rows": rows_out,
            "next_oid": int(self.next_oid),
            "zoomed_ids": sorted(int(x) for x in self.zoomed_ids),
            "structure_field_override": getattr(self, "_structure_field_override", None),
            "filter_panel_visible": bool(self.f_panel.isVisible()),
            "workspace_layout": (
                self._workspace_layout.collect_splitter_sizes()
                if getattr(self, "_workspace_layout", None) is not None
                else None
            ),
            "plot_panel_visible": True,
            "plot_panel_width": (self._plot_panel_splitter_sizes() or [0, 0])[1],
            "filters": filters_out,
            "column_logical_order": logical_order,
            "sort_column": sort_col,
            "sort_ascending": sort_asc,
            "sort_mode": sort_mode,
            "column_colors": self._table_model.export_column_color_rules(),
            "logarithmic_columns": sorted(
                h for h in getattr(self, "_logarithmic_columns", set()) if h in self.headers
            ),
            "confs_sidecar": serialize_confs_sidecar(
                getattr(self, "_confs_blocks_sidecar", {}) or {}
            ),
            "som_browse": self._session_som_browse_payload(),
            "ionization_sidecar": serialize_ionization_sidecar(),
        }

    def _session_som_browse_payload(self) -> list[dict]:
        """Atom-level SOM maps for session restore (redraws table images on open)."""
        from ..som_browser import records_from_table, serialize_som_browse_records

        records = list(getattr(self, "_som_browse_records", None) or ())
        if not records:
            records = records_from_table(self)
        return serialize_som_browse_records(records)

    def _restore_column_visual_order(self, logical_order: list[int]) -> None:
        h = self.table.horizontalHeader()
        n = self._table_model.columnCount()
        if not logical_order or len(logical_order) != n:
            return
        if any(not isinstance(x, int) or x < 0 or x >= n for x in logical_order):
            return
        for target_visual, want_logical in enumerate(logical_order):
            cur_v = h.visualIndex(want_logical)
            if cur_v != target_visual:
                h.moveSection(cur_v, target_visual)

    def _append_filter_widget(self, card, *, title: str | None = None) -> None:
        if title:
            card.set_filter_title(str(title))
        else:
            from ..filters.cards import next_default_filter_title

            card.set_filter_title(next_default_filter_title(self.filters, type(card)))
        card.changed.connect(self.apply_filters)
        card.removed.connect(lambda c=card: self.remove_filter(c))
        self.f_container.addWidget(card)
        self.filters.append(card)
        self._sync_filter_panel_scroll_content()

    def _apply_session_document(self, doc: dict) -> None:
        if (
            not self._session_format_ok(doc.get("format"))
            or int(doc.get("version", 0)) != self._SESSION_VERSION
        ):
            raise ValueError("Unsupported session format.")
        self.clear_all()
        self._table_stack.setCurrentIndex(1)
        self.status_label.setText("Loading session…")
        headers = doc.get("headers") or ["ID_HIDDEN", "Structure", "SMILES"]
        if len(headers) < 2 or headers[0] != "ID_HIDDEN" or headers[1] != "Structure":
            raise ValueError("Invalid session headers.")
        self.headers = list(headers)
        self._structure_field_override = doc.get("structure_field_override")
        self.zoomed_ids = set(int(x) for x in (doc.get("zoomed_ids") or []) if x is not None)
        self.table.setSortingEnabled(False)
        self._table_model.clear_rows()
        self._table_model.set_headers(list(self.headers))
        self.table.setColumnHidden(0, True)
        self.mols = {}
        self._clear_filter_target_smiles_cache()
        self.global_bounds = {}
        rows = doc.get("rows") or []
        max_id = -1
        chunk = 128
        if len(rows) <= chunk:
            batch_rows: list[tuple[int, dict[str, str]]] = []
            try:
                self.table.setUpdatesEnabled(False)
            except Exception:
                pass
            try:
                for entry in rows:
                    oid = int(entry["id"])
                    max_id = max(max_id, oid)
                    cells = entry.get("cells") or {}
                    smi = (cells.get("SMILES", "") or "").strip()
                    row_cells = {
                        cname: str(cells.get(cname, "") or "") for cname in self.headers[2:]
                    }
                    batch_rows.append((oid, row_cells))
                    mol = Chem.MolFromSmiles(smi) if smi else None
                    if mol is not None:
                        self.mols[oid] = mol
                self._table_model.append_rows_batch(batch_rows)
            finally:
                try:
                    self.table.setUpdatesEnabled(True)
                except Exception:
                    pass
            self._finalize_session_restore(doc, max_id)
        else:
            try:
                self.table.setUpdatesEnabled(False)
            except Exception:
                pass
            self._session_restore_ctx = {
                "gen": int(getattr(self, "_session_load_generation", 0)),
                "doc": doc,
                "rows": rows,
                "idx": 0,
                "chunk": chunk,
                "max_id": -1,
            }
            self.status_label.setText(f"Loading session… (0/{len(rows)} rows)")
            QTimer.singleShot(0, self._session_restore_step)

    def _session_restore_step(self) -> None:
        ctx = getattr(self, "_session_restore_ctx", None)
        if not ctx or ctx.get("gen") != getattr(self, "_session_load_generation", 0):
            try:
                self.table.setUpdatesEnabled(True)
            except Exception:
                pass
            return
        rows = ctx["rows"]
        doc = ctx["doc"]
        i = int(ctx["idx"])
        chunk = int(ctx["chunk"])
        max_id = int(ctx["max_id"])
        n = len(rows)
        end = min(i + chunk, n)
        batch_rows: list[tuple[int, dict[str, str]]] = []
        for j in range(i, end):
            entry = rows[j]
            oid = int(entry["id"])
            max_id = max(max_id, oid)
            cells = entry.get("cells") or {}
            smi = (cells.get("SMILES", "") or "").strip()
            row_cells = {cname: str(cells.get(cname, "") or "") for cname in self.headers[2:]}
            batch_rows.append((oid, row_cells))
            mol = Chem.MolFromSmiles(smi) if smi else None
            if mol is not None:
                self.mols[oid] = mol
        self._table_model.append_rows_batch(batch_rows)
        ctx["idx"] = end
        ctx["max_id"] = max_id
        self.status_label.setText(f"Loading session… ({end}/{n} rows)")
        if end < n:
            QTimer.singleShot(0, self._session_restore_step)
        else:
            self._session_restore_ctx = None
            self._finalize_session_restore(doc, max_id)

    def _finalize_session_restore(self, doc: dict, max_id: int) -> None:
        try:
            self.table.setUpdatesEnabled(True)
        except Exception:
            pass
        want_next = int(doc.get("next_oid", max_id + 1))
        self.next_oid = want_next if want_next > max_id else max_id + 1
        self.calculate_global_bounds()
        for spec in doc.get("filters") or []:
            kind = spec.get("kind")
            if kind == "substructure":
                sources = ["Structure"]
                get_srcs = getattr(self, "chemistry_tool_structure_sources", None)
                if callable(get_srcs):
                    sources = get_srcs() or sources
                c = SubstructureFilterCard(structure_sources=sources)
                self._append_filter_widget(c, title=str(spec.get("title") or "") or None)
                c.set_smarts(str(spec.get("smarts", "") or ""))
                c.set_structure_source(
                    str(spec.get("structure_source", "Structure") or "Structure")
                )
                c.restore_filter_flags(
                    bool(spec.get("enabled", True)), bool(spec.get("inverted", False))
                )
            elif kind == "range":
                props = list(self.global_bounds.keys()) or ["SMILES"]
                c = FilterCard(props, self)
                self._append_filter_widget(c, title=str(spec.get("title") or "") or None)
                p = str(spec.get("property", "") or "")
                if p:
                    try:
                        c.restore_state(p, float(spec.get("min", 0)), float(spec.get("max", 0)))
                    except Exception:
                        pass
                c.restore_filter_flags(
                    bool(spec.get("enabled", True)), bool(spec.get("inverted", False))
                )
            elif kind == "text":
                cols = self._filterable_data_column_names()
                if not cols:
                    cols = list(self.global_bounds.keys()) or ["SMILES"]
                c = TextFilterCard(cols, self)
                self._append_filter_widget(c, title=str(spec.get("title") or "") or None)
                c.restore_from_session(
                    str(spec.get("property", "") or ""),
                    str(spec.get("text", "") or ""),
                    case_sensitive=bool(spec.get("case_sensitive", False)),
                    partial_match=bool(spec.get("partial_match", True)),
                )
                c.restore_filter_flags(
                    bool(spec.get("enabled", True)), bool(spec.get("inverted", False))
                )
            elif kind == "category":
                cols = self._filterable_data_column_names()
                if not cols:
                    cols = list(self.global_bounds.keys()) or ["SMILES"]
                c = CategoryFilterCard(cols, self)
                self._append_filter_widget(c, title=str(spec.get("title") or "") or None)
                vals = spec.get("values")
                if not isinstance(vals, list):
                    vals = []
                c.restore_from_session(str(spec.get("property", "") or ""), vals)
                c.restore_filter_flags(
                    bool(spec.get("enabled", True)), bool(spec.get("inverted", False))
                )
        self.f_panel.setVisible(bool(doc.get("filter_panel_visible", False)))
        ws = doc.get("workspace_layout")
        mgr = getattr(self, "_workspace_layout", None)
        if mgr is not None and isinstance(ws, dict):
            layout_id = ws.get("layout_id")
            if isinstance(layout_id, str) and layout_id:
                apply = getattr(self, "apply_workspace_layout", None)
                if callable(apply):
                    apply(layout_id)
                else:
                    mgr.apply_layout(layout_id, preserve_plots=False)
            mgr.restore_splitter_sizes(ws)
        elif getattr(self, "_workspace_layout", None) is not None:
            saved_w = doc.get("plot_panel_width")
            if isinstance(saved_w, (int, float)) and saved_w > 0:
                ensure = getattr(self, "_ensure_plot_panel_width", None)
                if callable(ensure):
                    QTimer.singleShot(0, lambda: ensure(int(saved_w)))
        co = doc.get("column_logical_order")
        if isinstance(co, list):
            self._restore_column_visual_order([int(x) for x in co])
        sc = doc.get("sort_column")
        self.table.setSortingEnabled(False)
        if sc is not None and isinstance(sc, int) and 0 <= sc < self._table_model.columnCount():
            asc = bool(doc.get("sort_ascending", True))
            mode = doc.get("sort_mode") or "auto"
            if mode not in ("auto", "numeric", "alphabetic"):
                mode = "auto"
            self._table_model.sort(
                sc, Qt.AscendingOrder if asc else Qt.DescendingOrder, sort_kind=mode
            )
            self._session_sort = {"column": sc, "ascending": asc, "mode": mode}
        else:
            self._session_sort = None
        col_colors = doc.get("column_colors")
        if isinstance(col_colors, dict):
            self._table_model.restore_column_color_rules(col_colors)
        log_cols = doc.get("logarithmic_columns") or []
        self._logarithmic_columns = {
            str(h) for h in log_cols if isinstance(h, str) and h in self.headers
        }
        self.apply_filters()
        rows_n = self._table_model.rowCount()
        self.status_label.setText(loaded_session_status(rows_n))
        if getattr(self, "_sqlite_store", None) is not None:
            self._sqlite_store_dirty = True
        side = deserialize_confs_sidecar(doc.get("confs_sidecar"))
        if side:
            cs = getattr(self, "_confs_blocks_sidecar", None)
            if cs is None:
                self._confs_blocks_sidecar = {}
                cs = self._confs_blocks_sidecar
            cs.update(side)
        from ..som_browser import restore_som_maps_for_session

        restore_som_maps_for_session(self, doc.get("som_browse"))
        restore_ionization_sidecar(doc.get("ionization_sidecar"))
        QTimer.singleShot(0, self._deferred_session_post_load_follow_up)

    def save_session_as(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Session", "", "MolManager Session (*.cms);;JSON (*.json)"
        )
        if not path:
            return
        low = path.lower()
        if not low.endswith(".cms") and not low.endswith(".json"):
            path += ".cms"
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self._build_session_document(), f, separators=(",", ":"))
            self.status_label.setText(f"Session saved to {path}")
        except Exception as e:
            logger.exception("Save session failed: %s", path)
            QMessageBox.warning(self, "Save Session", str(e))

    def open_session_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open Session",
            "",
            "MolManager Session (*.cms *.json);;Legacy session CSV (*.csv);;All files (*.*)",
        )
        if not path:
            return
        if path.lower().endswith(".csv"):
            self.load_session_csv(path)
        else:
            self.apply_saved_session_from_file(path)

    def apply_saved_session_from_file(self, path: str) -> bool:
        try:
            with open(path, "r", encoding="utf-8") as f:
                d = json.load(f)
        except Exception as e:
            logger.exception("Open session: could not read %s", path)
            QMessageBox.warning(self, "Open Session", f"Could not read file: {e}")
            return False
        if (
            not self._session_format_ok(d.get("format"))
            or int(d.get("version", 0)) != self._SESSION_VERSION
        ):
            QMessageBox.warning(
                self, "Open Session", "Not a MolManager session file (expected .cms / version 1)."
            )
            return False
        try:
            self._apply_session_document(d)
        except Exception as e:
            logger.exception("Open session: apply failed for %s", path)
            QMessageBox.warning(self, "Open Session", str(e))
            return False
        return True

    def _abort_csv_session_load(self) -> None:
        """Close an in-progress streamed session CSV load."""
        ctx = getattr(self, "_csv_session_ctx", None)
        if not ctx:
            return
        handle = ctx.get("file")
        if handle is not None:
            try:
                handle.close()
            except Exception:
                pass
        self._csv_session_ctx = None

    def load_session_csv(self, path: str) -> None:
        """Load a session CSV exported by `_write_session_csv` (streamed + chunked on the GUI thread)."""
        import csv

        self.clear_all()
        self._table_stack.setCurrentIndex(1)
        self.status_label.setText("Loading session…")

        f = open(path, "r", encoding="utf-8", errors="replace", newline="")
        reader = csv.DictReader(f)
        cols = list(reader.fieldnames or [])
        if "SMILES" not in cols:
            cols = ["SMILES"] + cols

        self.headers = ["ID_HIDDEN", "Structure"] + cols
        self.table.setSortingEnabled(False)
        self._table_model.clear_rows()
        self._table_model.set_headers(list(self.headers))
        self.table.setColumnHidden(0, True)
        self.mols = {}
        self._clear_filter_target_smiles_cache()
        self.global_bounds = {}
        self.next_oid = 0

        self._session_load_generation = int(getattr(self, "_session_load_generation", 0)) + 1
        gen = self._session_load_generation
        chunk = max(64, load_config().ingest_gui_chunk_size)
        self._csv_session_ctx = {
            "gen": gen,
            "cols": cols,
            "reader": reader,
            "file": f,
            "chunk": chunk,
            "loaded": 0,
        }
        QTimer.singleShot(0, self._load_session_csv_step)

    def _load_session_csv_step(self) -> None:
        ctx = getattr(self, "_csv_session_ctx", None)
        if not ctx or ctx.get("gen") != getattr(self, "_session_load_generation", 0):
            return
        cols = ctx["cols"]
        reader = ctx["reader"]
        chunk = int(ctx["chunk"])
        pack: list[tuple[int, dict[str, str]]] = []
        done = False
        for _ in range(chunk):
            try:
                row = next(reader)
            except StopIteration:
                done = True
                break
            oid = self.next_oid
            self.next_oid += 1
            smi = (row.get("SMILES", "") or "").strip()
            row_cells = {c: str(row.get(c, "") or "") for c in cols}
            pack.append((oid, row_cells))
            mol = Chem.MolFromSmiles(smi) if smi else None
            if mol is not None:
                self.mols[oid] = mol
        if pack:
            self._table_model.append_rows_batch(pack)
            ctx["loaded"] = int(ctx.get("loaded", 0)) + len(pack)
        loaded = int(ctx.get("loaded", 0))
        self.status_label.setText(f"Loading session… ({loaded:,} rows)")
        if not done:
            QTimer.singleShot(0, self._load_session_csv_step)
            return
        handle = ctx.get("file")
        if handle is not None:
            try:
                handle.close()
            except Exception:
                pass
        self._csv_session_ctx = None
        self._finalize_session_csv_load()

    def _deferred_session_post_load_follow_up(self) -> None:
        """Migrate packed ensembles, then auto-render 2D using the same rules as file ingest."""
        migrate = getattr(self, "_migrate_legacy_confs_cells_to_sidecar", None)
        if callable(migrate):
            migrate()
        n = self._table_model.rowCount()
        render = getattr(self, "_try_auto_render_all_structures_after_ingest", None)
        if callable(render) and render():
            return
        self.status_label.setText(loaded_session_status(n) if n else "Ready.")

    def _finalize_session_csv_load(self) -> None:
        self.schedule_calculate_global_bounds()
        self.table.setSortingEnabled(False)
        rows_n = self._table_model.rowCount()
        if getattr(self, "_sqlite_store", None) is not None:
            self._sqlite_store_dirty = True
            schedule = getattr(self, "_schedule_sqlite_rebuild", None)
            if callable(schedule) and rows_n > 0:
                schedule()
        QTimer.singleShot(0, self._deferred_session_post_load_follow_up)
