# This file is part of MCToolkit.
# Copyright (C) 2026 Hunter Picard
#
# MCToolkit is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# MCToolkit is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with MCToolkit.  If not, see <https://www.gnu.org/licenses/>.

"""Tests for plot type inference from axis selections."""

from mctoolkit.ui.plot import (
    AXIS_NONE,
    PLOT_TYPE_HEATMAP,
    PLOT_TYPE_HISTOGRAM,
    PLOT_TYPE_LINE_2D,
    PLOT_TYPE_SCATTER,
    infer_plot_mode,
    normalize_axis_name,
    resolve_plot_mode,
)


def test_normalize_axis_name():
    assert normalize_axis_name(None) is None
    assert normalize_axis_name("") is None
    assert normalize_axis_name(AXIS_NONE) is None
    assert normalize_axis_name("  MW  ") == "MW"


def test_infer_plot_mode_requires_y_for_scatter():
    assert infer_plot_mode("MW", AXIS_NONE, AXIS_NONE) is None
    assert infer_plot_mode("MW", None, None) is None


def test_infer_plot_mode_2d():
    assert infer_plot_mode("MW", "LogP", AXIS_NONE) == "2D"
    assert infer_plot_mode("MW", "LogP", None) == "2D"


def test_infer_plot_mode_3d():
    assert infer_plot_mode("MW", "LogP", "TPSA") == "3D"


def test_infer_plot_mode_invalid():
    assert infer_plot_mode(None, "LogP", None) is None
    assert infer_plot_mode("MW", AXIS_NONE, "TPSA") is None
    assert infer_plot_mode(AXIS_NONE, "LogP", "TPSA") is None


def test_resolve_plot_mode_scatter_matches_infer():
    axes = ("MW", "LogP", AXIS_NONE)
    assert resolve_plot_mode(PLOT_TYPE_SCATTER, *axes) == infer_plot_mode(*axes)
    assert resolve_plot_mode(PLOT_TYPE_SCATTER, "MW", AXIS_NONE, AXIS_NONE) is None


def test_resolve_plot_mode_histogram():
    assert resolve_plot_mode(PLOT_TYPE_HISTOGRAM, "MW", AXIS_NONE, AXIS_NONE) == "Histogram"
    assert resolve_plot_mode(PLOT_TYPE_HISTOGRAM, "MW", "LogP", AXIS_NONE) == "Histogram"
    assert resolve_plot_mode(PLOT_TYPE_HISTOGRAM, AXIS_NONE, AXIS_NONE, AXIS_NONE) is None


def test_resolve_plot_mode_line_2d():
    assert resolve_plot_mode(PLOT_TYPE_LINE_2D, "MW", "LogP", AXIS_NONE) == "2D"
    assert resolve_plot_mode(PLOT_TYPE_LINE_2D, "MW", AXIS_NONE, AXIS_NONE) is None


def test_resolve_plot_mode_heatmap():
    assert resolve_plot_mode(PLOT_TYPE_HEATMAP, "MW", "LogP", "None") == "Heatmap"
