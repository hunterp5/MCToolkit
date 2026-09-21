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

"""Tests for multi-parameter optimization desirability scoring."""

from __future__ import annotations

import math

import pytest

from mctoolkit.analysis.mpo_scoring import (
    DesirabilitySpec,
    combine_desirabilities,
    evaluate_desirability,
    format_score,
    gaussian_desirability,
    linear_desirability,
    score_mpo_row,
    score_mpo_table,
    step_desirability,
)


def test_linear_maximize_and_minimize():
    assert linear_desirability(0.0, direction="maximize", low=0.0, high=10.0) == 0.0
    assert linear_desirability(10.0, direction="maximize", low=0.0, high=10.0) == 1.0
    assert linear_desirability(5.0, direction="maximize", low=0.0, high=10.0) == pytest.approx(0.5)

    assert linear_desirability(0.0, direction="minimize", low=0.0, high=10.0) == 1.0
    assert linear_desirability(10.0, direction="minimize", low=0.0, high=10.0) == 0.0
    assert linear_desirability(5.0, direction="minimize", low=0.0, high=10.0) == pytest.approx(0.5)


def test_linear_target():
    d = linear_desirability(5.0, direction="target", low=0.0, high=10.0, target=5.0)
    assert d == pytest.approx(1.0)
    assert linear_desirability(-1.0, direction="target", low=0.0, high=10.0, target=5.0) == 0.0
    assert linear_desirability(
        2.5, direction="target", low=0.0, high=10.0, target=5.0
    ) == pytest.approx(0.5)


def test_gaussian_peak_and_width():
    assert gaussian_desirability(0.0, center=0.0, sigma=1.0) == pytest.approx(1.0)
    d = gaussian_desirability(1.0, center=0.0, sigma=1.0)
    assert d == pytest.approx(math.exp(-0.5))
    assert gaussian_desirability(10.0, center=0.0, sigma=1.0) < 1e-6


def test_step_functions():
    assert step_desirability(5.0, direction="maximize", low=0.0, high=3.0) == 1.0
    assert step_desirability(2.0, direction="maximize", low=0.0, high=3.0) == 0.0
    assert step_desirability(1.0, direction="minimize", low=2.0, high=9.0) == 1.0
    assert step_desirability(3.0, direction="minimize", low=2.0, high=9.0) == 0.0
    assert step_desirability(5.0, direction="target", low=2.0, high=8.0) == 1.0
    assert step_desirability(9.0, direction="target", low=2.0, high=8.0) == 0.0


def test_combine_geometric_and_arithmetic():
    assert combine_desirabilities([1.0, 1.0], method="geometric") == pytest.approx(1.0)
    assert combine_desirabilities([1.0, 0.0], method="geometric") == 0.0
    assert combine_desirabilities([0.25, 1.0], method="geometric") == pytest.approx(0.5)
    assert combine_desirabilities(
        [0.0, 1.0], weights=[1.0, 1.0], method="arithmetic"
    ) == pytest.approx(0.5)
    assert math.isnan(combine_desirabilities([0.5, float("nan")], method="geometric"))


def test_score_mpo_row_end_to_end():
    specs = [
        DesirabilitySpec(
            column="MW", kind="linear", direction="minimize", low=300.0, high=500.0, weight=1.0
        ),
        DesirabilitySpec(column="LogP", kind="gaussian", center=2.0, sigma=1.0, weight=1.0),
        DesirabilitySpec(
            column="TPSA", kind="step", direction="target", low=20.0, high=90.0, weight=1.0
        ),
    ]
    overall, per = score_mpo_row(
        {"MW": 300.0, "LogP": 2.0, "TPSA": 50.0}, specs, method="geometric"
    )
    assert overall == pytest.approx(1.0)
    assert per["MW"] == pytest.approx(1.0)
    assert per["LogP"] == pytest.approx(1.0)
    assert per["TPSA"] == pytest.approx(1.0)

    overall2, _ = score_mpo_row({"MW": None, "LogP": 2.0, "TPSA": 50.0}, specs)
    assert overall2 is None

    assert evaluate_desirability(2.0, specs[1]) == pytest.approx(1.0)
    assert format_score(0.5, decimals=2) == "0.50"
    assert format_score(None) == ""


def test_numeric_columns_and_bounds_from_dict_and_tuple() -> None:
    from types import SimpleNamespace

    from mctoolkit.ui.dialogs.mpo_scoring import _numeric_columns_and_bounds

    parent = SimpleNamespace(
        global_bounds={"MW": {"min": 1, "max": 10}, "LogP": (0, 5), "empty": {"min": 3, "max": 3}}
    )
    cols, bounds = _numeric_columns_and_bounds(parent)
    assert cols == ["LogP", "MW", "empty"]
    assert bounds["MW"] == (1.0, 10.0)
    assert bounds["LogP"] == (0.0, 5.0)
    assert bounds["empty"] == (3.0, 4.0)


def test_mpo_dialog_constructs_without_parent(qapp) -> None:  # noqa: ARG001
    from mctoolkit.ui.dialogs.mpo_scoring import MPOScoringDialog

    dlg = MPOScoringDialog(None)
    assert dlg.out_edit.text() == "MPO_Score"
    assert dlg.add_btn.isEnabled() is False
    dlg.close()


def test_score_mpo_table_from_column_texts():
    specs = [DesirabilitySpec(column="MW", kind="linear", direction="maximize", low=0.0, high=10.0)]
    rows = score_mpo_table(
        [1, 2],
        {"MW": ["0", "10"]},
        specs,
        output_column="MPO_Score",
    )
    assert rows[0] == (1, {"MPO_Score": format_score(0.0)})
    assert rows[1] == (2, {"MPO_Score": format_score(1.0)})
