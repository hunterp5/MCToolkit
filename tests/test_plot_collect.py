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

"""Unit tests for plot_collect helpers."""

from __future__ import annotations

from molmanager.plot_collect import (
    collect_histogram_values,
    collect_scatter_points,
    plotly_axis_range,
)
from molmanager.ui.compound_table_model import CompoundTableModel


def _model_with_rows() -> CompoundTableModel:
    m = CompoundTableModel(["ID_HIDDEN", "Structure", "X", "Y", "Z"])
    m.append_rows_batch(
        [
            (0, {"X": "1", "Y": "10", "Z": "100"}),
            (1, {"X": "2", "Y": "20", "Z": "200"}),
            (2, {"X": "3", "Y": "30", "Z": ""}),
            (3, {"X": "50", "Y": "40", "Z": "400"}),
        ]
    )
    return m


def test_collect_scatter_points_filters_range_and_allowed():
    m = _model_with_rows()
    xs, ys, zs, oids = collect_scatter_points(
        model=m,
        row_indices=range(m.rowCount()),
        x_col=2,
        y_col=3,
        allowed_oids={0, 1, 2},
        xmax=2.5,
    )
    assert oids == [0, 1]
    assert xs == [1.0, 2.0]
    assert ys == [10.0, 20.0]
    assert zs == []


def test_collect_scatter_points_3d_skips_missing_z():
    m = _model_with_rows()
    xs, ys, zs, oids = collect_scatter_points(
        model=m,
        row_indices=range(m.rowCount()),
        x_col=2,
        y_col=3,
        z_col=4,
    )
    assert oids == [0, 1, 3]
    assert zs == [100.0, 200.0, 400.0]
    assert len(xs) == 3


def test_collect_histogram_values():
    m = _model_with_rows()
    vals, oids = collect_histogram_values(
        model=m,
        row_indices=range(m.rowCount()),
        value_col=2,
        xmin=2,
        xmax=40,
    )
    assert oids == [1, 2]
    assert vals == [2.0, 3.0]


def test_plotly_axis_range():
    assert plotly_axis_range(None, None, [1.0, 2.0]) == {}
    assert plotly_axis_range(0.0, 5.0, []) == {"range": [0.0, 5.0], "autorange": False}
    assert plotly_axis_range(5.0, 1.0, [])["range"] == [1.0, 5.0]
