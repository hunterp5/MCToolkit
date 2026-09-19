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

"""Numeric summaries, outlier flags, curve fits, and hypothesis tests (no Qt)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
import pandas as pd

OUTLIER_IQR = "iqr"
OUTLIER_ZSCORE = "zscore"
OUTLIER_MODIFIED_Z = "modified_z"
OUTLIER_METHODS = (OUTLIER_IQR, OUTLIER_ZSCORE, OUTLIER_MODIFIED_Z)

CURVE_POLYNOMIAL = "polynomial"
CURVE_EXPONENTIAL = "exponential"
CURVE_LOGX = "logx"
CURVE_POWER = "power"
CURVE_MODELS = (CURVE_POLYNOMIAL, CURVE_EXPONENTIAL, CURVE_LOGX, CURVE_POWER)

TEST_PAIRED_T = "paired_t"
TEST_WELCH_T = "welch_t"
TEST_MANN_WHITNEY = "mann_whitney"
TEST_ONE_SAMPLE_T = "one_sample_t"
TEST_SHAPIRO = "shapiro"
HYPOTHESIS_TESTS = (
    TEST_PAIRED_T,
    TEST_WELCH_T,
    TEST_MANN_WHITNEY,
    TEST_ONE_SAMPLE_T,
    TEST_SHAPIRO,
)


@dataclass(frozen=True)
class OutlierColumnResult:
    column: str
    header_lines: tuple[str, ...]
    indices: tuple[int, ...]
    values: tuple[float, ...]


@dataclass(frozen=True)
class CurveFitResult:
    text: str
    ok: bool = True


@dataclass(frozen=True)
class HypothesisTestResult:
    lines: tuple[str, ...]


def r2_rmse(y: np.ndarray, y_hat: np.ndarray) -> tuple[float, float]:
    y = np.asarray(y, dtype=float)
    y_hat = np.asarray(y_hat, dtype=float)
    n = len(y)
    if n < 1:
        return float("nan"), float("nan")
    ss_res = float(np.sum((y - y_hat) ** 2))
    y_mean = float(np.mean(y))
    ss_tot = float(np.sum((y - y_mean) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else float("nan")
    rmse = float(np.sqrt(ss_res / n))
    return r2, rmse


def outlier_mask_iqr(v: np.ndarray, *, k: float = 1.5) -> np.ndarray:
    """Tukey fences: True where value is outside [Q1 - k·IQR, Q3 + k·IQR]."""
    v = np.asarray(v, dtype=float)
    m = np.isfinite(v)
    out = np.zeros_like(v, dtype=bool)
    if int(np.sum(m)) < 4:
        return out
    xs = v[m]
    q1, q3 = np.percentile(xs, [25.0, 75.0])
    iqr = float(q3 - q1)
    if iqr <= 0.0 or not np.isfinite(iqr):
        return out
    lo, hi = q1 - k * iqr, q3 + k * iqr
    out[m] = (xs < lo) | (xs > hi)
    return out


def outlier_mask_zscore(v: np.ndarray, *, z: float = 3.0) -> np.ndarray:
    """Classic Z using sample mean and SD; True where |Z| > threshold."""
    v = np.asarray(v, dtype=float)
    m = np.isfinite(v)
    out = np.zeros_like(v, dtype=bool)
    xs = v[m]
    if xs.size < 2:
        return out
    mu = float(np.mean(xs))
    sig = float(np.std(xs, ddof=1))
    if sig <= 0.0 or not np.isfinite(sig):
        return out
    zsc = np.abs((v - mu) / sig)
    return m & (zsc > z)


def outlier_mask_modified_z(v: np.ndarray, *, threshold: float = 3.5) -> np.ndarray:
    """Modified Z (Iglewicz & Hoaglin): 0.6745 · |x − median| / MAD."""
    v = np.asarray(v, dtype=float)
    m = np.isfinite(v)
    out = np.zeros_like(v, dtype=bool)
    xs = v[m]
    if xs.size < 3:
        return out
    med = float(np.median(xs))
    mad = float(np.median(np.abs(xs - med)))
    if mad <= 0.0 or not np.isfinite(mad):
        return out
    mz = 0.6745 * np.abs(v - med) / mad
    return m & (mz > threshold)


def parse_percentiles(s: str) -> list[float]:
    """Parse comma-separated percentiles in (0, 100) or (0, 1)."""
    parts = [p.strip() for p in s.split(",") if p.strip()]
    out: list[float] = []
    for p in parts:
        v = float(p)
        if v > 1.0:
            v = v / 100.0
        if not (0.0 < v < 1.0):
            raise ValueError(f"Percentile out of (0,100) exclusive: {p}")
        out.append(v)
    return sorted(set(out))


def format_numeric_summary(
    df_raw: pd.DataFrame,
    df_num: pd.DataFrame,
    *,
    empty_selection_note: str | None = None,
) -> str:
    """Plain-text summary of a scoped table snapshot."""
    lines: list[str] = []
    if empty_selection_note:
        lines.append(empty_selection_note)
        lines.append("")
    n = len(df_raw)
    lines.append(f"Rows: {n}")
    lines.append(f"Columns (excl. Structure): {df_raw.shape[1]}")
    num_cols = list(df_num.columns)
    lines.append(f"Numeric columns (≥1 value): {len(num_cols)}")
    if num_cols and n > 0:
        lines.append("")
        desc = df_num.describe(percentiles=[0.05, 0.25, 0.5, 0.75, 0.95])
        lines.append(desc.to_string())
        lines.append("")
        sk = df_num.skew(numeric_only=True)
        ku = df_num.kurtosis(numeric_only=True)
        lines.append("Skewness:")
        lines.append(sk.to_string())
        lines.append("")
        lines.append("Kurtosis (excess):")
        lines.append(ku.to_string())
    elif not num_cols:
        lines.append("")
        lines.append(
            "No numeric columns detected after coercion — add numeric property columns or calculations."
        )
    miss = df_raw.isna().sum()
    if miss.any():
        lines.append("")
        lines.append("Missing / non-numeric cells (raw column counts as NaN after coercion):")
        lines.append(miss[miss > 0].to_string())
    return "\n".join(lines)


def analyze_outlier_column(
    values: np.ndarray,
    *,
    column: str,
    method: str,
    k: float = 1.5,
    z: float = 3.0,
    threshold: float = 3.5,
) -> OutlierColumnResult:
    """Flag outliers in one numeric series and collect the report header lines."""
    v = np.asarray(values, dtype=float)
    fin = np.isfinite(v)
    n_fin = int(np.sum(fin))
    lines: list[str] = []

    if method == OUTLIER_IQR:
        mask = outlier_mask_iqr(v, k=k)
        lines.append(f"Column: {column}")
        lines.append(f"Method: IQR (Tukey fences), k={k:g}")
        lines.append(f"n finite: {n_fin}")
        if n_fin >= 4:
            xs = v[fin]
            q1, q3 = np.percentile(xs, [25.0, 75.0])
            iqr = float(q3 - q1)
            lo, hi = q1 - k * iqr, q3 + k * iqr
            lines.append(f"Q1={q1:g}, Q3={q3:g}, IQR={iqr:g}")
            lines.append(f"Fences: [{lo:g}, {hi:g}]")
        else:
            lines.append("(Fewer than 4 finite values — IQR fences are not applied.)")
    elif method == OUTLIER_ZSCORE:
        mask = outlier_mask_zscore(v, z=z)
        lines.append(f"Column: {column}")
        lines.append(f"Method: Z-score, |Z| > {z:g}")
        lines.append(f"n finite: {n_fin}")
        xs = v[fin]
        if xs.size >= 2:
            mu, sig = float(np.mean(xs)), float(np.std(xs, ddof=1))
            lines.append(f"mean={mu:g}, SD (sample)={sig:g}")
        else:
            lines.append("(Need at least two finite values.)")
    elif method == OUTLIER_MODIFIED_Z:
        mask = outlier_mask_modified_z(v, threshold=threshold)
        lines.append(f"Column: {column}")
        lines.append(f"Method: modified Z (median & MAD), threshold={threshold:g}")
        lines.append(f"n finite: {n_fin}")
        if n_fin >= 3:
            med = float(np.median(v[fin]))
            mad = float(np.median(np.abs(v[fin] - med)))
            lines.append(f"median={med:g}, MAD={mad:g}")
    else:
        raise ValueError(f"Unknown outlier method: {method!r}")

    idxs = tuple(int(i) for i in np.flatnonzero(mask))
    flagged = tuple(float(v[i]) for i in idxs)
    lines.append(f"Outliers flagged: {len(idxs)}")
    return OutlierColumnResult(column, tuple(lines), idxs, flagged)


def format_outlier_column_report(
    result: OutlierColumnResult,
    *,
    row_label: Callable[[int], str],
    max_list: int = 500,
    values: np.ndarray | None = None,
) -> str:
    """Append the labelled value table to *result.header_lines*."""
    lines = list(result.header_lines)
    if result.indices:
        series = None if values is None else np.asarray(values, dtype=float)
        lines.append("")
        lines.append(f"{'Label':<28} {'Value':>16}")
        n_show = min(len(result.indices), max_list)
        for j in range(n_show):
            ii = result.indices[j]
            value = result.values[j] if series is None else float(series[ii])
            lines.append(f"{row_label(ii):<28} {value:>16.8g}")
        if len(result.indices) > max_list:
            lines.append(f"... ({len(result.indices) - max_list} more not shown)")
    return "\n".join(lines)


def fit_xy_curve(
    x: np.ndarray,
    y: np.ndarray,
    *,
    model: str,
    x_name: str,
    y_name: str,
    degree: int = 1,
) -> CurveFitResult:
    """Fit *model* to paired finite (x, y). *text* is the report or an error."""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    mask = np.isfinite(x) & np.isfinite(y)
    x, y = x[mask], y[mask]
    n = len(x)
    if n < 2:
        return CurveFitResult("Need at least two paired finite values.", ok=False)

    lines: list[str] = [f"N (finite pairs): {n}", ""]
    try:
        if model == CURVE_POLYNOMIAL:
            deg = int(degree)
            coefs = np.polyfit(x, y, deg)
            y_hat = np.polyval(coefs, x)
            r2, rmse = r2_rmse(y, y_hat)
            terms = []
            for i, c in enumerate(coefs):
                p = deg - i
                if p == 0:
                    terms.append(f"{c:.8g}")
                elif p == 1:
                    terms.append(f"{c:.8g}*({x_name})")
                else:
                    terms.append(f"{c:.8g}*({x_name})^{p}")
            eq = " + ".join(terms).replace("+ -", "- ")
            lines.append(f"Model: {y_name} = {eq}")
            lines.append(f"Polynomial degree: {deg}")
            lines.append(f"R²: {r2:.8g}")
            lines.append(f"RMSE: {rmse:.8g}")
            lines.append("")
            lines.append("Coefficients (high degree first, NumPy polyfit convention):")
            lines.append(np.array2string(coefs, precision=8))
        elif model == CURVE_EXPONENTIAL:
            try:
                from scipy.optimize import curve_fit
            except ImportError as exc:
                return CurveFitResult(
                    "Exponential fitting requires SciPy. Install with: pip install scipy\n"
                    + str(exc),
                    ok=False,
                )
            if np.any(y <= 0):
                return CurveFitResult(
                    "Exponential model requires all Y values to be positive.",
                    ok=False,
                )

            def exp_model(t, a, b):
                return a * np.exp(b * t)

            p0 = (float(np.median(y)), 1e-4)
            popt, _pcov = curve_fit(exp_model, x, y, p0=p0, maxfev=200_000)
            a, b = float(popt[0]), float(popt[1])
            y_hat = exp_model(x, a, b)
            r2, rmse = r2_rmse(y, y_hat)
            lines.append(f"Model: {y_name} = {a:.8g} * exp({b:.8g} * ({x_name}))")
            lines.append(f"R²: {r2:.8g}")
            lines.append(f"RMSE: {rmse:.8g}")
        elif model == CURVE_LOGX:
            if np.any(x <= 0):
                return CurveFitResult(
                    "Log-X model requires all X values to be positive.",
                    ok=False,
                )
            lx = np.log(x)
            slope, intercept = np.polyfit(lx, y, 1)
            y_hat = slope * lx + intercept
            r2, rmse = r2_rmse(y, y_hat)
            lines.append(f"Model: {y_name} = {intercept:.8g} + {slope:.8g} * ln({x_name})")
            lines.append(f"R²: {r2:.8g}")
            lines.append(f"RMSE: {rmse:.8g}")
        elif model == CURVE_POWER:
            if np.any(x <= 0) or np.any(y <= 0):
                return CurveFitResult(
                    "Power-law model requires all X and Y values to be positive.",
                    ok=False,
                )
            lx = np.log(x)
            ly = np.log(y)
            b, log_a = np.polyfit(lx, ly, 1)
            a = float(np.exp(log_a))
            b = float(b)
            y_hat = a * (x**b)
            r2, rmse = r2_rmse(y, y_hat)
            lines.append(f"Model: {y_name} = {a:.8g} * ({x_name})^{b:.8g}  (fit in log-log space)")
            lines.append(f"R²: {r2:.8g}")
            lines.append(f"RMSE: {rmse:.8g}")
        else:
            return CurveFitResult(f"Unknown curve-fit model: {model!r}", ok=False)
    except Exception as exc:  # noqa: BLE001
        return CurveFitResult(f"Fit failed: {exc}", ok=False)
    return CurveFitResult("\n".join(lines))


def run_hypothesis_test(
    a: np.ndarray,
    b: np.ndarray | None,
    *,
    test: str,
    a_name: str,
    b_name: str = "",
    hypothesized_mean: float | None = None,
) -> HypothesisTestResult:
    """Run one SciPy hypothesis test on one or two numeric series."""
    try:
        from scipy import stats
    except Exception as exc:  # noqa: BLE001
        return HypothesisTestResult((f"SciPy is not available: {exc}",))

    ca = np.asarray(a, dtype=float)
    cb = np.asarray(b, dtype=float) if b is not None else np.array([])
    lines: list[str] = []
    try:
        if test == TEST_SHAPIRO:
            v = ca[np.isfinite(ca)]
            if len(v) < 3:
                lines.append("Shapiro-Wilk needs at least 3 finite values.")
            else:
                if len(v) > 5000:
                    lines.append("Note: using the first 5000 values (SciPy Shapiro-Wilk limit).")
                    v = v[:5000]
                stat, p = stats.shapiro(v)
                lines.append(f"Column: {a_name}")
                lines.append(f"Shapiro-Wilk W = {stat:.8g}, p-value = {p:.4g}")
                lines.append("(H0: data come from a normal distribution.)")
        elif test == TEST_ONE_SAMPLE_T:
            v = ca[np.isfinite(ca)]
            if hypothesized_mean is None:
                lines.append("Enter a numeric hypothesized mean.")
            elif len(v) < 2:
                lines.append("Need at least two finite values.")
            else:
                res = stats.ttest_1samp(v, popmean=hypothesized_mean, nan_policy="omit")
                lines.append(f"Column: {a_name}  vs  H0 mean = {hypothesized_mean}")
                lines.append(
                    f"t = {float(res.statistic):.8g}, p-value (two-sided) = {float(res.pvalue):.4g}"
                )
                lines.append(f"n = {len(v)}")
        elif test in (TEST_PAIRED_T, TEST_WELCH_T, TEST_MANN_WHITNEY):
            if not a_name or not b_name or a_name == b_name:
                lines.append("Pick two different columns.")
            else:
                paired_mask = np.isfinite(ca) & np.isfinite(cb)
                a_p = ca[paired_mask]
                b_p = cb[paired_mask]
                if test == TEST_PAIRED_T:
                    if len(a_p) < 2:
                        lines.append("Need at least two paired finite values.")
                    else:
                        res = stats.ttest_rel(a_p, b_p, nan_policy="omit")
                        lines.append(f"Paired t-test: {a_name} vs {b_name}")
                        lines.append(
                            f"t = {float(res.statistic):.8g}, p-value (two-sided) = {float(res.pvalue):.4g}"
                        )
                        lines.append(f"n (pairs) = {len(a_p)}")
                elif test == TEST_WELCH_T:
                    a_all = ca[np.isfinite(ca)]
                    b_all = cb[np.isfinite(cb)]
                    if len(a_all) < 2 or len(b_all) < 2:
                        lines.append("Each column needs at least two finite values.")
                    else:
                        res = stats.ttest_ind(a_all, b_all, equal_var=False, nan_policy="omit")
                        lines.append(f"Welch t-test (independent): {a_name} vs {b_name}")
                        lines.append(
                            f"t = {float(res.statistic):.8g}, p-value (two-sided) = {float(res.pvalue):.4g}"
                        )
                        lines.append(f"n₁ = {len(a_all)}, n₂ = {len(b_all)}")
                else:
                    a_all = ca[np.isfinite(ca)]
                    b_all = cb[np.isfinite(cb)]
                    if len(a_all) < 1 or len(b_all) < 1:
                        lines.append("Each column needs at least one finite value.")
                    else:
                        res = stats.mannwhitneyu(a_all, b_all, alternative="two-sided")
                        lines.append(f"Mann-Whitney U: {a_name} vs {b_name}")
                        lines.append(
                            f"U = {float(res.statistic):.8g}, p-value (two-sided) = {float(res.pvalue):.4g}"
                        )
                        lines.append(f"n₁ = {len(a_all)}, n₂ = {len(b_all)}")
        else:
            lines.append("Unknown test.")
    except Exception as exc:  # noqa: BLE001
        lines.append(f"Test failed: {exc}")
    return HypothesisTestResult(tuple(lines))
