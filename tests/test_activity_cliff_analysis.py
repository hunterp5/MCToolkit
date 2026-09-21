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

"""Tests for activity-cliff metrics and figure helpers."""

from rdkit import Chem

from mctoolkit.analysis.activity_cliff_analysis import (
    build_activity_cliff_points,
    change_heavy_atom_count,
    fragment_tanimoto_distance,
)
from mctoolkit.analysis.mmp_analysis import find_matched_molecular_pairs
from mctoolkit.ui.activity_cliff_plot import build_activity_cliff_figure


def _rec(oid: int, smiles: str, activity: float):
    return oid, Chem.MolFromSmiles(smiles), activity


def test_change_heavy_atom_count_and_distance():
    ha = change_heavy_atom_count("O[*:1]", "CO[*:1]")
    assert ha >= 2
    dist = fragment_tanimoto_distance("O[*:1]", "CO[*:1]")
    assert 0.0 <= dist <= 1.0
    assert fragment_tanimoto_distance("O[*:1]", "O[*:1]") == 0.0


def test_build_activity_cliff_points_from_mmp():
    records = [
        _rec(1, "Oc1ccccc1", 1.0),
        _rec(2, "COc1ccccc1", 2.5),
        _rec(3, "CCOc1ccccc1", 3.0),
    ]
    pairs = find_matched_molecular_pairs(records, max_cuts=1)
    points = build_activity_cliff_points(pairs)
    assert len(points) == len(pairs)
    assert all(p.abs_delta >= 0 for p in points)
    assert all(p.change_heavy_atoms >= 0 for p in points)
    fig = build_activity_cliff_figure(points, activity_column="pIC50")
    assert len(fig.data) == 1
    assert len(fig.data[0].x) == len(points)
    fig2 = build_activity_cliff_figure(points, activity_column="pIC50", x_mode="frag_distance")
    assert len(fig2.data[0].x) == len(points)
