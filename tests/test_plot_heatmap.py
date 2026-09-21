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

"""Tests for 2D heatmap binning."""

from mctoolkit.plotting.plot_heatmap import (
    binned_count_matrix,
    oids_in_heatmap_cell,
    summarize_heatmap,
)
from mctoolkit.ui.plot import compute_histogram_bin_edges, resolve_plot_mode, PLOT_TYPE_HEATMAP


def test_binned_count_matrix():
    x = [0.5, 1.5, 1.5, 2.5]
    y = [1.0, 1.0, 2.0, 2.0]
    x_edges = [0.0, 1.0, 2.0, 3.0]
    y_edges = [0.5, 1.5, 2.5]
    z, xc, yc = binned_count_matrix(x, y, x_edges, y_edges)
    assert len(yc) == 2
    assert len(xc) == 3
    assert sum(sum(row) for row in z) == 4.0


def test_resolve_plot_mode_heatmap():
    assert resolve_plot_mode(PLOT_TYPE_HEATMAP, "MW", "LogP", "None") == "Heatmap"
    assert resolve_plot_mode(PLOT_TYPE_HEATMAP, "MW", "None", "None") is None


def test_oids_in_heatmap_cell():
    x = [0.5, 1.5, 1.5, 2.5]
    y = [1.0, 1.0, 2.0, 2.0]
    oids = [10, 20, 30, 40]
    x_edges = [0.0, 1.0, 2.0, 3.0]
    y_edges = [0.5, 1.5, 2.5]
    hit = oids_in_heatmap_cell(x, y, oids, x_edges, y_edges, 1.5, 1.0)
    assert set(hit) == {20}
    assert 40 not in hit


def test_summarize_heatmap():
    x_edges, _ = compute_histogram_bin_edges([1.0, 2.0, 3.0], bin_width=1.0)
    y_edges, _ = compute_histogram_bin_edges([4.0, 5.0, 6.0], bin_width=1.0)
    z, _, _ = binned_count_matrix([1.0, 2.0], [4.0, 5.0], x_edges, y_edges)
    lines = summarize_heatmap(
        [1.0, 2.0],
        [4.0, 5.0],
        x_label="X",
        y_label="Y",
        x_edges=x_edges,
        y_edges=y_edges,
        counts=z,
    )
    assert any("bins" in line for line in lines)
