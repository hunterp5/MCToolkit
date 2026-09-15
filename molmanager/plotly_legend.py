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

"""Plotly legend cleanup helpers (no Qt)."""

from __future__ import annotations

import re

from plotly import graph_objects as go

_UTILITY_LEGEND_NAMES = frozenset(
    {
        "fit",
        "points",
        "selected",
        "compounds",
        "compound",
        "data",
        "values",
    }
)
_TRACE_LEGEND_RE = re.compile(r"^trace\s*\d+$", re.I)
_FIT_LEGEND_RE = re.compile(r"^fit\b", re.I)


def legend_name_is_utility(name: str | None) -> bool:
    """True when a trace name should not appear in the Plotly legend."""
    text = ("" if name is None else str(name)).strip()
    if not text:
        return True
    low = text.lower()
    if low in _UTILITY_LEGEND_NAMES:
        return True
    if _TRACE_LEGEND_RE.match(text):
        return True
    if _FIT_LEGEND_RE.match(text):
        return True
    return False


def suppress_utility_legend_entries(fig: go.Figure) -> None:
    """Hide generic / internal trace names from the Plotly legend (Fit, Trace 0, Compounds, …)."""
    any_visible = False
    for tr in fig.data:
        # Size-scale legend entries must stay visible.
        if getattr(tr, "legendgroup", None) == "molmanager_size":
            tr.showlegend = True
            any_visible = True
            continue
        if legend_name_is_utility(getattr(tr, "name", None)):
            tr.showlegend = False
        elif getattr(tr, "showlegend", True) is not False:
            any_visible = True
    if not any_visible:
        fig.update_layout(showlegend=False)


def finalize_plot_legend(fig: go.Figure) -> go.Figure:
    """Apply legend cleanup (call from every figure builder before display)."""
    suppress_utility_legend_entries(fig)
    return fig
