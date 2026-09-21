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
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with MCToolkit. If not, see <https://www.gnu.org/licenses/>.

"""Plotter axis / mode / histogram helpers (no Qt)."""

from __future__ import annotations

import math

AXIS_NONE = "None"

PLOT_TYPE_SCATTER = "scatter"
PLOT_TYPE_HISTOGRAM = "histogram"
PLOT_TYPE_LINE_2D = "line_2d"
PLOT_TYPE_BOX = "box"
PLOT_TYPE_VIOLIN = "violin"
PLOT_TYPE_HEATMAP = "heatmap"
PLOT_TYPE_RADAR = "radar"

PLOT_TYPE_CHOICES: tuple[tuple[str, str], ...] = (
    ("Scatter", PLOT_TYPE_SCATTER),
    ("Histogram", PLOT_TYPE_HISTOGRAM),
    ("2D Line", PLOT_TYPE_LINE_2D),
    ("Heatmap", PLOT_TYPE_HEATMAP),
    ("Box plot", PLOT_TYPE_BOX),
    ("Violin", PLOT_TYPE_VIOLIN),
    ("Radar", PLOT_TYPE_RADAR),
)

PLOT_SESSION_KIND = "plotter"


def normalize_axis_name(text: str | None) -> str | None:
    """Return a column name, or None when the combo is unset or ``AXIS_NONE``."""
    if not text:
        return None
    name = text.strip()
    if not name or name == AXIS_NONE:
        return None
    return name


def infer_plot_mode(x: str | None, y: str | None, z: str | None) -> str | None:
    """Infer scatter dimensionality from axis combo text: 2D, 3D, or None if invalid."""
    xn = normalize_axis_name(x)
    yn = normalize_axis_name(y)
    zn = normalize_axis_name(z)
    if not xn or yn is None:
        return None
    if zn is None:
        return "2D"
    return "3D"


def resolve_plot_mode(
    plot_type: str,
    x: str | None,
    y: str | None,
    z: str | None,
) -> str | None:
    """Resolve plot mode from plot type and axis selections."""
    xn = normalize_axis_name(x)
    yn = normalize_axis_name(y)
    if plot_type == PLOT_TYPE_HISTOGRAM:
        return "Histogram" if xn else None
    if plot_type == PLOT_TYPE_SCATTER:
        return infer_plot_mode(x, y, z)
    if plot_type == PLOT_TYPE_LINE_2D:
        return "2D" if xn and yn else None
    if plot_type == PLOT_TYPE_HEATMAP:
        return "Heatmap" if xn and yn else None
    return None


def compute_histogram_bin_edges(
    vals: list[float],
    *,
    bin_width: float | None = None,
    xmin: float | None = None,
    xmax: float | None = None,
) -> tuple[list[float], float]:
    """Return histogram bin edges (length n+1) and the bin width used."""
    if not vals:
        return [0.0, 1.0], 1.0
    lo = float(xmin) if xmin is not None else min(vals)
    hi = float(xmax) if xmax is not None else max(vals)
    if lo > hi:
        lo, hi = hi, lo
    if math.isclose(lo, hi, rel_tol=0.0, abs_tol=1e-12):
        hi = lo + 1.0
    if bin_width is not None and bin_width > 0:
        width = float(bin_width)
        start = math.floor(lo / width) * width
        end = math.ceil(hi / width) * width
        edges = []
        x = start
        guard = 0
        while x <= end + abs(end) * 1e-9 and guard < 10_000:
            edges.append(x)
            x += width
            guard += 1
        if len(edges) < 2:
            edges = [lo, lo + width]
        return edges, width
    n = len(vals)
    n_bins = max(1, int(math.ceil(math.log2(n) + 1))) if n else 1
    width = (hi - lo) / n_bins
    edges = [lo + i * width for i in range(n_bins + 1)]
    edges[-1] = hi
    return edges, width


def oids_at_histogram_point_indices(oids: list[int], indices: list[int]) -> list[int]:
    """Map Plotly histogram ``pointNumbers`` indices to row OIDs (deduped, order preserved)."""
    n = len(oids)
    seen: set[int] = set()
    selected: list[int] = []
    for raw in indices:
        try:
            i = int(raw)
        except (TypeError, ValueError):
            continue
        if not (0 <= i < n):
            continue
        oid = int(oids[i])
        if oid in seen:
            continue
        seen.add(oid)
        selected.append(oid)
    return selected


def oids_in_histogram_bin(
    vals: list[float],
    oids: list[int],
    edges: list[float],
    bin_index: int,
) -> list[int]:
    """OIDs whose values fall in histogram bin ``bin_index`` (half-open, last bin inclusive)."""
    if bin_index < 0 or bin_index + 1 >= len(edges):
        return []
    lo, hi = float(edges[bin_index]), float(edges[bin_index + 1])
    last_bin = bin_index == len(edges) - 2
    selected: list[int] = []
    for v, oid in zip(vals, oids):
        vf = float(v)
        if last_bin:
            if lo <= vf <= hi:
                selected.append(int(oid))
        elif lo <= vf < hi:
            selected.append(int(oid))
    return selected
