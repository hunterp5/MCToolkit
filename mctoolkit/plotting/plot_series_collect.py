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

"""Collect numeric plot series from a table model (no Qt widgets)."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any, Protocol

from ..chem.molecule_conversion import safe_float


class _TableModelProto(Protocol):
    def row_oid(self, row: int) -> int: ...

    def cell_text(self, row: int, col: int) -> Any: ...


def collect_scatter_points(
    *,
    model: _TableModelProto,
    row_indices: Iterable[int],
    x_col: int,
    y_col: int,
    z_col: int | None = None,
    allowed_oids: set[int] | frozenset[int] | None = None,
    xmin: float | None = None,
    xmax: float | None = None,
    ymin: float | None = None,
    ymax: float | None = None,
    zmin: float | None = None,
    zmax: float | None = None,
) -> tuple[list[float], list[float], list[float], list[int]]:
    """Return ``(xs, ys, zs, oids)`` for scatter / heatmap scopes.

    When ``z_col`` is set, rows missing a Z value are skipped and ``zs`` is filled;
    otherwise ``zs`` is empty.
    """
    is3d = z_col is not None
    fx: list[float] = []
    fy: list[float] = []
    fz: list[float] = []
    foids: list[int] = []
    for r in row_indices:
        oid = int(model.row_oid(r))
        if allowed_oids is not None and oid not in allowed_oids:
            continue
        xv = safe_float(model.cell_text(r, x_col))
        yv = safe_float(model.cell_text(r, y_col))
        if xv is None or yv is None:
            continue
        xv = float(xv)
        yv = float(yv)
        if xmin is not None and xv < xmin:
            continue
        if xmax is not None and xv > xmax:
            continue
        if ymin is not None and yv < ymin:
            continue
        if ymax is not None and yv > ymax:
            continue
        if is3d:
            zv = safe_float(model.cell_text(r, z_col))
            if zv is None:
                continue
            zv = float(zv)
            if zmin is not None and zv < zmin:
                continue
            if zmax is not None and zv > zmax:
                continue
            fz.append(zv)
        fx.append(xv)
        fy.append(yv)
        foids.append(oid)
    return fx, fy, fz, foids


def collect_histogram_values(
    *,
    model: _TableModelProto,
    row_indices: Iterable[int],
    value_col: int,
    allowed_oids: set[int] | frozenset[int] | None = None,
    xmin: float | None = None,
    xmax: float | None = None,
) -> tuple[list[float], list[int]]:
    """Return ``(values, oids)`` for a single-column histogram / box / violin."""
    vals: list[float] = []
    oids: list[int] = []
    for r in row_indices:
        oid = int(model.row_oid(r))
        if allowed_oids is not None and oid not in allowed_oids:
            continue
        xv = safe_float(model.cell_text(r, value_col))
        if xv is None:
            continue
        xv = float(xv)
        if xmin is not None and xv < xmin:
            continue
        if xmax is not None and xv > xmax:
            continue
        vals.append(xv)
        oids.append(oid)
    return vals, oids


def plotly_axis_range(
    vmin: float | None, vmax: float | None, data_vals: Sequence[float]
) -> dict[str, Any]:
    """Build Plotly axis settings from user limits (may extend beyond plotted points)."""
    if vmin is None and vmax is None:
        return {}
    vals = list(data_vals) if data_vals else []
    lo = float(vmin) if vmin is not None else (min(vals) if vals else 0.0)
    hi = float(vmax) if vmax is not None else (max(vals) if vals else lo + 1.0)
    if lo > hi:
        lo, hi = hi, lo
    return {"range": [lo, hi], "autorange": False}
