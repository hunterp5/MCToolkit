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

"""Statistics summaries and curve fits for Plotly charts (Plotter)."""

from __future__ import annotations

import numpy as np

FIT_NONE = "none"
FIT_LINEAR = "linear"
FIT_QUADRATIC = "quadratic"
FIT_GAUSSIAN = "gaussian"
FIT_TRUNCATED_GAUSSIAN = "truncated_gaussian"
FIT_LOGNORMAL = "lognormal"

HISTOGRAM_ONLY_FITS = frozenset({FIT_GAUSSIAN, FIT_TRUNCATED_GAUSSIAN, FIT_LOGNORMAL})

PLOT_FIT_CHOICES: tuple[tuple[str, str], ...] = (
    ("None", FIT_NONE),
    ("Linear", FIT_LINEAR),
    ("Quadratic", FIT_QUADRATIC),
    ("Normal", FIT_GAUSSIAN),
    ("Truncated Normal", FIT_TRUNCATED_GAUSSIAN),
    ("Log-Normal", FIT_LOGNORMAL),
)

PLOT_FIT_CHOICES_XY: tuple[tuple[str, str], ...] = tuple(
    choice for choice in PLOT_FIT_CHOICES if choice[1] not in HISTOGRAM_ONLY_FITS
)


def _finite_array(values: list[float]) -> np.ndarray:
    arr = np.asarray(values, dtype=float)
    mask = np.isfinite(arr)
    return arr[mask]


def _paired_finite(x: list[float], y: list[float]) -> tuple[np.ndarray, np.ndarray]:
    xa = np.asarray(x, dtype=float)
    ya = np.asarray(y, dtype=float)
    n = min(xa.size, ya.size)
    xa = xa[:n]
    ya = ya[:n]
    mask = np.isfinite(xa) & np.isfinite(ya)
    return xa[mask], ya[mask]


def summarize_univariate(values: list[float], *, label: str) -> list[str]:
    """Summary lines for one numeric series (histogram, box, violin)."""
    arr = _finite_array(values)
    n = int(arr.size)
    if n == 0:
        return [f"{label}: no data"]
    lines = [
        f"{label} (n={n})",
        f"  mean = {_fmt(arr.mean())}",
        f"  median = {_fmt(np.median(arr))}",
        f"  std = {_fmt(arr.std(ddof=1)) if n > 1 else '—'}",
        f"  min = {_fmt(arr.min())}",
        f"  max = {_fmt(arr.max())}",
    ]
    if n >= 4:
        q1, q3 = np.percentile(arr, [25, 75])
        lines.append(f"  Q1 = {_fmt(q1)}  Q3 = {_fmt(q3)}")
    return lines


def summarize_xy(
    x: list[float],
    y: list[float],
    *,
    x_label: str,
    y_label: str,
) -> list[str]:
    """Summary lines for paired X/Y data (2D scatter or line)."""
    xa, ya = _paired_finite(x, y)
    n = int(xa.size)
    if n == 0:
        return ["No data"]
    lines = [
        f"n = {n}",
        f"{x_label}: mean {_fmt(xa.mean())}  σ {_fmt(xa.std(ddof=1)) if n > 1 else '—'}",
        f"{y_label}: mean {_fmt(ya.mean())}  σ {_fmt(ya.std(ddof=1)) if n > 1 else '—'}",
    ]
    if n >= 2:
        r = float(np.corrcoef(xa, ya)[0, 1])
        if np.isfinite(r):
            lines.append(f"Pearson r = {r:.4f}")
    return lines


def fit_xy_curve(
    x: list[float],
    y: list[float],
    fit_kind: str,
    *,
    n_points: int = 100,
) -> tuple[list[float], list[float], str] | None:
    """
    Return fitted (x_line, y_line, legend name) for overlay on a 2D plot.

    ``fit_kind`` is ``FIT_LINEAR``, ``FIT_QUADRATIC``, or ``FIT_NONE``.
    """
    if fit_kind == FIT_NONE:
        return None
    xa, ya = _paired_finite(x, y)
    n = int(xa.size)
    if n < 2:
        return None
    order = 1 if fit_kind == FIT_LINEAR else 2
    if fit_kind == FIT_QUADRATIC and n < 3:
        return None
    try:
        coeffs = np.polyfit(xa, ya, order)
    except np.linalg.LinAlgError:
        return None
    x0, x1 = float(xa.min()), float(xa.max())
    if abs(x1 - x0) < 1e-12:
        return None
    xs = np.linspace(x0, x1, max(2, int(n_points)))
    ys = np.polyval(coeffs, xs)
    if order == 1:
        name = f"Fit: y = {coeffs[0]:.4g}x + {coeffs[1]:.4g}"
    else:
        name = f"Fit: y = {coeffs[0]:.4g}x² + {coeffs[1]:.4g}x + {coeffs[2]:.4g}"
    return xs.tolist(), ys.tolist(), name


def _truncation_interval(
    arr: np.ndarray,
    *,
    lower: float | None,
    upper: float | None,
) -> tuple[float, float]:
    """Finite truncation interval for scipy truncnorm (open-ended sides use wide tails)."""
    sigma = float(arr.std(ddof=1)) if arr.size > 1 else 1.0
    span = max(sigma * 8.0, (float(arr.max()) - float(arr.min())) * 0.5, 1.0)
    lo = float(lower) if lower is not None else float(arr.min()) - span
    hi = float(upper) if upper is not None else float(arr.max()) + span
    if hi <= lo:
        hi = lo + max(span, 1e-6)
    return lo, hi


def _fit_truncated_gaussian_overlay(
    arr: np.ndarray,
    edge_arr: np.ndarray,
    width: float,
    *,
    lower: float | None,
    upper: float | None,
    n_points: int,
) -> tuple[list[float], list[float], str] | None:
    from scipy import stats
    from scipy.optimize import minimize

    work = arr
    if lower is not None:
        work = work[work >= lower]
    if upper is not None:
        work = work[work <= upper]
    if work.size < 2:
        return None

    lo, hi = _truncation_interval(work, lower=lower, upper=upper)
    mu0 = float(work.mean())
    sigma0 = max(float(work.std(ddof=1)), 1e-6)

    def neg_log_likelihood(params: np.ndarray) -> float:
        mu = float(params[0])
        sigma = float(np.exp(params[1]))
        a = (lo - mu) / sigma
        b = (hi - mu) / sigma
        if b <= a + 1e-8:
            return 1e30
        return -float(np.sum(stats.truncnorm.logpdf(work, a, b, loc=mu, scale=sigma)))

    result = minimize(
        neg_log_likelihood,
        np.array([mu0, np.log(sigma0)], dtype=float),
        method="L-BFGS-B",
    )
    if not result.success:
        return None
    mu = float(result.x[0])
    sigma = float(np.exp(result.x[1]))
    if sigma < 1e-12:
        return None

    a = (lo - mu) / sigma
    b = (hi - mu) / sigma
    x0, x1 = float(edge_arr[0]), float(edge_arr[-1])
    if abs(x1 - x0) < 1e-12:
        return None
    xs = np.linspace(x0, x1, max(2, int(n_points)))
    pdf = stats.truncnorm.pdf(xs, a, b, loc=mu, scale=sigma)
    ys = arr.size * width * pdf

    bound_parts: list[str] = []
    if lower is not None:
        bound_parts.append(f"lower ≥ {_fmt(lower)}")
    if upper is not None:
        bound_parts.append(f"upper ≤ {_fmt(upper)}")
    bounds_note = f", {', '.join(bound_parts)}" if bound_parts else ""
    name = f"Fit: Truncated Normal(μ={mu:.4g}, σ={sigma:.4g}{bounds_note})"
    return xs.tolist(), ys.tolist(), name


def _fit_lognormal_overlay(
    arr: np.ndarray,
    edge_arr: np.ndarray,
    width: float,
    *,
    n_points: int,
) -> tuple[list[float], list[float], str] | None:
    """MLE log-normal overlay (positive samples only; loc fixed at 0)."""
    from scipy import stats

    positive = arr[arr > 0]
    if positive.size < 2:
        return None
    try:
        shape, loc, scale = stats.lognorm.fit(positive, floc=0)
    except Exception:
        return None
    shape = float(shape)
    scale = float(scale)
    if shape < 1e-12 or scale <= 0:
        return None

    x0, x1 = float(edge_arr[0]), float(edge_arr[-1])
    x_start = max(x0, np.finfo(float).tiny)
    if x_start >= x1:
        return None
    xs = np.linspace(x_start, x1, max(2, int(n_points)))
    pdf = stats.lognorm.pdf(xs, shape, loc=loc, scale=scale)
    ys = arr.size * width * pdf
    mu_log = float(np.log(scale))
    name = f"Fit: LogNormal(μ_log={_fmt(mu_log)}, σ_log={_fmt(shape)})"
    return xs.tolist(), ys.tolist(), name


def fit_histogram_curve(
    values: list[float],
    edges: list[float],
    fit_kind: str,
    *,
    bin_width: float | None = None,
    trunc_lower: float | None = None,
    trunc_upper: float | None = None,
    n_points: int = 100,
) -> tuple[list[float], list[float], str] | None:
    """
    Return a curve overlay for a histogram (counts on y).

    Gaussian fit scales a normal PDF to match bar counts; linear/quadratic fits
    bin centers versus counts.
    """
    if fit_kind == FIT_NONE:
        return None
    arr = _finite_array(values)
    if arr.size < 2:
        return None
    edge_arr = np.asarray(edges, dtype=float)
    if edge_arr.size < 2:
        return None
    width = (
        float(bin_width)
        if bin_width is not None and bin_width > 0
        else float(edge_arr[1] - edge_arr[0])
    )
    if width <= 0:
        return None

    if fit_kind == FIT_GAUSSIAN:
        mu = float(arr.mean())
        sigma = float(arr.std(ddof=1))
        if sigma < 1e-12:
            return None
        x0, x1 = float(edge_arr[0]), float(edge_arr[-1])
        if abs(x1 - x0) < 1e-12:
            return None
        xs = np.linspace(x0, x1, max(2, int(n_points)))
        pdf = (1.0 / (sigma * np.sqrt(2.0 * np.pi))) * np.exp(-0.5 * ((xs - mu) / sigma) ** 2)
        ys = arr.size * width * pdf
        name = f"Fit: Normal(μ={mu:.4g}, σ={sigma:.4g})"
        return xs.tolist(), ys.tolist(), name

    if fit_kind == FIT_TRUNCATED_GAUSSIAN:
        return _fit_truncated_gaussian_overlay(
            arr,
            edge_arr,
            width,
            lower=trunc_lower,
            upper=trunc_upper,
            n_points=n_points,
        )

    if fit_kind == FIT_LOGNORMAL:
        return _fit_lognormal_overlay(arr, edge_arr, width, n_points=n_points)

    counts, _ = np.histogram(arr, bins=edge_arr)
    centers = ((edge_arr[:-1] + edge_arr[1:]) / 2.0).tolist()
    return fit_xy_curve(centers, counts.tolist(), fit_kind, n_points=n_points)


def _fmt(value: float) -> str:
    av = abs(float(value))
    if av >= 1000 or (av > 0 and av < 0.001):
        return f"{value:.4g}"
    if av >= 100:
        return f"{value:.2f}"
    return f"{value:.4f}"
