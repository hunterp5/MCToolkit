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

"""Reaction-arrow geometry and SMILES/SMARTS joining for the sketcher."""

from __future__ import annotations

import math

MIN_REACTION_ARROW_LENGTH = 28.0
ARROW_SNAP_DEG = 15.0


def snap_arrow_end(
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    *,
    snap: bool,
) -> tuple[float, float]:
    """Optionally snap the arrow head to 15° increments around the tail."""
    if not snap:
        return x1, y1
    dx, dy = x1 - x0, y1 - y0
    length = math.hypot(dx, dy)
    if length < 1e-6:
        return x1, y1
    ang = math.atan2(dy, dx)
    step = math.radians(ARROW_SNAP_DEG)
    snapped = round(ang / step) * step
    return x0 + length * math.cos(snapped), y0 + length * math.sin(snapped)


def fragment_side(
    cx: float,
    cy: float,
    x0: float,
    y0: float,
    x1: float,
    y1: float,
) -> str:
    """``reactant`` on the tail side of the perpendicular bisector, else ``product``."""
    mx, my = 0.5 * (x0 + x1), 0.5 * (y0 + y1)
    side = (cx - mx) * (x1 - x0) + (cy - my) * (y1 - y0)
    return "product" if side >= 0.0 else "reactant"


def plus_sign_positions(
    centroids: list[tuple[float, float]],
    x0: float,
    y0: float,
    x1: float,
    y1: float,
) -> list[tuple[float, float]]:
    """Midpoints between consecutive same-side fragments, ordered along the arrow axis."""
    if len(centroids) < 2:
        return []
    dx, dy = x1 - x0, y1 - y0
    ordered = sorted(centroids, key=lambda c: c[0] * dx + c[1] * dy)
    out: list[tuple[float, float]] = []
    for (ax, ay), (bx, by) in zip(ordered, ordered[1:]):
        out.append((0.5 * (ax + bx), 0.5 * (ay + by)))
    return out


def join_reaction_string(reactants: list[str], products: list[str]) -> str:
    """Daylight reaction SMILES/SMARTS: ``A.B>>C.D``."""
    left = ".".join(p for p in reactants if p)
    right = ".".join(p for p in products if p)
    if not left and not right:
        return ""
    return f"{left}>>{right}"
