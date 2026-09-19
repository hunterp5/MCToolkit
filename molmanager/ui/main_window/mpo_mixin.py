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

"""MPO Scoring tool window (Data menu)."""

from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QMessageBox

from ...chem.molecule_conversion import safe_float


class MpoMixin:
    def open_mpo_scoring_dialog(self) -> None:
        if not self.headers or self._table_model.rowCount() == 0:
            QMessageBox.information(
                self,
                "MPO Scoring",
                "Open a file or add rows with numeric property columns first.",
            )
            return
        if not getattr(self, "global_bounds", None):
            try:
                self.calculate_global_bounds()
            except Exception:
                pass
        if not getattr(self, "global_bounds", None):
            QMessageBox.information(
                self,
                "MPO Scoring",
                "No numeric columns are available yet. Compute descriptors or import numeric data first.",
            )
            return
        from ..dialogs.mpo_scoring import MPOScoringDialog
        from ..singleton_modeless_dialog import reuse_or_show_modeless_singleton

        def _factory():
            d = MPOScoringDialog(self)
            self._prepare_tool_dialog(d)
            d.setAttribute(Qt.WA_DeleteOnClose, True)
            d.accepted.connect(lambda *_, dlg=d: self._on_mpo_scoring_dialog_accepted(dlg))
            return d

        reuse_or_show_modeless_singleton(
            self,
            "_mpo_scoring_dialog",
            _factory,
            on_reused_visible=lambda dlg: self._sync_dialog_only_selected_scope(dlg),
        )

    def _on_mpo_scoring_dialog_accepted(self, d) -> None:
        from ...analysis.mpo_scoring import format_score, score_mpo_row

        try:
            p = d.params()
        except Exception as exc:
            QMessageBox.warning(self, "MPO Scoring", str(exc))
            return
        if not p.specs:
            QMessageBox.information(self, "MPO Scoring", "Add at least one property criterion.")
            return
        only_selected = d.only_selected_rows()
        allowed = self._selected_oids_set() if only_selected else None
        if self._abort_if_only_selected_but_empty(only_selected, allowed, "MPO Scoring"):
            return
        oids = self._all_oids_in_table_order()
        if allowed is not None:
            oids = [o for o in oids if o in allowed]
        if not oids:
            QMessageBox.information(self, "MPO Scoring", "No rows to process for this scope.")
            return

        cols = [s.column for s in p.specs]
        missing = [c for c in cols if c not in self.headers]
        if missing:
            QMessageBox.warning(
                self,
                "MPO Scoring",
                "These columns are no longer in the table:\n" + ", ".join(missing),
            )
            return

        out_cols = [p.output_column]
        if p.write_individual:
            for s in p.specs:
                out_cols.append(f"MPO_d_{s.column}")

        rows: list[tuple[int, dict[str, str]]] = []
        for oid in oids:
            r = self.logical_row_for_oid(int(oid))
            if r < 0:
                continue
            values: dict[str, float | None] = {}
            for col in cols:
                raw = self._table_model.backing_value_for_row_header(r, col)
                values[col] = safe_float(raw)
            overall, per = score_mpo_row(values, list(p.specs), method=p.combine)
            cell: dict[str, str] = {
                p.output_column: format_score(overall, decimals=p.decimals),
            }
            if p.write_individual:
                for s in p.specs:
                    cell[f"MPO_d_{s.column}"] = format_score(per.get(s.column), decimals=p.decimals)
            rows.append((int(oid), cell))

        if not rows:
            QMessageBox.information(self, "MPO Scoring", "No rows could be scored.")
            return
        self.on_calc_finished(rows, out_cols, progress_label="MPO Scoring")
        self.status_label.setText(
            f'MPO Scoring: wrote "{p.output_column}" for {len(rows)} row(s) '
            f"({len(p.specs)} criteri{'on' if len(p.specs) == 1 else 'a'})."
        )
