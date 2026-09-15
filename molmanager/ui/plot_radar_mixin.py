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

"""Radar spoke / entry helpers for :class:`PlotWidget`."""

from __future__ import annotations

from PyQt5.QtWidgets import QMessageBox

from ..plot_radar import SPOKE_NONE, resolve_entry_row_oid


class PlotRadarMixin:
    """Radar plot option wiring (spokes and entry OID filters)."""

    def _refresh_radar_spoke_columns(self) -> None:
        """Sync radar spoke dropdowns when table columns change."""
        if self.parent_app is None or not self.spoke_combos:
            return
        cols = self._numeric_column_names()
        previous = [c.currentText() for c in self.spoke_combos]
        for combo, prev in zip(self.spoke_combos, previous):
            combo.blockSignals(True)
            try:
                combo.clear()
                combo.addItem(SPOKE_NONE)
                for col in cols:
                    combo.addItem(col)
                idx = combo.findText(prev)
                combo.setCurrentIndex(idx if idx >= 0 else 0)
            finally:
                combo.blockSignals(False)

    def _selected_radar_spoke_columns(self) -> list[str]:
        cols: list[str] = []
        for combo in self.spoke_combos:
            text = combo.currentText()
            if text and text != SPOKE_NONE:
                cols.append(text)
        return cols

    def _on_radar_spoke_changed(self, spoke_index: int) -> None:
        combo = self.spoke_combos[spoke_index]
        chosen = combo.currentText()
        if chosen and chosen != SPOKE_NONE:
            for i, other in enumerate(self.spoke_combos):
                if i != spoke_index and other.currentText() == chosen:
                    combo.blockSignals(True)
                    try:
                        combo.setCurrentIndex(0)
                    finally:
                        combo.blockSignals(False)
                    QMessageBox.information(
                        self,
                        "Radar Plot",
                        f'Column "{chosen}" is already assigned to another spoke.',
                    )
                    return
        self._schedule_plot()

    def _selected_radar_entry_oids(self) -> tuple[list[int] | None, list[str]]:
        """Return (oids to plot, or None for all rows) and invalid ID strings entered."""
        if self.parent_app is None:
            return None, []
        model = self.parent_app._table_model
        oids: list[int] = []
        invalid: list[str] = []
        for edit in self.entry_edits:
            text = edit.text().strip()
            if not text:
                continue
            oid = resolve_entry_row_oid(
                text,
                model=model,
                row_for_oid=self.parent_app.logical_row_for_oid,
            )
            if oid is None:
                invalid.append(text)
                continue
            if oid not in oids:
                oids.append(oid)
        return (oids or None), invalid
