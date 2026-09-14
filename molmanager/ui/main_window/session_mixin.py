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

from PyQt5.QtCore import QByteArray, QTimer, Qt
from PyQt5.QtWidgets import QApplication, QFileDialog, QMessageBox

from rdkit import Chem

from ...config import load_config
from ...confs_codec import deserialize_confs_sidecar, serialize_confs_sidecar
from ...microstate_cache import restore_ionization_sidecar, serialize_ionization_sidecar
from ...session_codec import (
    SESSION_VERSION_CURRENT,
    compact_session_document,
    dumps_session_document,
    expand_session_document,
    loads_session_bytes,
    session_format_ok,
    session_version_ok,
)
from ...utils import mol_to_canonical_smiles
from ..strings import LOADING_DETAIL_SESSION, loaded_session_status
from ..threadpool_access import start_runnable_on_app_pool
from ..widgets import CategoryFilterCard, FilterCard, SubstructureFilterCard, TextFilterCard
from ...workers.session_rows_parse import (
    SessionRowsParseResult,
    SessionRowsParseSignals,
    SessionRowsParseWorker,
)

logger = logging.getLogger(__name__)


class SessionMixin:
    _SESSION_FORMAT = "molmanager_session"
    _SESSION_FORMAT_ALIASES = frozenset(
        {"molmanager_session", "MOLMANAGER_session", "chemmanager_session"}
    )
    _SESSION_VERSION = SESSION_VERSION_CURRENT

    def _session_format_ok(self, fmt: object) -> bool:
        return session_format_ok(fmt)

    def _session_version_ok(self, version: object) -> bool:
        return session_version_ok(version)

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
        with open(out_path, "wb") as f:
            f.write(dumps_session_document(self._build_session_document()))
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
        structure_smiles: list[str] = []
        for r in range(self._table_model.rowCount()):
            t0 = self._table_model.cell_text(r, 0)
            oid = int(t0) if t0.isdigit() else r
            mol = self.mols.get(oid)
            if mol is None:
                mol = self._mol_for_structure_row(r)
            structure_smiles.append(mol_to_canonical_smiles(mol) if mol is not None else "")
            cells: dict[str, str] = {}
            for ci, h in enumerate(self.headers):
                if h in ("ID_HIDDEN", "Structure"):
                    continue
                if self._table_model.is_pixmap_data_column(h):
                    cells[h] = self._table_model.backing_value_for_row_header(r, h)
                else:
                    cells[h] = self._table_cell_text(r, ci)
            if "SMILES" in cells and not (cells.get("SMILES") or "").strip() and mol is not None:
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
        doc = {
            "format": self._SESSION_FORMAT,
            "version": self._SESSION_VERSION,
            "headers": list(self.headers),
            "rows": rows_out,
            "structure_smiles": structure_smiles,
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
            "docked_plots": self._collect_docked_plots(),
            "floating_plots": self._collect_floating_plots(),
            "table_layout": self._collect_table_layout(),
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
            "mmp_ledger": self._session_mmp_ledger_payload(),
        }
        collect_search = getattr(self, "collect_table_search_session", None)
        if callable(collect_search):
            search_payload = collect_search()
            if search_payload:
                doc["table_search"] = search_payload
        return compact_session_document(doc)

    def _session_som_browse_payload(self) -> list[dict]:
        """Atom-level SOM maps for session restore (redraws table images on open)."""
        from ..som_browser import records_from_table, serialize_som_browse_records

        records = list(getattr(self, "_som_browse_records", None) or ())
        if not records:
            records = records_from_table(self)
        return serialize_som_browse_records(records)

    def _session_mmp_ledger_payload(self) -> dict | None:
        """Last MMP run for Transform Ledger reopen after session open."""
        from ...mmp_analysis import serialize_mmp_ledger_payload

        return serialize_mmp_ledger_payload(
            getattr(self, "_mmp_last_pairs", None),
            activity_column=str(getattr(self, "_mmp_last_activity_column", "") or ""),
        )

    @staticmethod
    def _header_state_b64(header) -> str | None:
        if header is None:
            return None
        try:
            raw = header.saveState()
        except RuntimeError:
            return None
        if raw is None or raw.isEmpty():
            return None
        return bytes(raw.toBase64()).decode("ascii")

    @staticmethod
    def _restore_header_state_b64(header, payload: object) -> bool:
        if header is None or not isinstance(payload, str) or not payload:
            return False
        try:
            raw = QByteArray.fromBase64(payload.encode("ascii"))
            return bool(header.restoreState(raw))
        except (RuntimeError, ValueError):
            return False

    def _collect_table_layout(self) -> dict:
        """Column widths, hidden columns, row chrome, and Qt header state."""
        widths: dict[str, int] = {}
        hidden: list[str] = []
        hh = None
        try:
            hh = self.table.horizontalHeader()
        except RuntimeError:
            hh = None
        updates = False
        try:
            updates = bool(self.table.updatesEnabled())
            self.table.setUpdatesEnabled(False)
        except RuntimeError:
            pass
        try:
            for i, h in enumerate(self.headers):
                if not h:
                    continue
                was_hidden = False
                try:
                    was_hidden = bool(self.table.isColumnHidden(i))
                    if was_hidden and i != 0 and hh is not None:
                        hh.showSection(i)
                    width = int(self.table.columnWidth(i))
                except RuntimeError:
                    width = 0
                if was_hidden:
                    try:
                        self.table.setColumnHidden(i, True)
                    except RuntimeError:
                        pass
                    if i != 0:
                        hidden.append(h)
                if width > 0 and h != "ID_HIDDEN":
                    widths[h] = width
        finally:
            if updates:
                try:
                    self.table.setUpdatesEnabled(True)
                except RuntimeError:
                    pass
        default_h = None
        vh = None
        try:
            vh = self.table.verticalHeader()
            if vh is not None:
                default_h = int(vh.defaultSectionSize())
        except RuntimeError:
            vh = None
        scroll_v = None
        scroll_h = None
        try:
            vbar = self.table.verticalScrollBar()
            hbar = self.table.horizontalScrollBar()
            if vbar is not None:
                scroll_v = int(vbar.value())
            if hbar is not None:
                scroll_h = int(hbar.value())
        except RuntimeError:
            pass
        return {
            "column_widths": widths,
            "hidden_columns": hidden,
            "pixmap_columns": self._table_model.pixmap_data_column_headers(),
            "default_row_height": default_h,
            "hheader_state": self._header_state_b64(hh),
            "vheader_state": self._header_state_b64(vh),
            "scroll_vertical": scroll_v,
            "scroll_horizontal": scroll_h,
        }

    def _restore_table_layout(self, payload: object) -> None:
        if not isinstance(payload, dict):
            return
        try:
            hh = self.table.horizontalHeader()
        except RuntimeError:
            hh = None
        self._restore_header_state_b64(hh, payload.get("hheader_state"))
        widths = payload.get("column_widths")
        if isinstance(widths, dict):
            for name, raw in widths.items():
                if not isinstance(name, str) or name not in self.headers:
                    continue
                try:
                    width = int(raw)
                except (TypeError, ValueError):
                    continue
                if width <= 0:
                    continue
                col = self.headers.index(name)
                try:
                    self.table.setColumnWidth(col, width)
                except RuntimeError:
                    pass
        hidden = payload.get("hidden_columns")
        if isinstance(hidden, list):
            for name in hidden:
                if not isinstance(name, str) or name not in self.headers or name == "ID_HIDDEN":
                    continue
                try:
                    self.table.setColumnHidden(self.headers.index(name), True)
                except RuntimeError:
                    pass
        pix_cols = payload.get("pixmap_columns")
        if isinstance(pix_cols, list):
            for name in pix_cols:
                if (
                    isinstance(name, str)
                    and name in self.headers
                    and name not in ("ID_HIDDEN", "Structure")
                ):
                    self._table_model.register_pixmap_column(name)
        try:
            vh = self.table.verticalHeader()
        except RuntimeError:
            vh = None
        self._restore_header_state_b64(vh, payload.get("vheader_state"))
        raw_h = payload.get("default_row_height")
        try:
            row_h = int(raw_h)
        except (TypeError, ValueError):
            row_h = 0
        if row_h > 0:
            try:
                if vh is not None:
                    vh.setDefaultSectionSize(row_h)
            except RuntimeError:
                pass
        try:
            self.table.setColumnHidden(0, True)
        except RuntimeError:
            pass
        try:
            vbar = self.table.verticalScrollBar()
            hbar = self.table.horizontalScrollBar()
            sv = payload.get("scroll_vertical")
            sh = payload.get("scroll_horizontal")
            if vbar is not None and isinstance(sv, (int, float)):
                vbar.setValue(int(sv))
            if hbar is not None and isinstance(sh, (int, float)):
                hbar.setValue(int(sh))
        except RuntimeError:
            pass

    def _collect_docked_plots(self) -> dict:
        """Docked plot widgets keyed by workspace pane (Plotter and analysis maps)."""
        mgr = getattr(self, "_workspace_layout", None)
        if mgr is None:
            return {"panes": [], "preferred_pane_id": None, "layout_id": None}
        panes_out: list[dict] = []
        for i, pane in enumerate(mgr.plot_panes()):
            plots: list[dict] = []
            for widget in pane.plot_widgets():
                collect = getattr(widget, "collect_session_state", None)
                if not callable(collect):
                    continue
                try:
                    state = collect()
                except Exception:
                    logger.exception("Skipping docked plot while collecting session state")
                    continue
                if not isinstance(state, dict):
                    continue
                try:
                    json.dumps(state)
                except (TypeError, ValueError):
                    logger.exception(
                        "Skipping docked plot with non-JSON-serializable session state"
                    )
                    continue
                kind = str(state.get("kind") or "plotter")
                entry: dict = {"kind": kind, "state": state}
                custom_title = getattr(widget, "_pane_display_title", None)
                if isinstance(custom_title, str) and custom_title.strip():
                    entry["display_title"] = custom_title.strip()
                plots.append(entry)
            if not plots:
                continue
            panes_out.append(
                {
                    "pane_id": pane.pane_id,
                    "pane_index": i,
                    "current": pane.page_index(),
                    "plots": plots,
                }
            )
        pref = mgr.preferred_pane()
        return {
            "panes": panes_out,
            "preferred_pane_id": pref.pane_id if pref is not None else None,
            "layout_id": mgr.layout_id,
        }

    def _iter_floating_plot_hosts(self) -> list:
        """Floating plot/viewer/browser dialogs that can be session-serialized."""
        hosts: list = []
        seen: set[int] = set()

        def add(dlg) -> None:
            if dlg is None:
                return
            try:
                from PyQt5 import sip

                if sip.isdeleted(dlg):
                    return
            except Exception:
                pass
            key = id(dlg)
            if key in seen:
                return
            seen.add(key)
            hosts.append(dlg)

        for dlg in list(getattr(self, "_plot_dialogs", []) or []):
            add(dlg)
        for dlg in list(getattr(self, "_floating_result_dialogs", []) or []):
            add(dlg)
        for attr in (
            "_pca_dialog",
            "_tsne_dialog",
            "_umap_dialog",
            "_som_dialog",
            "_boiled_egg_dialog",
            "_golden_triangle_dialog",
            "_sali_map_dialog",
            "_activity_cliff_map_dialog",
            "_mmp_neighborhood_map_dialog",
            "_selection_browser_dialog",
            "_som_browser_dialog",
            "_molecule_3d_viewer_dialog",
        ):
            add(getattr(self, attr, None))
        return hosts

    @staticmethod
    def _floating_plot_panel(dlg):
        for attr in ("_plot_widget", "_panel", "_viewer_widget"):
            panel = getattr(dlg, attr, None)
            if panel is not None:
                return panel
        return None

    def _collect_floating_plots(self) -> list[dict]:
        """Undocked plot windows to restore beside docked panes."""
        out: list[dict] = []
        for dlg in self._iter_floating_plot_hosts():
            panel = self._floating_plot_panel(dlg)
            if panel is None:
                continue
            collect = getattr(panel, "collect_session_state", None)
            if not callable(collect):
                continue
            try:
                state = collect()
            except Exception:
                logger.exception("Skipping floating plot while collecting session state")
                continue
            if not isinstance(state, dict):
                continue
            try:
                json.dumps(state)
            except (TypeError, ValueError):
                logger.exception("Skipping floating plot with non-JSON-serializable session state")
                continue
            kind = str(state.get("kind") or "plotter")
            entry: dict = {"kind": kind, "state": state}
            custom_title = getattr(panel, "_pane_display_title", None)
            if isinstance(custom_title, str) and custom_title.strip():
                entry["display_title"] = custom_title.strip()
            try:
                geo = dlg.saveGeometry()
                if geo is not None and not geo.isEmpty():
                    entry["geometry"] = bytes(geo.toBase64()).decode("ascii")
            except RuntimeError:
                pass
            try:
                title = str(dlg.windowTitle() or "").strip()
            except RuntimeError:
                title = ""
            if title:
                entry["window_title"] = title
            out.append(entry)
        return out

    def _discard_floating_plot_dialogs(self) -> None:
        """Close floating plot windows so a session restore starts clean."""
        for dlg in list(self._iter_floating_plot_hosts()):
            try:
                dlg._force_close = True
            except Exception:
                pass
            try:
                dlg.hide()
                dlg.close()
            except RuntimeError:
                pass
            try:
                dlg.setParent(None)
            except RuntimeError:
                pass
        self._plot_dialogs = []
        self._floating_result_dialogs = []
        for attr in (
            "_pca_dialog",
            "_tsne_dialog",
            "_umap_dialog",
            "_som_dialog",
            "_boiled_egg_dialog",
            "_golden_triangle_dialog",
            "_sali_map_dialog",
            "_activity_cliff_map_dialog",
            "_mmp_neighborhood_map_dialog",
            "_selection_browser_dialog",
            "_som_browser_dialog",
            "_molecule_3d_viewer_dialog",
        ):
            if getattr(self, attr, None) is not None:
                setattr(self, attr, None)

    def _discard_docked_plot_widgets(self) -> None:
        """Detach and delete docked plot widgets so a session restore starts clean."""
        mgr = getattr(self, "_workspace_layout", None)
        if mgr is None:
            return
        widgets = []
        for pane in mgr.plot_panes():
            widgets.extend(pane.plot_widgets())
            pane.set_plot_widgets([])
        for widget in widgets:
            try:
                widget.setParent(None)
                widget.deleteLater()
            except RuntimeError:
                pass

    def _restore_docked_plot_widget(self, spec: dict):
        from ..docked_plot_session import restore_docked_plot_widget

        return restore_docked_plot_widget(self, spec)

    def _resolve_session_workspace_layout_id(
        self, docked_payload: object, panes_data: list
    ) -> str | None:
        """Pick the workspace layout id to use when restoring docked plots."""
        from .workspace_layout import (
            LAYOUT_PRESETS,
            LAYOUT_TABLE_SIDE,
            LAYOUT_TABLE_SINGLE,
        )

        known = {p[0] for p in LAYOUT_PRESETS}
        candidates: list[str] = []
        for source in (
            getattr(self, "_pending_session_workspace_layout", None),
            docked_payload if isinstance(docked_payload, dict) else None,
        ):
            if not isinstance(source, dict):
                continue
            lid = source.get("layout_id")
            if isinstance(lid, str) and lid in known and lid != "table_only":
                if lid not in candidates:
                    candidates.append(lid)

        max_idx = 0
        for spec in panes_data:
            if not isinstance(spec, dict):
                continue
            try:
                max_idx = max(max_idx, int(spec.get("pane_index", 0)))
            except (TypeError, ValueError):
                continue
        need_multi = max_idx > 0 or len(panes_data) > 1

        # Prefer an explicit id that can host the saved pane indices.
        for lid in candidates:
            if need_multi and lid == LAYOUT_TABLE_SINGLE:
                continue
            return lid
        if candidates:
            return candidates[0]

        if not panes_data:
            return None
        if not need_multi:
            return LAYOUT_TABLE_SINGLE
        # Prefer side-by-side over stacked when the saved layout id is unavailable.
        return LAYOUT_TABLE_SIDE

    def _restore_floating_plots(self, payload: object) -> None:
        """Re-open undocked plot windows from session state."""
        if not isinstance(payload, list) or not payload:
            return
        from ..dockable_plot import plot_widget_display_title

        for spec in payload:
            if not isinstance(spec, dict):
                continue
            widget = self._restore_docked_plot_widget(spec)
            if widget is None:
                continue
            factory = getattr(widget, "create_floating_dialog", None)
            if not callable(factory):
                try:
                    widget.setParent(None)
                    widget.deleteLater()
                except RuntimeError:
                    pass
                continue
            try:
                dlg = factory(self)
            except Exception:
                logger.exception("Failed to recreate floating plot from session")
                try:
                    widget.setParent(None)
                    widget.deleteLater()
                except RuntimeError:
                    pass
                continue
            prepare = getattr(self, "_prepare_tool_dialog", None)
            if callable(prepare):
                prepare(dlg)
            # Prefer plotter registration without importing PlotDialog (WebEngine).
            if (
                getattr(dlg, "_plot_widget", None) is not None
                and getattr(dlg, "_panel", None) is None
            ):
                self._register_plot_dialog(dlg)
            elif not self._bind_undocked_browser_dialog(dlg):
                self._register_floating_result_dialog(dlg)
            title = spec.get("display_title") or spec.get("window_title")
            if isinstance(title, str) and title.strip():
                try:
                    dlg.setWindowTitle(title.strip())
                except RuntimeError:
                    pass
            else:
                try:
                    dlg.setWindowTitle(plot_widget_display_title(widget))
                except RuntimeError:
                    pass
            geo = spec.get("geometry")
            if isinstance(geo, str) and geo:
                try:
                    raw = QByteArray.fromBase64(geo.encode("ascii"))
                    dlg.restoreGeometry(raw)
                except (RuntimeError, ValueError):
                    pass
            sync = getattr(widget, "_sync_footer_chrome", None)
            if callable(sync):
                sync()
            try:
                if getattr(self, "_session_hold_workspace_surfaces", False):
                    widget.hide()
                    dlg.hide()
                else:
                    widget.show()
                    dlg.show()
            except RuntimeError:
                pass

    def _restore_docked_plots(self, payload: object) -> None:
        mgr = getattr(self, "_workspace_layout", None)
        if mgr is None:
            return
        panes_data = payload.get("panes") if isinstance(payload, dict) else None
        if not isinstance(panes_data, list):
            panes_data = []
        saved_layout = self._resolve_session_workspace_layout_id(payload, panes_data)
        if panes_data:
            need_layout = False
            if not mgr.plot_panes():
                need_layout = True
            elif saved_layout and mgr.layout_id != saved_layout:
                need_layout = True
            elif saved_layout:
                # Enough panes for the highest saved pane index?
                max_idx = 0
                for spec in panes_data:
                    if not isinstance(spec, dict):
                        continue
                    try:
                        max_idx = max(max_idx, int(spec.get("pane_index", 0)))
                    except (TypeError, ValueError):
                        continue
                if max_idx >= len(mgr.plot_panes()):
                    need_layout = True
            if need_layout and saved_layout:
                mgr.apply_layout(saved_layout, preserve_plots=False)
        for pane in mgr.plot_panes():
            leftover = pane.plot_widgets()
            pane.set_plot_widgets([])
            for widget in leftover:
                try:
                    widget.setParent(None)
                    widget.deleteLater()
                except RuntimeError:
                    pass
        if not panes_data:
            return
        for spec in panes_data:
            if not isinstance(spec, dict):
                continue
            pane = None
            pane_id = spec.get("pane_id")
            if isinstance(pane_id, str) and pane_id:
                pane = mgr.find_pane(pane_id)
            if pane is None:
                try:
                    idx = int(spec.get("pane_index", 0))
                except (TypeError, ValueError):
                    idx = 0
                panes = mgr.plot_panes()
                if not panes:
                    continue
                pane = panes[max(0, min(idx, len(panes) - 1))]
            widgets = []
            for plot_spec in spec.get("plots") or []:
                if not isinstance(plot_spec, dict):
                    continue
                widget = self._restore_docked_plot_widget(plot_spec)
                if widget is None:
                    continue
                widgets.append(widget)
            if not widgets:
                continue
            for widget in widgets:
                wire = getattr(self, "_wire_docked_plot_widget", None)
                if callable(wire):
                    wire(widget)
            try:
                current = int(spec.get("current", 0))
            except (TypeError, ValueError):
                current = 0
            pane.set_plot_widgets(widgets, current=current)
        pref_id = payload.get("preferred_pane_id") if isinstance(payload, dict) else None
        if isinstance(pref_id, str) and pref_id:
            pref = mgr.find_pane(pref_id)
            if pref is not None:
                mgr.set_preferred_pane(pref)
        # Re-assert saved workspace layout in case docking hooks changed it.
        if saved_layout and mgr.layout_id != saved_layout:
            mgr.apply_layout(saved_layout, preserve_plots=True)
        show = getattr(self, "show_docked_plot_panel", None)
        if callable(show):
            show()

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
        try:
            doc = expand_session_document(doc)
        except ValueError as exc:
            raise ValueError(str(exc) or "Unsupported session format.") from exc
        if not self._session_format_ok(doc.get("format")) or not self._session_version_ok(
            doc.get("version")
        ):
            raise ValueError("Unsupported session format.")
        self._session_mutation_paused = True
        self._pending_session_clean_on_ready = True
        self._session_restore_ctx = None
        self._session_finalize_ctx = None
        self._session_parse_busy = False
        self._session_awaiting_ready = False
        self._session_waiting_for_render = False
        self._session_plot_wait_deadline = None
        self._discard_floating_plot_dialogs()
        self.clear_all()
        self._session_hold_workspace_surfaces = True
        # clear_all() bumps the load generation; capture after that so callbacks match.
        self._session_load_generation = int(getattr(self, "_session_load_generation", 0)) + 1
        gen = self._session_load_generation
        self._set_ingest_loading(True)
        self._table_stack.setCurrentIndex(0)
        self._loading_detail.setText(LOADING_DETAIL_SESSION)
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
        layout_early = doc.get("table_layout")
        if isinstance(layout_early, dict):
            pix_cols = layout_early.get("pixmap_columns")
            if isinstance(pix_cols, list):
                for name in pix_cols:
                    if (
                        isinstance(name, str)
                        and name in self.headers
                        and name not in ("ID_HIDDEN", "Structure")
                    ):
                        self._table_model.register_pixmap_column(name)
        self.table.setColumnHidden(0, True)
        self.mols = {}
        self._clear_filter_target_smiles_cache()
        self.global_bounds = {}
        rows = doc.get("rows") or []
        try:
            self.table.setUpdatesEnabled(False)
        except Exception:
            pass

        if not rows:
            self._begin_session_finalize(doc, -1, gen=gen)
        else:
            self._loading_detail.setText(f"Parsing structures…\n0 / {len(rows):,} rows")
            self.status_label.setText(f"Loading session… (parsing {len(rows):,} rows)")
            self._session_parse_busy = True
            signals = SessionRowsParseSignals(self)

            def _on_parsed(result, g=gen, d=doc) -> None:
                self._on_session_rows_parsed(result, g, d)

            def _on_failed(message, g=gen) -> None:
                self._on_session_rows_parse_failed(message, g)

            worker = SessionRowsParseWorker(
                list(rows),
                data_headers=list(self.headers[2:]),
                signals=signals,
                generation=gen,
                structure_smiles=list(doc.get("structure_smiles") or []),
            )
            # Pytest has no lasting event-loop turn for threadpool completions; parse inline.
            if "pytest" in sys.modules:
                signals.finished.connect(_on_parsed, type=Qt.DirectConnection)
                signals.failed.connect(_on_failed, type=Qt.DirectConnection)
                worker.run()
            else:
                signals.finished.connect(_on_parsed, type=Qt.QueuedConnection)
                signals.failed.connect(_on_failed, type=Qt.QueuedConnection)
                start_runnable_on_app_pool(self, worker)

        # Tests call apply synchronously; drain until async restore finishes.
        if "pytest" in sys.modules:
            self._drain_pending_session_load()

    def _drain_pending_session_load(self, *, timeout_s: float = 60.0) -> None:
        """Process Qt events until session parse/apply/finalize complete."""
        deadline = time.monotonic() + float(timeout_s)
        while time.monotonic() < deadline:
            busy = bool(getattr(self, "_session_parse_busy", False))
            busy = busy or getattr(self, "_session_restore_ctx", None) is not None
            busy = busy or getattr(self, "_session_finalize_ctx", None) is not None
            busy = busy or bool(getattr(self, "_session_awaiting_ready", False))
            if not busy:
                return
            QApplication.processEvents()
            time.sleep(0.001)
        raise TimeoutError("Timed out waiting for session restore to finish.")

    def _session_gui_chunk_size(self) -> int:
        return max(64, int(load_config().ingest_gui_chunk_size))

    def _on_session_rows_parse_failed(self, message: str, generation: int) -> None:
        if generation != getattr(self, "_session_load_generation", 0):
            return
        self._session_parse_busy = False
        self._session_awaiting_ready = False
        self._session_waiting_for_render = False
        self._session_hold_workspace_surfaces = False
        self._show_session_workspace_when_ready()
        try:
            self.table.setUpdatesEnabled(True)
        except Exception:
            pass
        self._set_ingest_loading(False)
        self._session_mutation_paused = False
        self._pending_session_clean_on_ready = False
        self._table_stack.setCurrentIndex(1)
        QMessageBox.warning(self, "Open Session", message or "Session row parse failed.")

    def _on_session_rows_parsed(self, result: object, generation: int, doc: dict) -> None:
        if generation != getattr(self, "_session_load_generation", 0):
            return
        self._session_parse_busy = False
        if not isinstance(result, SessionRowsParseResult):
            self._on_session_rows_parse_failed("Invalid session parse result.", generation)
            return
        prepared = list(result.prepared_rows or [])
        try:
            self.mols.update(result.mols or {})
        except Exception:
            self.mols = dict(result.mols or {})
        if not prepared:
            self._begin_session_finalize(doc, int(result.max_id), gen=generation)
            return
        chunk = self._session_gui_chunk_size()
        self._session_restore_ctx = {
            "gen": generation,
            "doc": doc,
            "prepared_rows": prepared,
            "idx": 0,
            "chunk": chunk,
            "max_id": int(result.max_id),
        }
        n = len(prepared)
        self.status_label.setText(f"Loading session… (0/{n} rows)")
        self._loading_detail.setText(f"Loading session…\n0 / {n:,} rows")
        QTimer.singleShot(0, self._session_restore_apply_step)

    def _session_restore_apply_step(self) -> None:
        ctx = getattr(self, "_session_restore_ctx", None)
        if not ctx or ctx.get("gen") != getattr(self, "_session_load_generation", 0):
            try:
                self.table.setUpdatesEnabled(True)
            except Exception:
                pass
            return
        prepared = ctx["prepared_rows"]
        doc = ctx["doc"]
        i = int(ctx["idx"])
        chunk = int(ctx["chunk"])
        max_id = int(ctx["max_id"])
        n = len(prepared)
        end = min(i + chunk, n)
        batch = prepared[i:end]
        if batch:
            self._table_model.append_rows_batch(batch)
        ctx["idx"] = end
        self.status_label.setText(f"Loading session… ({end}/{n} rows)")
        self._loading_detail.setText(f"Loading session…\n{end:,} / {n:,} rows")
        if end < n:
            QTimer.singleShot(0, self._session_restore_apply_step)
            return
        self._session_restore_ctx = None
        self._loading_detail.setText(
            f"Session loaded ({n:,} row(s)).\nRestoring filters and workspace…"
        )
        self._begin_session_finalize(doc, max_id, gen=int(ctx["gen"]))

    def _begin_session_finalize(self, doc: dict, max_id: int, *, gen: int) -> None:
        self._session_finalize_ctx = {
            "gen": int(gen),
            "doc": doc,
            "max_id": int(max_id),
            "step": 0,
        }
        QTimer.singleShot(0, self._session_finalize_step)

    def _session_finalize_step(self) -> None:
        ctx = getattr(self, "_session_finalize_ctx", None)
        if not ctx or ctx.get("gen") != getattr(self, "_session_load_generation", 0):
            return
        doc = ctx["doc"]
        max_id = int(ctx["max_id"])
        step = int(ctx["step"])
        try:
            if step == 0:
                self._loading_detail.setText("Restoring filters…")
                self._finalize_session_filters(doc, max_id)
                ctx["step"] = 1
                QTimer.singleShot(0, self._session_finalize_step)
                return
            if step == 1:
                self._loading_detail.setText("Restoring workspace and plots…")
                self._finalize_session_workspace_and_plots(doc)
                ctx["step"] = 2
                QTimer.singleShot(0, self._session_finalize_step)
                return
            if step == 2:
                self._loading_detail.setText("Applying sort, colors, and filters…")
                self._finalize_session_table_chrome(doc)
                ctx["step"] = 3
                QTimer.singleShot(0, self._session_finalize_step)
                return
            # step 3 — sidecars + reveal
            self._loading_detail.setText("Restoring tool data…")
            self._finalize_session_sidecars_and_reveal(doc)
            self._session_finalize_ctx = None
        except Exception:
            self._session_finalize_ctx = None
            self._session_awaiting_ready = False
            self._session_waiting_for_render = False
            self._session_hold_workspace_surfaces = False
            self._show_session_workspace_when_ready()
            try:
                self.table.setUpdatesEnabled(True)
            except Exception:
                pass
            self._set_ingest_loading(False)
            self._session_mutation_paused = False
            self._pending_session_clean_on_ready = False
            self._table_stack.setCurrentIndex(1)
            raise

    def _finalize_session_filters(self, doc: dict, max_id: int) -> None:
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

    def _finalize_session_workspace_and_plots(self, doc: dict) -> None:
        self._discard_docked_plot_widgets()
        ws = doc.get("workspace_layout")
        self._pending_session_workspace_layout = ws if isinstance(ws, dict) else None
        self._pending_session_column_order = (
            doc.get("column_logical_order")
            if isinstance(doc.get("column_logical_order"), list)
            else None
        )
        mgr = getattr(self, "_workspace_layout", None)
        docked_payload = doc.get("docked_plots")
        panes_data = docked_payload.get("panes") if isinstance(docked_payload, dict) else None
        if not isinstance(panes_data, list):
            panes_data = []
        saved_layout = self._resolve_session_workspace_layout_id(docked_payload, panes_data)
        if mgr is not None and saved_layout:
            if mgr.layout_id != saved_layout:
                mgr.apply_layout(saved_layout, preserve_plots=False)
            if isinstance(ws, dict):
                mgr.restore_splitter_sizes(ws)
        elif mgr is not None and isinstance(ws, dict):
            layout_id = ws.get("layout_id")
            if isinstance(layout_id, str) and layout_id:
                mgr.apply_layout(layout_id, preserve_plots=False)
            mgr.restore_splitter_sizes(ws)
        elif getattr(self, "_workspace_layout", None) is not None:
            saved_w = doc.get("plot_panel_width")
            if isinstance(saved_w, (int, float)) and saved_w > 0:
                ensure = getattr(self, "_ensure_plot_panel_width", None)
                if callable(ensure):
                    QTimer.singleShot(0, lambda: ensure(int(saved_w)))
        self._restore_docked_plots(docked_payload)
        # Re-assert after docking hooks so side-by-side cannot collapse to stacked.
        if mgr is not None and saved_layout and mgr.layout_id != saved_layout:
            mgr.apply_layout(saved_layout, preserve_plots=True)
            if isinstance(ws, dict):
                mgr.restore_splitter_sizes(ws)
        self._restore_floating_plots(doc.get("floating_plots"))
        self._hide_session_workspace_until_ready()
        self._restore_pending_workspace_layout()
        co = self._pending_session_column_order
        if isinstance(co, list):
            self._restore_column_visual_order([int(x) for x in co])

    def _finalize_session_table_chrome(self, doc: dict) -> None:
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

    def _finalize_session_sidecars_and_reveal(self, doc: dict) -> None:
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
        from ...mmp_analysis import restore_mmp_ledger_for_session

        restore_mmp_ledger_for_session(self, doc.get("mmp_ledger"))
        self._pending_session_table_layout = doc.get("table_layout")
        self._restore_table_layout(self._pending_session_table_layout)
        restore_search = getattr(self, "restore_table_search_session", None)
        if callable(restore_search):
            restore_search(doc.get("table_search"))
        self._session_awaiting_ready = True
        self._session_waiting_for_render = False
        self._session_plot_wait_deadline = None
        self._hide_session_workspace_until_ready()
        self._deferred_session_post_load_follow_up()

    def _reveal_table_after_session_prep(self) -> None:
        """Leave the loading overlay once session rows, 2D renders, and plots are ready."""
        self._set_ingest_loading(False)
        self._table_stack.setCurrentIndex(1)
        finish_clean = getattr(self, "_finish_session_clean_if_pending", None)
        if callable(finish_clean):
            finish_clean()
        try:
            self.table.setUpdatesEnabled(True)
        except Exception:
            pass

    def _hide_session_workspace_until_ready(self) -> None:
        """Keep independent floating plot windows hidden until the workspace overlay lifts."""
        if not getattr(self, "_session_hold_workspace_surfaces", False):
            return
        for dlg in self._iter_floating_plot_hosts():
            try:
                dlg.hide()
            except RuntimeError:
                pass

    def _show_session_workspace_when_ready(self) -> None:
        """Show restored floating plot windows and Search with the rest of the workspace."""
        self._session_hold_workspace_surfaces = False
        for dlg in self._iter_floating_plot_hosts():
            try:
                dlg.show()
            except RuntimeError:
                pass
        panel = getattr(self, "_search_panel", None)
        if panel is not None and getattr(self, "_session_search_want_visible", False):
            try:
                panel.setVisible(True)
                populate = getattr(self, "_populate_table_search_columns_combo", None)
                if callable(populate):
                    populate()
            except RuntimeError:
                pass
        self._session_search_want_visible = False

    def _session_plot_host_waiting_for_web(self, host) -> bool:
        """True when a restored plot still has a Plotly payload waiting on the WebEngine."""
        stack = [host]
        seen: set[int] = set()
        while stack:
            widget = stack.pop()
            if widget is None:
                continue
            key = id(widget)
            if key in seen:
                continue
            seen.add(key)
            if hasattr(widget, "_web_ready") and not bool(getattr(widget, "_web_ready", False)):
                if getattr(widget, "_pending_payload_json", None):
                    return True
            for attr in ("_plot_widget", "_panel", "_viewer_widget", "_view"):
                child = getattr(widget, attr, None)
                if child is not None:
                    stack.append(child)
        return False

    def _session_plots_ready_for_reveal(self) -> bool:
        """Skip waiting in tests; otherwise poll briefly so Plotly views are not blank."""
        if "pytest" in sys.modules:
            return True
        hosts_fn = getattr(self, "_iter_active_plot_hosts", None)
        hosts = list(hosts_fn()) if callable(hosts_fn) else []
        if not hosts:
            return True
        now = time.monotonic()
        deadline = getattr(self, "_session_plot_wait_deadline", None)
        if deadline is None:
            self._session_plot_wait_deadline = now + 8.0
            deadline = self._session_plot_wait_deadline
        if now >= float(deadline):
            return True
        for host in hosts:
            if self._session_plot_host_waiting_for_web(host):
                return False
        return True

    def _session_on_render2d_batch_finished(self) -> None:
        """Continue session reveal after auto Render 2D (or cancel) completes."""
        if getattr(self, "_session_waiting_for_render", False):
            self._session_waiting_for_render = False
        if not getattr(self, "_session_awaiting_ready", False):
            return
        detail = getattr(self, "_loading_detail", None)
        if detail is not None:
            try:
                detail.setText("Preparing plots…")
            except RuntimeError:
                pass
        QTimer.singleShot(0, self._session_try_reveal_when_ready)

    def _session_try_reveal_when_ready(self) -> None:
        """Show the workspace once 2D drawing and plot views have settled."""
        if not getattr(self, "_session_awaiting_ready", False):
            return
        if getattr(self, "_session_waiting_for_render", False):
            return
        if not self._session_plots_ready_for_reveal():
            detail = getattr(self, "_loading_detail", None)
            if detail is not None:
                try:
                    detail.setText("Preparing plots…")
                except RuntimeError:
                    pass
            QTimer.singleShot(50, self._session_try_reveal_when_ready)
            return
        self._session_awaiting_ready = False
        self._session_plot_wait_deadline = None
        self._show_session_workspace_when_ready()
        self._restore_pending_workspace_layout()
        self._reveal_table_after_session_prep()
        rerun = getattr(self, "_rerun_restored_table_search", None)
        if callable(rerun):
            rerun()
        finish = getattr(self, "_finish_deferred_session_workspace_restore", None)
        if callable(finish):
            QTimer.singleShot(0, finish)
        n = self._table_model.rowCount()
        self.status_label.setText(loaded_session_status(n) if n else "Ready.")

    def save_session_as(self) -> bool:
        """Prompt for a path and save the session. Returns True if a file was written."""
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Session", "", "MolManager Session (*.cms);;JSON (*.json)"
        )
        if not path:
            return False
        low = path.lower()
        if not low.endswith(".cms") and not low.endswith(".json"):
            path += ".cms"
        try:
            with open(path, "wb") as f:
                f.write(dumps_session_document(self._build_session_document()))
            self.status_label.setText(f"Session saved to {path}")
            clear = getattr(self, "_clear_session_dirty", None)
            if callable(clear):
                clear()
            return True
        except Exception as e:
            logger.exception("Save session failed: %s", path)
            QMessageBox.warning(self, "Save Session", str(e))
            return False

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
            with open(path, "rb") as f:
                raw = f.read()
            d = expand_session_document(loads_session_bytes(raw))
        except Exception as e:
            logger.exception("Open session: could not read %s", path)
            QMessageBox.warning(self, "Open Session", f"Could not read file: {e}")
            return False
        if not self._session_format_ok(d.get("format")) or not self._session_version_ok(
            d.get("version")
        ):
            QMessageBox.warning(
                self,
                "Open Session",
                "Not a MolManager session file (expected .cms / version 1–2).",
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

        self._session_mutation_paused = True
        self._pending_session_clean_on_ready = True
        self.clear_all()
        self._set_ingest_loading(True)
        self._table_stack.setCurrentIndex(0)
        self._loading_detail.setText(LOADING_DETAIL_SESSION)
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
        try:
            self.table.setUpdatesEnabled(False)
        except Exception:
            pass

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
        self._loading_detail.setText(f"Loading session…\n{loaded:,} rows")
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
        self._loading_detail.setText(f"Session loaded ({loaded:,} row(s)).\nPreparing table…")
        self._finalize_session_csv_load()

    def _restore_pending_workspace_layout(self) -> None:
        """Re-apply saved splitter ratios after the workspace has a real size."""
        pending = getattr(self, "_pending_session_workspace_layout", None)
        if not isinstance(pending, dict):
            return
        mgr = getattr(self, "_workspace_layout", None)
        if mgr is None:
            return
        lid = pending.get("layout_id")
        if isinstance(lid, str) and lid and mgr.layout_id != lid:
            try:
                mgr.apply_layout(lid, preserve_plots=True)
            except RuntimeError:
                pass
        try:
            mgr.restore_splitter_sizes(pending)
        except RuntimeError:
            pass

    def _deferred_session_post_load_follow_up(self) -> None:
        """Migrate packed ensembles, then auto-render 2D using the same rules as file ingest."""
        migrate = getattr(self, "_migrate_legacy_confs_cells_to_sidecar", None)
        if callable(migrate):
            migrate()
        render = getattr(self, "_try_auto_render_all_structures_after_ingest", None)
        pending = getattr(self, "_pending_session_table_layout", None)
        self._restore_pending_workspace_layout()
        if callable(render) and render():
            self._session_waiting_for_render = True
            detail = getattr(self, "_loading_detail", None)
            if detail is not None:
                try:
                    detail.setText("Drawing 2D structures…")
                except RuntimeError:
                    pass
            self._restore_session_table_chrome(pending)
            self._restore_pending_workspace_layout()
            QTimer.singleShot(0, self._restore_pending_workspace_layout)
            return
        self._restore_session_table_chrome(pending)
        self._session_try_reveal_when_ready()

    def _restore_session_table_chrome(self, payload: object | None = None) -> None:
        """Re-apply saved table layout and column order after other session side effects."""
        layout = (
            payload if payload is not None else getattr(self, "_pending_session_table_layout", None)
        )
        if layout is not None:
            self._restore_table_layout(layout)
        co = getattr(self, "_pending_session_column_order", None)
        if isinstance(co, list):
            try:
                self._restore_column_visual_order([int(x) for x in co])
            except (TypeError, ValueError):
                pass

    def _finish_deferred_session_workspace_restore(self) -> None:
        self._restore_pending_workspace_layout()
        self._restore_session_table_chrome()
        self._pending_session_table_layout = None
        self._pending_session_column_order = None
        self._pending_session_workspace_layout = None

    def _finalize_session_csv_load(self) -> None:
        self.schedule_calculate_global_bounds()
        self.table.setSortingEnabled(False)
        rows_n = self._table_model.rowCount()
        if getattr(self, "_sqlite_store", None) is not None:
            self._sqlite_store_dirty = True
            schedule = getattr(self, "_schedule_sqlite_rebuild", None)
            if callable(schedule) and rows_n > 0:
                schedule()
        self._session_hold_workspace_surfaces = True
        self._session_awaiting_ready = True
        self._session_waiting_for_render = False
        self._session_plot_wait_deadline = None
        self._deferred_session_post_load_follow_up()
