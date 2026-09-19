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

"""Multi-parameter optimization (MPO) desirability scoring for table columns.

Maps each numeric property through a desirability function on ``[0, 1]``, then
combines them into an overall score (geometric or arithmetic mean, optionally weighted).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

DesirabilityKind = Literal["linear", "gaussian", "step"]
DesirabilityDirection = Literal["maximize", "minimize", "target"]
CombineMethod = Literal["geometric", "arithmetic"]


@dataclass(frozen=True)
class DesirabilitySpec:
    """One property → desirability mapping."""

    column: str
    kind: DesirabilityKind = "linear"
    direction: DesirabilityDirection = "maximize"
    weight: float = 1.0
    low: float | None = None
    high: float | None = None
    target: float | None = None
    center: float | None = None
    sigma: float | None = None


def _clamp01(x: float) -> float:
    if x < 0.0:
        return 0.0
    if x > 1.0:
        return 1.0
    return float(x)


def linear_desirability(
    x: float,
    *,
    direction: DesirabilityDirection,
    low: float,
    high: float,
    target: float | None = None,
) -> float:
    """
    Piecewise-linear Derringer-style desirability.

    * maximize: 0 at/below *low*, 1 at/above *high*
    * minimize: 1 at/below *low*, 0 at/above *high*
    * target: 0 outside [*low*, *high*], 1 at *target* (defaults to midpoint)
    """
    if not math.isfinite(x) or not math.isfinite(low) or not math.isfinite(high):
        return float("nan")
    if high < low:
        low, high = high, low
    if direction == "maximize":
        if high <= low:
            return 1.0 if x >= high else 0.0
        if x <= low:
            return 0.0
        if x >= high:
            return 1.0
        return _clamp01((x - low) / (high - low))
    if direction == "minimize":
        if high <= low:
            return 1.0 if x <= low else 0.0
        if x <= low:
            return 1.0
        if x >= high:
            return 0.0
        return _clamp01(1.0 - (x - low) / (high - low))
    # target
    t = float(target) if target is not None and math.isfinite(target) else 0.5 * (low + high)
    t = min(max(t, low), high)
    if x <= low or x >= high:
        return 0.0
    if x == t:
        return 1.0
    if x < t:
        if t <= low:
            return 0.0
        return _clamp01((x - low) / (t - low))
    if high <= t:
        return 0.0
    return _clamp01((high - x) / (high - t))


def gaussian_desirability(x: float, *, center: float, sigma: float) -> float:
    """Bell-shaped desirability peaked at *center* with width *sigma* (d=exp(-½ z²))."""
    if not math.isfinite(x) or not math.isfinite(center) or not math.isfinite(sigma):
        return float("nan")
    s = abs(float(sigma))
    if s <= 0.0:
        return 1.0 if x == center else 0.0
    z = (x - center) / s
    return _clamp01(math.exp(-0.5 * z * z))


def step_desirability(
    x: float,
    *,
    direction: DesirabilityDirection,
    low: float,
    high: float,
) -> float:
    """
    Hard threshold desirability.

    * maximize: 1 if x ≥ *high*, else 0 (*low* unused)
    * minimize: 1 if x ≤ *low*, else 0 (*high* unused)
    * target: 1 if *low* ≤ x ≤ *high*, else 0
    """
    if not math.isfinite(x):
        return float("nan")
    if direction == "maximize":
        thr = high if math.isfinite(high) else low
        if not math.isfinite(thr):
            return float("nan")
        return 1.0 if x >= thr else 0.0
    if direction == "minimize":
        thr = low if math.isfinite(low) else high
        if not math.isfinite(thr):
            return float("nan")
        return 1.0 if x <= thr else 0.0
    if not math.isfinite(low) or not math.isfinite(high):
        return float("nan")
    lo, hi = (low, high) if low <= high else (high, low)
    return 1.0 if lo <= x <= hi else 0.0


def evaluate_desirability(x: float | None, spec: DesirabilitySpec) -> float:
    """Evaluate one :class:`DesirabilitySpec` at *x* (NaN if *x* is missing/invalid)."""
    if x is None:
        return float("nan")
    try:
        xv = float(x)
    except (TypeError, ValueError):
        return float("nan")
    if not math.isfinite(xv):
        return float("nan")
    kind = spec.kind
    if kind == "linear":
        low = float(spec.low if spec.low is not None else 0.0)
        high = float(spec.high if spec.high is not None else 1.0)
        return linear_desirability(
            xv,
            direction=spec.direction,
            low=low,
            high=high,
            target=spec.target,
        )
    if kind == "gaussian":
        center = float(spec.center if spec.center is not None else (spec.target or 0.0))
        sigma = float(spec.sigma if spec.sigma is not None else 1.0)
        return gaussian_desirability(xv, center=center, sigma=sigma)
    if kind == "step":
        low = float(spec.low if spec.low is not None else 0.0)
        high = float(spec.high if spec.high is not None else 1.0)
        return step_desirability(xv, direction=spec.direction, low=low, high=high)
    raise ValueError(f"Unknown desirability kind: {kind!r}")


def combine_desirabilities(
    values: list[float],
    weights: list[float] | None = None,
    *,
    method: CombineMethod = "arithmetic",
) -> float:
    """
    Combine individual desirabilities into one score in ``[0, 1]``.

    Arithmetic mean is a weighted average. Geometric mean is the classic
    Derringer–Suich overall desirability. Missing/NaN inputs yield NaN.
    Non-positive weights are ignored.
    """
    if not values:
        return float("nan")
    if any(not math.isfinite(v) for v in values):
        return float("nan")
    if weights is None:
        w = [1.0] * len(values)
    else:
        if len(weights) != len(values):
            raise ValueError("weights length must match values")
        w = [max(0.0, float(x)) for x in weights]
    total_w = sum(w)
    if total_w <= 0.0:
        return float("nan")
    if method == "arithmetic":
        return _clamp01(sum(v * wi for v, wi in zip(values, w)) / total_w)
    if method == "geometric":
        # D = exp(Σ w_i ln(d_i) / Σ w_i); d=0 ⇒ overall 0
        if any(v <= 0.0 for v in values):
            return 0.0
        acc = sum(wi * math.log(v) for v, wi in zip(values, w))
        return _clamp01(math.exp(acc / total_w))
    raise ValueError(f"Unknown combine method: {method!r}")


def score_mpo_row(
    values_by_column: dict[str, float | None],
    specs: list[DesirabilitySpec],
    *,
    method: CombineMethod = "arithmetic",
) -> tuple[float | None, dict[str, float | None]]:
    """
    Score one row.

    Returns ``(overall_or_None, {column: desirability_or_None})``.
    """
    if not specs:
        return None, {}
    per: dict[str, float | None] = {}
    ds: list[float] = []
    ws: list[float] = []
    for spec in specs:
        raw = values_by_column.get(spec.column)
        d = evaluate_desirability(raw, spec)
        if not math.isfinite(d):
            per[spec.column] = None
            ds.append(float("nan"))
        else:
            per[spec.column] = float(d)
            ds.append(float(d))
        ws.append(float(spec.weight))
    overall = combine_desirabilities(ds, ws, method=method)
    if not math.isfinite(overall):
        return None, per
    return float(overall), per


def format_score(value: float | None, *, decimals: int = 4) -> str:
    """Table cell text for an MPO score."""
    if value is None or not math.isfinite(value):
        return ""
    dec = max(0, min(12, int(decimals)))
    return f"{float(value):.{dec}f}"
