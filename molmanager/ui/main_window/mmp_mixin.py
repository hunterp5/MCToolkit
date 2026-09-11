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

"""Matched molecular pair (MMP) analysis entry points."""

from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QMessageBox

from rdkit import Chem

from ..strings import TOOL_MMP
from ...workers import MmpAnalysisWorker
from ..singleton_modeless_dialog import reuse_or_show_modeless_singleton


class MmpMixin:
    def open_mmp_dialog(self) -> None:
        if not self.headers or self._table_model.rowCount() == 0:
            QMessageBox.information(
                self,
                TOOL_MMP,
                "Load a table with at least one row first.",
            )
            return
        from ..dialogs import MmpDialog
        from ..dialogs.mmp import activity_columns_for_mmp

        activity_cols = activity_columns_for_mmp(self, only_selected=False)
        if not activity_cols:
            QMessageBox.information(
                self,
                TOOL_MMP,
                "MMP requires at least one numeric activity/property column.",
            )
            return
        d = MmpDialog(
            structure_sources=self.chemistry_tool_structure_sources(),
            activity_columns=activity_cols,
            selected_row_count=len(self._selected_logical_rows()),
            parent=self,
        )
        self._prepare_tool_dialog(d)
        d.setAttribute(Qt.WA_DeleteOnClose, True)
        d.accepted.connect(lambda *_, dlg=d: self._on_mmp_dialog_accepted(dlg))
        d.show()

    def _on_mmp_dialog_accepted(self, d) -> None:
        p = d.params()
        only_selected = d.only_selected_rows()
        if self._abort_if_only_selected_but_empty(only_selected, self._selected_oids_set(), TOOL_MMP):
            return
        if not p.activity_column or p.activity_column.startswith("("):
            QMessageBox.information(self, TOOL_MMP, "Select a numeric activity column.")
            return
        if p.activity_column not in self.headers:
            QMessageBox.information(
                self,
                TOOL_MMP,
                f"Activity column “{p.activity_column}” is not in the table.",
            )
            return
        if p.core_smarts:
            from ...mmp_analysis import parse_mmp_core_query

            if parse_mmp_core_query(p.core_smarts) is None:
                QMessageBox.information(
                    self,
                    TOOL_MMP,
                    "Core / MCS could not be parsed as SMARTS or SMILES.",
                )
                return

        mol_data = self.collect_scoped_table_mols(p.structure_source, only_selected=only_selected)
        if not mol_data:
            QMessageBox.information(
                self,
                TOOL_MMP,
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
                raw = (self._table_model.backing_value_for_row_header(row, p.activity_column) or "").strip()
            try:
                activity = float(raw)
            except (TypeError, ValueError):
                continue
            records.append((oid, mol, activity))

        if len(records) < 2:
            QMessageBox.information(
                self,
                TOOL_MMP,
                "Need at least two molecules with both a structure and a numeric activity value.",
            )
            self.status_label.setText("Ready.")
            return

        ps = self._tool_progress_state
        self._begin_tool_progress(TOOL_MMP, len(records))
        self.process_queue.enqueue(
            f"{TOOL_MMP} ({len(records)} rows)",
            lambda ev, rec=records, pp=p, sigs=self.signals, prog=ps: MmpAnalysisWorker(
                rec,
                activity_column=pp.activity_column,
                max_cuts=pp.max_cuts,
                max_variable_heavy_atoms=pp.max_variable_heavy_atoms,
                min_activity_difference=pp.min_activity_difference,
                max_activity_difference=pp.max_activity_difference,
                core_smarts=pp.core_smarts,
                signals=sigs,
                cancel_event=ev,
                progress_state=prog,
            ),
        )

    def on_mmp_finished(self, pairs, activity_column: str) -> None:
        self._finish_tool_progress(TOOL_MMP)
        pairs = list(pairs or [])
        if not pairs:
            self.status_label.setText("Ready.")
            QMessageBox.information(
                self,
                TOOL_MMP,
                "No matched molecular pairs were found for the current settings.",
            )
            return

        from ...mmp_analysis import assemble_mmp_table_annotations

        rows, headers = assemble_mmp_table_annotations(
            pairs, activity_column=activity_column
        )
        if rows:
            self.on_calc_finished(rows, headers, finish_progress=False)

        self._mmp_last_pairs = pairs
        self._mmp_last_activity_column = str(activity_column or "")
        mark = getattr(self, "_mark_session_dirty", None)
        if callable(mark):
            mark()
        self._open_mmp_ledger(pairs, activity_column=activity_column)
        self.status_label.setText(f"MMP: {len(pairs)} pair(s).")

    def on_mmp_failed(self, message: str) -> None:
        self._clear_tool_progress()
        self.status_label.setText("Ready.")
        QMessageBox.warning(self, TOOL_MMP, message or "MMP analysis failed.")

    def open_mmp_transform_ledger_for_last_run(self) -> None:
        """Re-open the Transform Ledger for the most recent MMP analysis."""
        pairs = list(getattr(self, "_mmp_last_pairs", None) or [])
        activity_column = str(getattr(self, "_mmp_last_activity_column", "") or "")
        if not pairs:
            QMessageBox.information(
                self,
                TOOL_MMP,
                "No MMP results are available in this session. Run Data → MMP first.",
            )
            return
        self._open_mmp_ledger(pairs, activity_column=activity_column)

    def _open_mmp_ledger(self, pairs, *, activity_column: str) -> None:
        from ..mmp_transform_ledger import MmpTransformLedgerDialog

        def _factory():
            dlg = MmpTransformLedgerDialog(self, pairs, activity_column=activity_column)
            dlg.setModal(False)
            dlg.setWindowModality(Qt.NonModal)
            return dlg

        def _on_reused(dlg):
            dlg.set_pairs(pairs, activity_column=activity_column)

        reuse_or_show_modeless_singleton(
            self,
            "_mmp_ledger_dialog",
            _factory,
            self._on_mmp_ledger_dialog_destroyed,
            on_reused_visible=_on_reused,
        )

    def _on_mmp_ledger_dialog_destroyed(self, *_args) -> None:
        self._mmp_ledger_dialog = None

    def _open_mmp_browser(self, pairs, *, activity_column: str) -> None:
        from ..mmp_browser import MmpBrowserDialog

        def _factory():
            dlg = MmpBrowserDialog(self, pairs, activity_column=activity_column)
            dlg.setModal(False)
            dlg.setWindowModality(Qt.NonModal)
            return dlg

        def _on_reused(dlg):
            dlg.set_pairs(pairs, activity_column=activity_column)

        reuse_or_show_modeless_singleton(
            self,
            "_mmp_browser_dialog",
            _factory,
            self._on_mmp_browser_dialog_destroyed,
            on_reused_visible=_on_reused,
        )

    def _on_mmp_browser_dialog_destroyed(self, *_args) -> None:
        self._mmp_browser_dialog = None
