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

"""Qt WebChannel bridge from Plotly JS events to :class:`PlotWidget`."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Slot

if TYPE_CHECKING:
    from .plot import PlotWidget


class PlotBridge(QObject):
    """Bridge JS Plotly events back to Qt."""

    def __init__(self, plot_widget: PlotWidget) -> None:
        super().__init__(plot_widget)
        self._plot_widget = plot_widget

    @Slot(int, bool)
    def pointClicked(self, point_index: int, additive: bool = False) -> None:  # noqa: N802
        self._plot_widget._on_plot_point_clicked(int(point_index), additive=bool(additive))

    @Slot(str, bool)
    def pointsSelected(self, points_json: str, additive: bool = False) -> None:  # noqa: N802
        self._plot_widget._on_plot_points_selected(points_json, additive=bool(additive))

    @Slot(str, bool)
    def histogramPointsSelected(self, indices_json: str, additive: bool = False) -> None:  # noqa: N802
        self._plot_widget._on_histogram_points_selected(indices_json, additive=bool(additive))

    @Slot(int)
    def histogramBinClicked(self, bin_index: int) -> None:  # noqa: N802
        self._plot_widget._on_histogram_bin_clicked(int(bin_index))

    @Slot(float, float)
    def heatmapCellClicked(self, x_value: float, y_value: float) -> None:  # noqa: N802
        self._plot_widget._on_heatmap_cell_clicked(float(x_value), float(y_value))

    @Slot(int)
    def radarTraceClicked(self, trace_index: int) -> None:  # noqa: N802
        self._plot_widget._on_radar_trace_clicked(int(trace_index))

    @Slot(int, result=str)
    def hoverCardJson(self, point_index: int) -> str:  # noqa: N802
        return self._plot_widget._hover_card_json_for_point(int(point_index))

    @Slot(str, result=str)
    def hoverCardsJson(self, indices_json: str) -> str:  # noqa: N802
        return self._plot_widget._hover_card_json_for_points(indices_json)
