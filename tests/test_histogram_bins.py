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

"""Tests for histogram bin edge computation and OID lookup."""

from mctoolkit.ui.plot import (
    compute_histogram_bin_edges,
    oids_at_histogram_point_indices,
    oids_in_histogram_bin,
)


def test_compute_histogram_bin_edges_fixed_width():
    vals = [0.5, 1.2, 1.8, 2.4, 2.9]
    edges, width = compute_histogram_bin_edges(vals, bin_width=1.0)
    assert width == 1.0
    assert len(edges) >= 3
    assert edges[0] <= min(vals)
    assert edges[-1] >= max(vals)


def test_oids_at_histogram_point_indices():
    oids = [10, 20, 30, 40, 50]
    assert oids_at_histogram_point_indices(oids, [0, 1, 0, 99, -1]) == [10, 20]
    assert oids_at_histogram_point_indices(oids, []) == []


def test_oids_in_histogram_bin():
    vals = [0.2, 0.8, 1.1, 1.9, 2.5]
    oids = [10, 20, 30, 40, 50]
    edges, _ = compute_histogram_bin_edges(vals, bin_width=1.0)
    bin0 = oids_in_histogram_bin(vals, oids, edges, 0)
    assert 10 in bin0
    assert 20 in bin0
    assert 50 not in bin0
