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

"""Session save / document build / File open-save entry points."""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import tempfile
import time

from PyQt5.QtWidgets import QFileDialog, QMessageBox

from ...confs_codec import serialize_confs_sidecar
from ...microstate_cache import serialize_ionization_sidecar
from ...services.filter_config import cfg_column
from ...session_codec import (
    compact_global_bounds,
    compact_session_document,
    dumps_session_document,
    encode_mol_blob_b64,
    expand_session_document,
    loads_session_bytes,
    session_format_ok,
    session_version_ok,
)
from ...utils import mol_graph_binary, mol_to_canonical_smiles
from ..qt_widget_utils import qobject_is_deleted
from ..widgets import CategoryFilterCard, FilterCard, SubstructureFilterCard, TextFilterCard

logger = logging.getLogger(__name__)


class SessionSaveMixin:
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
        structure_mols: list[str] = []
        n_rows = self._table_model.rowCount()
        smiles_col = "SMILES" in self.headers
        for r in range(n_rows):
            oid = int(self._table_model.row_oid(r))
            cells: dict[str, str] = {}
            for ci, h in enumerate(self.headers):
                if h in ("ID_HIDDEN", "Structure"):
                    continue
                if self._table_model.is_pixmap_data_column(h):
                    cells[h] = self._table_model.backing_value_for_row_header(r, h)
                else:
                    cells[h] = self._table_cell_text(r, ci)
            mol = self.mols.get(oid)
            if mol is None:
                mol = self._mol_for_structure_row(r)
            structure_mols.append(encode_mol_blob_b64(mol_graph_binary(mol)))
            smi = str(cells.get("SMILES") or "").strip() if smiles_col else ""
            if smi:
                structure_smiles.append(smi)
            else:
                structure_smiles.append(mol_to_canonical_smiles(mol) if mol is not None else "")
                if smiles_col and mol is not None and not (cells.get("SMILES") or "").strip():
                    cells["SMILES"] = structure_smiles[-1]
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
                        "property": cfg_column(cfg),
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
                        "property": cfg_column(cfg),
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
                        "property": cfg_column(cfg),
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
            "structure_mols": structure_mols,
            "global_bounds": compact_global_bounds(getattr(self, "global_bounds", None)),
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
            "protein_viewer": self._collect_protein_viewer(),
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

    def _collect_protein_viewer(self) -> dict | None:
        dlg = getattr(self, "_protein_viewer_dialog", None)
        if dlg is None or qobject_is_deleted(dlg):
            return None
        collect = getattr(dlg, "collect_session_state", None)
        if not callable(collect):
            return None
        try:
            state = collect()
        except Exception:
            logger.exception("Skipping Protein Viewer while collecting session state")
            return None
        if not isinstance(state, dict) or not state.get("structures"):
            return None
        try:
            json.dumps(state)
        except (TypeError, ValueError):
            logger.exception("Skipping Protein Viewer with non-JSON-serializable session state")
            return None
        return state

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
