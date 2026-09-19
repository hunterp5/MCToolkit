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

"""Plot title / axis-title overrides and fit-formula annotations."""

from __future__ import annotations

from plotly import graph_objects as go


def apply_plotly_label_overrides(
    fig: go.Figure,
    *,
    title: str = "",
    x_title: str = "",
    y_title: str = "",
    z_title: str = "",
) -> None:
    """
    Apply optional user labels onto an existing figure.

    Empty strings leave the current layout values unchanged (typically column names).
    """
    title_s = (title or "").strip()
    xt = (x_title or "").strip()
    yt = (y_title or "").strip()
    zt = (z_title or "").strip()
    if not (title_s or xt or yt or zt):
        return

    kw: dict = {}
    if title_s:
        kw["title"] = {"text": title_s, "x": 0.5, "xanchor": "center"}
        cur_t = 20
        try:
            mt = fig.layout.margin.t if fig.layout.margin is not None else None
            if mt is not None:
                cur_t = int(mt)
        except Exception:
            cur_t = 20
        kw["margin_t"] = max(cur_t, 48)

    layout = fig.to_plotly_json().get("layout") or {}
    if layout.get("scene"):
        if xt:
            kw["scene_xaxis_title"] = xt
        if yt:
            kw["scene_yaxis_title"] = yt
        if zt:
            kw["scene_zaxis_title"] = zt
    else:
        if xt:
            kw["xaxis_title"] = xt
        if yt:
            kw["yaxis_title"] = yt

    if kw:
        fig.update_layout(**kw)


def add_fit_formula_annotation(fig: go.Figure, formula: str) -> None:
    """Draw the fit equation in the upper-left of the plot area."""
    text = (formula or "").strip()
    if not text:
        return
    fig.add_annotation(
        text=text,
        xref="paper",
        yref="paper",
        x=0.01,
        y=0.99,
        xanchor="left",
        yanchor="top",
        showarrow=False,
        align="left",
        bgcolor="rgba(255,255,255,0.88)",
        bordercolor="#b0b0b0",
        borderwidth=1,
        borderpad=4,
        font={"size": 11, "color": "#333"},
    )
