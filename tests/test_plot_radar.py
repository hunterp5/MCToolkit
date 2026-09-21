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

"""Tests for radar (spider) plot data and figure building."""

import pytest

from mctoolkit.plotting.plot_radar import (
    MAX_RADAR_DISPLAY_ENTRIES,
    MAX_RADAR_VARIABLES,
    MIN_RADAR_VARIABLES,
    SPOKE_NONE,
    apply_radar_normalization,
    build_radar_figure,
    collect_radar_rows,
    compute_radar_normalization_bounds,
    filter_radar_rows_by_oids,
    normalize_radar_rows,
    resolve_entry_row_oid,
)
from mctoolkit.ui.compound_table_model import CompoundTableModel
from mctoolkit.ui.plot import PLOT_TYPE_CHOICES


@pytest.fixture()
def model(qapp):  # noqa: ARG001
    return CompoundTableModel(["ID_HIDDEN", "Structure", "SMILES", "MW"])


def test_plotter_includes_radar_type():
    labels = [label for label, _ in PLOT_TYPE_CHOICES]
    assert "Radar" in labels


def test_normalize_radar_rows_scales_to_unit_interval():
    rows = [[1.0, 10.0], [3.0, 30.0]]
    norm, mins, maxs = normalize_radar_rows(rows)
    assert mins == [1.0, 10.0]
    assert maxs == [3.0, 30.0]
    assert norm[0] == [0.0, 0.0]
    assert norm[1] == [1.0, 1.0]


def test_collect_radar_rows_skips_incomplete_rows(model):
    model.append_row(10, {"SMILES": "CC", "MW": "30.07"})
    model.append_row(11, {"SMILES": "CCC", "MW": ""})
    headers = list(model._headers)
    oids, rows = collect_radar_rows(
        model,
        headers,
        ["MW"],
        allowed_oids=None,
    )
    assert oids == [10]
    assert rows == [[30.07]]


def test_build_radar_figure_one_trace_per_row():
    columns = ["A", "B", "C"]
    oids = [1, 2]
    rows = [[1.0, 2.0, 3.0], [2.0, 4.0, 6.0]]
    fig = build_radar_figure(columns, oids, rows)
    assert len(fig.data) == 2
    assert fig.data[0].type == "scatterpolar"
    assert len(fig.data[0].r) == len(columns) + 1


def test_apply_radar_normalization_uses_scope_bounds(model):
    scope_rows = [[1.0, 10.0], [5.0, 50.0]]
    mins, maxs = compute_radar_normalization_bounds(scope_rows)
    subset = [[1.0, 10.0]]
    norm = apply_radar_normalization(subset, mins, maxs)
    assert norm == [[0.0, 0.0]]


def test_resolve_entry_row_oid_by_oid_or_row_number(model):
    model.append_row(42, {"SMILES": "CC", "MW": "30"})
    model.append_row(99, {"SMILES": "CCC", "MW": "40"})
    assert (
        resolve_entry_row_oid("42", model=model, row_for_oid=lambda o: model.logical_row_for_oid(o))
        == 42
    )
    assert (
        resolve_entry_row_oid("2", model=model, row_for_oid=lambda o: model.logical_row_for_oid(o))
        == 99
    )
    assert resolve_entry_row_oid("", model=model, row_for_oid=lambda o: -1) is None


def test_build_radar_figure_with_external_norm_bounds():
    rows = [[1.0, 10.0], [5.0, 50.0]]
    mins, maxs = compute_radar_normalization_bounds(rows)
    fig = build_radar_figure(["A", "B"], [1], [[1.0, 10.0]], norm_mins=mins, norm_maxs=maxs)
    assert fig.data[0].r[0] == 0.0


def test_filter_radar_rows_by_oids_preserves_order():
    oids = [10, 20, 30]
    rows = [[1.0], [2.0], [3.0]]
    out_oids, out_rows = filter_radar_rows_by_oids(oids, rows, [30, 10])
    assert out_oids == [30, 10]
    assert out_rows == [[3.0], [1.0]]


def test_radar_variable_limits():
    assert MIN_RADAR_VARIABLES == 2
    assert MAX_RADAR_VARIABLES == 6
    assert MAX_RADAR_DISPLAY_ENTRIES == 6
    assert SPOKE_NONE == "(none)"
