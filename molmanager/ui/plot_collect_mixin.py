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

"""Series collection helpers for :class:`PlotWidget`."""

from __future__ import annotations

from PySide6.QtWidgets import QMessageBox

from ..analysis.medchem_space import snapshot_scope_row_indices
from ..plotting.plot_series_collect import collect_histogram_values, collect_scatter_points


class PlotCollectMixin:
    """Gather scatter / histogram series from the linked table."""

    def _plot_source_row_indices(self):
        """Source-model rows for plotting (visible/filtered rows; optional selection-only).

        When every row is in scope, returns ``range(rowCount)`` instead of ``None`` so callers
        can iterate without allocating a full index list.
        """
        model = self.parent_app._table_model
        only_sel = None
        n_sel_now = len(self.parent_app._selected_logical_rows())
        if n_sel_now > 0 and self.only_selected_cb.isChecked():
            only_sel = list(self.parent_app._selected_logical_rows())
        visible = self.parent_app._visible_source_row_indices()
        rows = snapshot_scope_row_indices(
            model.rowCount(),
            only_selected_rows=only_sel,
            visible_row_indices=visible,
        )
        if rows is None:
            return range(model.rowCount())
        return rows

    def _collect_points(
        self,
    ) -> tuple[list[float], list[float], list[float], list[int], str, str, str | None]:
        mode = self._effective_plot_mode()
        if mode not in ("2D", "3D", "Heatmap"):
            return [], [], [], [], "", "", None

        xname = self._combo_axis_name(self.x_combo) or ""
        yname = self._combo_axis_name(self.y_combo) or ""
        if not xname or not yname:
            return [], [], [], [], "", "", None

        h_map = {h: i for i, h in enumerate(self.parent_app.headers)}
        xi = h_map.get(xname)
        yi = h_map.get(yname)
        if xi is None or yi is None:
            return [], [], [], [], xname, yname, None

        n_sel_now = (
            len(self.parent_app._selected_logical_rows()) if self.parent_app is not None else 0
        )
        only_sel = n_sel_now > 0 and self.only_selected_cb.isChecked()
        allowed = self.parent_app._selected_oids_set() if only_sel else None
        if only_sel and not allowed:
            QMessageBox.warning(
                self, "Plot", "“Selected Rows Only” is checked but nothing is selected."
            )
            return [], [], [], [], xname, yname, None

        is3d = mode == "3D"
        zname = self._combo_axis_name(self.z_combo) if is3d else None
        zi = h_map.get(zname) if is3d else None
        if is3d and zi is None:
            return [], [], [], [], xname, yname, zname

        xmin = self._parse_edit_float(self.xmin)
        xmax = self._parse_edit_float(self.xmax)
        ymin = self._parse_edit_float(self.ymin)
        ymax = self._parse_edit_float(self.ymax)
        zmin = self._parse_edit_float(self.zmin) if is3d else None
        zmax = self._parse_edit_float(self.zmax) if is3d else None

        fx, fy, fz, foids = collect_scatter_points(
            model=self.parent_app._table_model,
            row_indices=self._plot_source_row_indices(),
            x_col=xi,
            y_col=yi,
            z_col=zi if is3d else None,
            allowed_oids=allowed,
            xmin=xmin,
            xmax=xmax,
            ymin=ymin,
            ymax=ymax,
            zmin=zmin,
            zmax=zmax,
        )
        return fx, fy, fz, foids, xname, yname, zname

    def _collect_histogram(self) -> tuple[list[float], list[int], str]:
        """Values and oids for a single-column histogram."""
        xname = self._combo_axis_name(self.x_combo) or ""
        if not xname:
            return [], [], ""
        h_map = {h: i for i, h in enumerate(self.parent_app.headers)}
        xi = h_map.get(xname)
        if xi is None:
            return [], [], xname

        n_sel_now = (
            len(self.parent_app._selected_logical_rows()) if self.parent_app is not None else 0
        )
        only_sel = n_sel_now > 0 and self.only_selected_cb.isChecked()
        allowed = self.parent_app._selected_oids_set() if only_sel else None
        if only_sel and not allowed:
            QMessageBox.warning(
                self, "Plot", "“Selected Rows Only” is checked but nothing is selected."
            )
            return [], [], xname

        vals, oids = collect_histogram_values(
            model=self.parent_app._table_model,
            row_indices=self._plot_source_row_indices(),
            value_col=xi,
            allowed_oids=allowed,
            xmin=self._parse_edit_float(self.xmin),
            xmax=self._parse_edit_float(self.xmax),
        )
        return vals, oids, xname
