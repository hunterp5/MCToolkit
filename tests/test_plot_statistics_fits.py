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

"""Tests for Plotter statistics and curve fits."""

import numpy as np

from molmanager.plotting.plot_statistics_fits import (
    FIT_GAUSSIAN,
    FIT_LINEAR,
    FIT_LOGNORMAL,
    FIT_TRUNCATED_GAUSSIAN,
    fit_histogram_curve,
    fit_xy_curve,
    summarize_univariate,
    summarize_xy,
)


def test_summarize_xy_includes_correlation():
    lines = summarize_xy([1.0, 2.0, 3.0, 4.0], [2.0, 4.0, 6.0, 8.0], x_label="X", y_label="Y")
    assert any("Pearson" in line for line in lines)


def test_linear_fit_perfect_line():
    x = [0.0, 1.0, 2.0, 3.0]
    y = [1.0, 2.0, 3.0, 4.0]
    result = fit_xy_curve(x, y, FIT_LINEAR)
    assert result is not None
    xs, ys, name = result
    assert len(xs) == 100
    assert abs(ys[0] - 1.0) < 0.05
    assert "Fit:" in name


def test_univariate_summary():
    lines = summarize_univariate([1.0, 2.0, 3.0, 100.0], label="MW")
    assert lines[0].startswith("MW")
    assert any("mean" in line for line in lines)


def test_histogram_gaussian_fit():
    rng = np.random.default_rng(0)
    vals = rng.normal(5.0, 1.0, size=200).tolist()
    edges = np.linspace(1.0, 9.0, 9).tolist()
    result = fit_histogram_curve(vals, edges, FIT_GAUSSIAN, bin_width=1.0)
    assert result is not None
    xs, ys, name = result
    assert len(xs) >= 2
    assert max(ys) > 0
    assert "Normal" in name


def test_histogram_linear_fit_bin_counts():
    edges = [0.0, 1.0, 2.0, 3.0, 4.0]
    vals = [0.5] * 3 + [1.5] * 5 + [2.5] * 2 + [3.5] * 4
    result = fit_histogram_curve(vals, edges, FIT_LINEAR, bin_width=1.0)
    assert result is not None
    assert len(result[0]) >= 2


def test_truncated_gaussian_lower_bound():
    rng = np.random.default_rng(1)
    vals = rng.normal(6.0, 0.8, size=150)
    vals = vals[vals >= 4.0]
    edges = np.linspace(3.0, 9.0, 13).tolist()
    result = fit_histogram_curve(
        vals.tolist(),
        edges,
        FIT_TRUNCATED_GAUSSIAN,
        bin_width=0.5,
        trunc_lower=4.0,
    )
    assert result is not None
    assert "Truncated Normal" in result[2]
    assert "lower" in result[2]


def test_histogram_lognormal_fit():
    rng = np.random.default_rng(3)
    vals = rng.lognormal(mean=1.0, sigma=0.35, size=200).tolist()
    edges = np.linspace(0.0, 8.0, 17).tolist()
    result = fit_histogram_curve(vals, edges, FIT_LOGNORMAL, bin_width=0.5)
    assert result is not None
    xs, ys, name = result
    assert len(xs) >= 2
    assert max(ys) > 0
    assert "LogNormal" in name


def test_lognormal_requires_positive_values():
    edges = [0.0, 1.0, 2.0, 3.0]
    vals = [-1.0, 0.0, 0.0, 1.0]
    assert fit_histogram_curve(vals, edges, FIT_LOGNORMAL, bin_width=1.0) is None


def test_truncated_gaussian_upper_bound():
    rng = np.random.default_rng(2)
    vals = rng.normal(3.0, 0.5, size=120)
    vals = vals[vals <= 4.0]
    edges = np.linspace(1.0, 5.0, 9).tolist()
    result = fit_histogram_curve(
        vals.tolist(),
        edges,
        FIT_TRUNCATED_GAUSSIAN,
        bin_width=0.5,
        trunc_upper=4.0,
    )
    assert result is not None
    assert "upper" in result[2]
