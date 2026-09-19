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

"""Qt-free table statistics used by Data → Table → Statistics."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from molmanager.analysis.table_statistics import (
    CURVE_POLYNOMIAL,
    OUTLIER_IQR,
    TEST_ONE_SAMPLE_T,
    TEST_SHAPIRO,
    analyze_outlier_column,
    fit_xy_curve,
    format_numeric_summary,
    format_outlier_column_report,
    outlier_mask_iqr,
    outlier_mask_modified_z,
    outlier_mask_zscore,
    parse_percentiles,
    r2_rmse,
    run_hypothesis_test,
)

_STATS_SRC = Path(__file__).resolve().parents[1] / "molmanager" / "analysis" / "table_statistics.py"


def test_table_statistics_source_does_not_import_qt() -> None:
    text = _STATS_SRC.read_text(encoding="utf-8")
    assert "PyQt5" not in text
    assert "PySide6" not in text
    assert "QtWidgets" not in text
    assert "QDialog" not in text


def test_outlier_masks_flag_the_far_point() -> None:
    v = np.array([1.0, 2.0, 3.0, 4.0, 1000.0])
    assert outlier_mask_iqr(v, k=1.5).sum() >= 1
    assert not outlier_mask_iqr(np.array([1.0, 1.0, 1.0, 1.0]), k=1.5).any()
    vt = np.array([1.0, 2.0, 3.0, 4.0, 50.0])
    assert outlier_mask_zscore(vt, z=1.5).any()
    assert outlier_mask_modified_z(vt, threshold=2.0).any()


def test_parse_percentiles_accepts_percent_or_fraction() -> None:
    assert parse_percentiles("5, 50, 95") == [0.05, 0.5, 0.95]
    assert parse_percentiles("0.25, 0.75") == [0.25, 0.75]


def test_parse_percentiles_rejects_endpoints() -> None:
    try:
        parse_percentiles("0, 50")
    except ValueError as exc:
        assert "out of" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_r2_rmse_perfect_line() -> None:
    y = np.array([1.0, 2.0, 3.0])
    r2, rmse = r2_rmse(y, y)
    assert r2 == 1.0
    assert rmse == 0.0


def test_analyze_outlier_column_iqr_report() -> None:
    v = np.array([1.0, 2.0, 3.0, 4.0, 100.0])
    result = analyze_outlier_column(v, column="MW", method=OUTLIER_IQR, k=1.5)
    header = "\n".join(result.header_lines)
    assert "Column: MW" in header
    assert "Outliers flagged: 1" in header
    assert result.indices == (4,)
    text = format_outlier_column_report(result, row_label=lambda i: f"row={i}", values=v)
    assert "row=4" in text
    assert "100" in text


def test_format_numeric_summary_counts_rows() -> None:
    raw = pd.DataFrame({"ID_HIDDEN": ["1", "2"], "MW": ["10", "20"]})
    num = pd.DataFrame({"MW": [10.0, 20.0]})
    text = format_numeric_summary(raw, num)
    assert "Rows: 2" in text
    assert "Numeric columns" in text
    assert "MW" in text


def test_polynomial_fit_recovers_a_line() -> None:
    x = np.array([0.0, 1.0, 2.0, 3.0])
    y = 2.0 * x + 1.0
    result = fit_xy_curve(x, y, model=CURVE_POLYNOMIAL, x_name="x", y_name="y", degree=1)
    assert result.ok
    assert "R²: 1" in result.text
    assert "2*(x)" in result.text
    assert "Polynomial degree: 1" in result.text


def test_fit_rejects_too_few_pairs() -> None:
    result = fit_xy_curve(
        np.array([1.0]),
        np.array([2.0]),
        model=CURVE_POLYNOMIAL,
        x_name="x",
        y_name="y",
    )
    assert not result.ok
    assert "at least two" in result.text


def test_shapiro_and_one_sample_t() -> None:
    rng = np.random.default_rng(0)
    a = rng.normal(loc=0.0, scale=1.0, size=40)
    shapiro = run_hypothesis_test(a, None, test=TEST_SHAPIRO, a_name="MW")
    assert any("Shapiro-Wilk" in line for line in shapiro.lines)
    ttest = run_hypothesis_test(a, None, test=TEST_ONE_SAMPLE_T, a_name="MW", hypothesized_mean=0.0)
    assert any(line.startswith("t =") for line in ttest.lines)
