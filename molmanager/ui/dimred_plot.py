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

"""Build Plotly figures for PCA / t-SNE / UMAP / SOM result dialogs."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from plotly import graph_objects as go

from ..analysis.dimensionality_reduction import DimensionReductionResult
from ..plotting.plot_marker_color import (
    DEFAULT_PLOT_COLORSCALE,
    DEFAULT_SELECTED_MARKER_SIZE_PX,
    attach_marker_size_legend,
    scatter_marker_from_column_values,
)
from ..ui.plotly_html import finalize_plot_legend
from .dockable_plot import resolve_plot_title_text


def dimension_reduction_result_with_color(
    result: DimensionReductionResult,
    *,
    color_values: list[Any] | None,
    color_label: str | None,
) -> DimensionReductionResult:
    """Return a copy of ``result`` with updated color encoding and hover text."""
    hover: list[str] = []
    for i, oid in enumerate(result.oids):
        parts = [f"OID {oid}"]
        if color_label and color_values is not None and i < len(color_values):
            parts.append(f"{color_label}: {color_values[i]}")
        hover.append("<br>".join(parts))
    return replace(
        result,
        color_values=color_values,
        color_label=color_label,
        hover=hover,
    )


def build_dimension_reduction_figure(
    result: DimensionReductionResult,
    *,
    colorscale: str = DEFAULT_PLOT_COLORSCALE,
    color_min: float | None = None,
    color_max: float | None = None,
    size_values: list[Any] | None = None,
    size_label: str | None = None,
    size_min_px: float | None = None,
    size_max_px: float | None = None,
    plot_title: str = "",
    xaxis_title: str = "",
    yaxis_title: str = "",
) -> go.Figure:
    if result.method == "pca":
        x_label, y_label = "PC1", "PC2"
    elif result.method == "umap":
        x_label, y_label = "UMAP 1", "UMAP 2"
    elif result.method == "som":
        x_label, y_label = "SOM column", "SOM row"
    else:
        x_label, y_label = "t-SNE 1", "t-SNE 2"
    title = resolve_plot_title_text(plot_title, "")
    x_label = resolve_plot_title_text(xaxis_title, x_label)
    y_label = resolve_plot_title_text(yaxis_title, y_label)
    marker_kwargs: dict[str, Any] = {
        "color_label": result.color_label,
        "colorscale": colorscale,
        "color_min": color_min,
        "color_max": color_max,
        "size_values": size_values,
    }
    if size_min_px is not None:
        marker_kwargs["size_min_px"] = size_min_px
    if size_max_px is not None:
        marker_kwargs["size_max_px"] = size_max_px
    marker = scatter_marker_from_column_values(
        result.color_values,
        **marker_kwargs,
    )
    fig = go.Figure(
        data=[
            go.Scatter(
                x=result.x,
                y=result.y,
                mode="markers",
                customdata=[[int(oid)] for oid in result.oids],
                hoverinfo="none",
                marker=marker,
                showlegend=False,
                unselected={"marker": {"opacity": 0.35}},
                selected={
                    "marker": {
                        "size": DEFAULT_SELECTED_MARKER_SIZE_PX,
                        "color": "#d62828",
                        "opacity": 1.0,
                    }
                },
            )
        ]
    )
    fig.update_layout(
        title=title or None,
        xaxis_title=x_label,
        yaxis_title=y_label,
        template="plotly_white",
        dragmode="lasso",
        clickmode="event+select",
        showlegend=False,
        margin=dict(l=48, r=24, t=24 if not title else 48, b=48),
        meta={
            "molmanager_selection_traces": [0],
            "molmanager_hover_persist": False,
        },
    )
    attach_marker_size_legend(
        fig,
        size_label=size_label,
        size_values=size_values,
        size_min_px=float(size_min_px) if size_min_px is not None else 4.0,
        size_max_px=float(size_max_px) if size_max_px is not None else 16.0,
    )
    return finalize_plot_legend(fig)
