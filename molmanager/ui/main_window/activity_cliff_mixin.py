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

"""Activity Cliff Map tool entry points."""

from __future__ import annotations

import logging

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QMessageBox

from rdkit import Chem

from ..strings import TOOL_ACTIVITY_CLIFF_MAP
from ...workers import MmpAnalysisWorker
from ..singleton_modeless_dialog import reuse_or_show_modeless_singleton

logger = logging.getLogger(__name__)


class ActivityCliffMixin:
    def open_activity_cliff_dialog(self) -> None:
        if not self.headers or self._table_model.rowCount() == 0:
            QMessageBox.information(
                self,
                TOOL_ACTIVITY_CLIFF_MAP,
                "Load a table with at least one row first.",
            )
            return
        from ..dialogs.activity_cliff import ActivityCliffDialog
        from ..dialogs.mmp import activity_columns_for_mmp

        activity_cols = activity_columns_for_mmp(self, only_selected=False)
        if not activity_cols:
            QMessageBox.information(
                self,
                TOOL_ACTIVITY_CLIFF_MAP,
                "Activity Cliff Map requires at least one numeric activity/property column.",
            )
            return
        d = ActivityCliffDialog(
            structure_sources=self.chemistry_tool_structure_sources(),
            activity_columns=activity_cols,
            selected_row_count=len(self._selected_logical_rows()),
            parent=self,
        )
        self._prepare_tool_dialog(d)
        d.setAttribute(Qt.WA_DeleteOnClose, True)
        d.accepted.connect(lambda *_, dlg=d: self._on_activity_cliff_dialog_accepted(dlg))
        d.show()

    def _on_activity_cliff_dialog_accepted(self, d) -> None:
        p = d.params()
        only_selected = d.only_selected_rows()
        if self._abort_if_only_selected_but_empty(
            only_selected, self._selected_oids_set(), TOOL_ACTIVITY_CLIFF_MAP
        ):
            return
        if not p.activity_column or p.activity_column.startswith("("):
            QMessageBox.information(
                self, TOOL_ACTIVITY_CLIFF_MAP, "Select a numeric activity column."
            )
            return
        if p.activity_column not in self.headers:
            QMessageBox.information(
                self,
                TOOL_ACTIVITY_CLIFF_MAP,
                f"Activity column “{p.activity_column}” is not in the table.",
            )
            return

        mol_data = self.collect_scoped_table_mols(p.structure_source, only_selected=only_selected)
        if not mol_data:
            QMessageBox.information(
                self,
                TOOL_ACTIVITY_CLIFF_MAP,
                "No valid structures were found for the selected source and scope.",
            )
            self.status_label.setText("Ready.")
            return

        act_col = self.headers.index(p.activity_column)
        records: list[tuple[int, Chem.Mol, float]] = []
        for oid, mol in mol_data:
            row = self.get_row_by_id(oid)
            if row < 0:
                continue
            raw = (self._table_cell_text(row, act_col) or "").strip()
            if not raw:
                raw = (
                    self._table_model.backing_value_for_row_header(row, p.activity_column) or ""
                ).strip()
            try:
                activity = float(raw)
            except (TypeError, ValueError):
                continue
            records.append((oid, mol, activity))

        if len(records) < 2:
            QMessageBox.information(
                self,
                TOOL_ACTIVITY_CLIFF_MAP,
                "Need at least two molecules with both a structure and a numeric activity value.",
            )
            self.status_label.setText("Ready.")
            return

        ps = self._tool_progress_state
        self._begin_tool_progress(TOOL_ACTIVITY_CLIFF_MAP, len(records))
        self.process_queue.enqueue(
            f"{TOOL_ACTIVITY_CLIFF_MAP} ({len(records)} rows)",
            lambda ev, rec=records, pp=p, sigs=self.signals, prog=ps: MmpAnalysisWorker(
                rec,
                activity_column=pp.activity_column,
                max_cuts=pp.max_cuts,
                max_variable_heavy_atoms=pp.max_variable_heavy_atoms,
                min_activity_difference=pp.min_activity_difference,
                purpose="activity_cliff",
                x_mode=pp.x_mode,
                signals=sigs,
                cancel_event=ev,
                progress_state=prog,
            ),
        )

    def on_activity_cliff_finished(self, pairs, activity_column: str, x_mode: str) -> None:
        self._finish_tool_progress(TOOL_ACTIVITY_CLIFF_MAP)
        pairs = list(pairs or [])
        if not pairs:
            self.status_label.setText("Ready.")
            QMessageBox.information(
                self,
                TOOL_ACTIVITY_CLIFF_MAP,
                "No matched molecular pairs were found for the current settings.",
            )
            return
        self._open_activity_cliff_map(pairs, activity_column=activity_column, x_mode=x_mode)
        self.status_label.setText(f"Activity Cliff Map: {len(pairs)} pair(s).")

    def on_activity_cliff_failed(self, message: str) -> None:
        self._clear_tool_progress()
        self.status_label.setText("Ready.")
        QMessageBox.warning(
            self, TOOL_ACTIVITY_CLIFF_MAP, message or "Activity Cliff Map failed."
        )

    def _open_activity_cliff_map(self, pairs, *, activity_column: str, x_mode: str) -> None:
        from ..activity_cliff_map import ActivityCliffMapDialog

        def _factory():
            dlg = ActivityCliffMapDialog(
                self, pairs, activity_column=activity_column, x_mode=x_mode
            )
            dlg.setModal(False)
            dlg.setWindowModality(Qt.NonModal)
            return dlg

        def _on_reused(dlg):
            dlg.set_pairs(pairs, activity_column=activity_column, x_mode=x_mode)

        reuse_or_show_modeless_singleton(
            self,
            "_activity_cliff_map_dialog",
            _factory,
            self._on_activity_cliff_map_dialog_destroyed,
            on_reused_visible=_on_reused,
        )

    def _on_activity_cliff_map_dialog_destroyed(self, *_args) -> None:
        self._activity_cliff_map_dialog = None
