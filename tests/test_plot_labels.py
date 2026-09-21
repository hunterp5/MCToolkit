# This file is part of mctoolkit.
# Copyright (C) 2026 Hunter Picard
#
# mctoolkit is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# mctoolkit is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with mctoolkit.  If not, see <https://www.gnu.org/licenses/>.

"""Tests for plot title / axis overrides and fit-formula annotations."""

from __future__ import annotations

from plotly import graph_objects as go

from mctoolkit.plotting.plot_labels import add_fit_formula_annotation, apply_plotly_label_overrides


def test_apply_plotly_label_overrides_2d() -> None:
    fig = go.Figure(data=[go.Scatter(x=[1, 2], y=[3, 4])])
    fig.update_layout(xaxis_title="MW", yaxis_title="LogP", margin={"t": 20})
    apply_plotly_label_overrides(
        fig,
        title="My Plot",
        x_title="Molecular weight",
        y_title="cLogP",
    )
    assert fig.layout.title.text == "My Plot"
    assert fig.layout.xaxis.title.text == "Molecular weight"
    assert fig.layout.yaxis.title.text == "cLogP"
    assert int(fig.layout.margin.t) >= 48


def test_apply_plotly_label_overrides_empty_keeps_defaults() -> None:
    fig = go.Figure(data=[go.Scatter(x=[1], y=[2])])
    fig.update_layout(xaxis_title="Xcol", yaxis_title="Ycol")
    apply_plotly_label_overrides(fig, title="", x_title="", y_title="")
    assert fig.layout.xaxis.title.text == "Xcol"
    assert fig.layout.yaxis.title.text == "Ycol"


def test_apply_plotly_label_overrides_3d_scene() -> None:
    fig = go.Figure(data=[go.Scatter3d(x=[1], y=[2], z=[3], mode="markers")])
    fig.update_layout(
        scene={
            "xaxis": {"title": "X"},
            "yaxis": {"title": "Y"},
            "zaxis": {"title": "Z"},
        }
    )
    apply_plotly_label_overrides(
        fig,
        x_title="Dim1",
        y_title="Dim2",
        z_title="Dim3",
    )
    assert fig.layout.scene.xaxis.title.text == "Dim1"
    assert fig.layout.scene.yaxis.title.text == "Dim2"
    assert fig.layout.scene.zaxis.title.text == "Dim3"


def test_add_fit_formula_annotation() -> None:
    fig = go.Figure(data=[go.Scatter(x=[0, 1], y=[0, 1])])
    add_fit_formula_annotation(fig, "y = 1.0x + 0.0")
    assert fig.layout.annotations
    assert "y = 1.0x" in fig.layout.annotations[0].text
