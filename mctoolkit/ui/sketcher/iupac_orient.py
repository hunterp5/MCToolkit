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
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with MCToolkit.  If not, see <https://www.gnu.org/licenses/>.

"""IUPAC GR-3 structure orientation helpers for 2D depictions."""

from __future__ import annotations

import math
from typing import Sequence

from ...chem.rdkit_conformer_xy import set_conformer_xy

_HETERO = frozenset(
    {
        "N",
        "O",
        "S",
        "P",
        "F",
        "Cl",
        "Br",
        "I",
        "Se",
        "Te",
        "As",
        "B",
        "Si",
        "Sn",
    }
)


def _mean(vals: Sequence[float]) -> float:
    return sum(vals) / len(vals) if vals else 0.0


def rotate_points(
    xs: list[float], ys: list[float], angle_rad: float
) -> tuple[list[float], list[float]]:
    ca, sa = math.cos(angle_rad), math.sin(angle_rad)
    out_x, out_y = [], []
    for x, y in zip(xs, ys):
        out_x.append(x * ca - y * sa)
        out_y.append(x * sa + y * ca)
    return out_x, out_y


def reflect_x(xs: list[float], ys: list[float]) -> tuple[list[float], list[float]]:
    mx = _mean(xs)
    return [2.0 * mx - x for x in xs], list(ys)


def reflect_y(xs: list[float], ys: list[float]) -> tuple[list[float], list[float]]:
    my = _mean(ys)
    return list(xs), [2.0 * my - y for y in ys]


def _principal_axis_angle(xs: list[float], ys: list[float]) -> float:
    """Angle of the first principal axis (largest variance) via 2×2 covariance."""
    n = len(xs)
    if n < 2:
        return 0.0
    mx, my = _mean(xs), _mean(ys)
    sxx = syy = sxy = 0.0
    for x, y in zip(xs, ys):
        dx, dy = x - mx, y - my
        sxx += dx * dx
        syy += dy * dy
        sxy += dx * dy
    if abs(sxy) < 1e-12 and abs(sxx - syy) < 1e-12:
        return 0.0
    return 0.5 * math.atan2(2.0 * sxy, sxx - syy)


def _longest_bond_angle(
    xs: list[float],
    ys: list[float],
    bonds: Sequence[tuple[int, int]],
) -> float | None:
    best = -1.0
    ang: float | None = None
    for i, j in bonds:
        if i < 0 or j < 0 or i >= len(xs) or j >= len(xs):
            continue
        dx, dy = xs[j] - xs[i], ys[j] - ys[i]
        length = math.hypot(dx, dy)
        if length > best:
            best = length
            ang = math.atan2(dy, dx)
    return ang


def _ring_atom_indices(bonds: Sequence[tuple[int, int]], n_atoms: int) -> set[int]:
    """Leaf-trim cycle membership (same idea as sketcher ring detection)."""
    from collections import deque

    adj: dict[int, set[int]] = {i: set() for i in range(n_atoms)}
    for a, b in bonds:
        if 0 <= a < n_atoms and 0 <= b < n_atoms:
            adj[a].add(b)
            adj[b].add(a)
    deg = {k: len(v) for k, v in adj.items()}
    q = deque([k for k, d in deg.items() if d <= 1])
    removed: set[int] = set()
    while q:
        u = q.popleft()
        if u in removed:
            continue
        removed.add(u)
        for v in adj[u]:
            if v in removed:
                continue
            deg[v] -= 1
            if deg[v] == 1:
                q.append(v)
    return set(range(n_atoms)) - removed


def _ring_system_components(bonds: Sequence[tuple[int, int]], ring: set[int]) -> list[set[int]]:
    """
    Fused/bridged ring-system components (GR-3.4.1).

    Builds simple cycles through ring edges, then merges cycles that share atoms.
    A single bond linking two rings (not part of a shared cycle) does **not** merge
    them — so a phenyl–alkyl–cyclopropyl stays two systems.
    """
    from collections import deque

    if len(ring) < 3:
        return [set(ring)] if ring else []

    adj: dict[int, set[int]] = {i: set() for i in ring}
    ring_edges: list[tuple[int, int]] = []
    for a, b in bonds:
        if a in ring and b in ring:
            adj[a].add(b)
            adj[b].add(a)
            ring_edges.append((a, b) if a < b else (b, a))
    ring_edges = sorted(set(ring_edges))

    cycles: list[set[int]] = []
    for start, nb in ring_edges:
        parent: dict[int, int | None] = {start: None}
        q: deque[int] = deque([start])
        found = None
        while q:
            u = q.popleft()
            for v in adj.get(u, ()):
                if u == start and v == nb:
                    continue
                if v == nb:
                    found = u
                    q.clear()
                    break
                if v in parent:
                    continue
                parent[v] = u
                q.append(v)
            if found is not None:
                break
        if found is None:
            continue
        cyc = {nb, found}
        cur: int | None = found
        while cur is not None and cur != start:
            cur = parent.get(cur)
            if cur is None:
                break
            cyc.add(cur)
        cyc.add(start)
        if len(cyc) >= 3:
            cycles.append(cyc)

    if not cycles:
        # Fallback: connectivity of ring atoms (older behavior).
        seen: set[int] = set()
        comps: list[set[int]] = []
        for start in sorted(ring):
            if start in seen:
                continue
            stack = [start]
            seen.add(start)
            comp: set[int] = set()
            while stack:
                u = stack.pop()
                comp.add(u)
                for v in adj.get(u, ()):
                    if v not in seen:
                        seen.add(v)
                        stack.append(v)
            comps.append(comp)
        return comps

    # Merge cycles that share ≥1 atom (ortho-/peri-fusion, bridges).
    systems: list[set[int]] = [set(c) for c in cycles]
    changed = True
    while changed:
        changed = False
        out: list[set[int]] = []
        for comp in systems:
            placed = False
            for existing in out:
                if existing & comp:
                    existing |= comp
                    placed = True
                    changed = True
                    break
            if not placed:
                out.append(set(comp))
        systems = out
    return systems


def _largest_cycle_in_component(bonds: Sequence[tuple[int, int]], comp: set[int]) -> int:
    """Approximate largest simple cycle size within a ring-system component."""
    from collections import deque

    if len(comp) < 3:
        return len(comp)
    adj: dict[int, set[int]] = {i: set() for i in comp}
    for a, b in bonds:
        if a in comp and b in comp:
            adj[a].add(b)
            adj[b].add(a)
    best = 0
    for start in comp:
        for nb in adj.get(start, ()):
            if nb < start:
                continue
            parent: dict[int, int | None] = {start: None}
            q: deque[int] = deque([start])
            found = None
            while q:
                u = q.popleft()
                for v in adj.get(u, ()):
                    if u == start and v == nb:
                        continue
                    if v == nb:
                        found = u
                        q.clear()
                        break
                    if v in parent:
                        continue
                    parent[v] = u
                    q.append(v)
                if found is not None:
                    break
            if found is None:
                continue
            length = 2
            cur: int | None = found
            while cur is not None and cur != start:
                length += 1
                cur = parent.get(cur)
            best = max(best, length)
    return best


def _unsaturation_in_component(
    bonds: Sequence[tuple[int, int]],
    bond_orders: Sequence[int],
    comp: set[int],
) -> int:
    score = 0
    for (a, b), o in zip(bonds, bond_orders):
        if a in comp and b in comp and o >= 2:
            score += int(o) - 1
    return score


def principal_ring_system(
    bonds: Sequence[tuple[int, int]],
    n_atoms: int,
    *,
    elements: Sequence[str] | None = None,
    bond_orders: Sequence[int] | None = None,
) -> set[int]:
    """
    Select the principal ring system (GR-3.4.1).

    Prefer: most ring atoms (proxy for most fused rings) → largest individual ring →
    greatest unsaturation → most heteroatoms.
    """
    ring = _ring_atom_indices(bonds, n_atoms)
    comps = _ring_system_components(bonds, ring)
    if not comps:
        return set()
    orders = list(bond_orders) if bond_orders is not None else [1] * len(bonds)
    els = list(elements) if elements is not None else ["C"] * n_atoms

    def _key(comp: set[int]) -> tuple:
        n_het = sum(1 for i in comp if i < len(els) and els[i] in _HETERO)
        return (
            len(comp),
            _largest_cycle_in_component(bonds, comp),
            _unsaturation_in_component(bonds, orders, comp),
            n_het,
        )

    return max(comps, key=_key)


def _median_bond_length(
    xs: list[float], ys: list[float], bonds: Sequence[tuple[int, int]]
) -> float:
    lens: list[float] = []
    for i, j in bonds:
        if i < 0 or j < 0 or i >= len(xs) or j >= len(xs):
            continue
        lens.append(math.hypot(xs[j] - xs[i], ys[j] - ys[i]))
    if not lens:
        return 1.0
    return sorted(lens)[len(lens) // 2]


def _orient2d(ax: float, ay: float, bx: float, by: float, cx: float, cy: float) -> float:
    return (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)


def _segments_properly_intersect(
    ax: float,
    ay: float,
    bx: float,
    by: float,
    cx: float,
    cy: float,
    dx: float,
    dy: float,
) -> bool:
    """True when open segments AB and CD properly cross (shared endpoints excluded)."""
    o1 = _orient2d(ax, ay, bx, by, cx, cy)
    o2 = _orient2d(ax, ay, bx, by, dx, dy)
    o3 = _orient2d(cx, cy, dx, dy, ax, ay)
    o4 = _orient2d(cx, cy, dx, dy, bx, by)
    return (o1 > 0) != (o2 > 0) and (o3 > 0) != (o4 > 0)


def count_bond_crossings(
    xs: list[float],
    ys: list[float],
    bonds: Sequence[tuple[int, int]],
) -> int:
    """Count proper crossings between non-adjacent bonds (GR-3.3.4 / software caution)."""
    n = len(xs)
    segs = [(a, b) for a, b in bonds if 0 <= a < n and 0 <= b < n and a != b]
    crossings = 0
    for i in range(len(segs)):
        a, b = segs[i]
        for j in range(i + 1, len(segs)):
            c, d = segs[j]
            if len({a, b, c, d}) < 4:
                continue
            if _segments_properly_intersect(xs[a], ys[a], xs[b], ys[b], xs[c], ys[c], xs[d], ys[d]):
                crossings += 1
    return crossings


def count_near_coincident_bonds(
    xs: list[float],
    ys: list[float],
    bonds: Sequence[tuple[int, int]],
    *,
    median_len: float | None = None,
) -> int:
    """
    Count non-adjacent bonds that nearly coincide (overlap / stack).

    Bridged depictions must avoid exact overlap of distinct bonds (GR-3.3.4).
    """
    n = len(xs)
    med = float(median_len) if median_len and median_len > 0 else _median_bond_length(xs, ys, bonds)
    tol = max(0.08 * med, 1e-3)
    segs = [(a, b) for a, b in bonds if 0 <= a < n and 0 <= b < n and a != b]
    bad = 0
    for i in range(len(segs)):
        a, b = segs[i]
        ax, ay, bx, by = xs[a], ys[a], xs[b], ys[b]
        abx, aby = bx - ax, by - ay
        ab_len = math.hypot(abx, aby) or 1.0
        ux, uy = abx / ab_len, aby / ab_len
        for j in range(i + 1, len(segs)):
            c, d = segs[j]
            if len({a, b, c, d}) < 4:
                continue
            cx, cy, dx, dy = xs[c], ys[c], xs[d], ys[d]
            cdx, cdy = dx - cx, dy - cy
            cd_len = math.hypot(cdx, cdy) or 1.0
            vx, vy = cdx / cd_len, cdy / cd_len
            # Nearly parallel (or anti-parallel).
            if abs(ux * vx + uy * vy) < 0.97:
                continue
            # Midpoint distance and projection overlap.
            mx1, my1 = 0.5 * (ax + bx), 0.5 * (ay + by)
            mx2, my2 = 0.5 * (cx + dx), 0.5 * (cy + dy)
            if math.hypot(mx2 - mx1, my2 - my1) > tol:
                # Also check endpoint-to-segment distances for stacked short bonds.
                def _dist_point_seg(
                    px: float, py: float, qx0: float, qy0: float, qx1: float, qy1: float
                ) -> float:
                    wx, wy = qx1 - qx0, qy1 - qy0
                    den = wx * wx + wy * wy
                    if den < 1e-18:
                        return math.hypot(px - qx0, py - qy0)
                    t = max(0.0, min(1.0, ((px - qx0) * wx + (py - qy0) * wy) / den))
                    return math.hypot(px - (qx0 + t * wx), py - (qy0 + t * wy))

                d_ac = _dist_point_seg(ax, ay, cx, cy, dx, dy)
                d_bc = _dist_point_seg(bx, by, cx, cy, dx, dy)
                d_ca = _dist_point_seg(cx, cy, ax, ay, bx, by)
                d_da = _dist_point_seg(dx, dy, ax, ay, bx, by)
                if min(d_ac, d_bc, d_ca, d_da) > tol:
                    continue
            bad += 1
    return bad


def count_atom_overlaps(
    xs: list[float],
    ys: list[float],
    *,
    median_len: float | None = None,
) -> int:
    """Count atom pairs closer than ~15% of a typical bond (GR-4.3)."""
    n = len(xs)
    if n < 2:
        return 0
    med = float(median_len) if median_len and median_len > 0 else 1.0
    lim = max(0.15 * med, 1e-3)
    bad = 0
    for i in range(n):
        for j in range(i + 1, n):
            if math.hypot(xs[j] - xs[i], ys[j] - ys[i]) < lim:
                bad += 1
    return bad


def layout_overlap_penalty(
    xs: list[float],
    ys: list[float],
    bonds: Sequence[tuple[int, int]],
) -> float:
    """Weighted penalty for crossings, coincident bonds, and atom clashes."""
    med = _median_bond_length(xs, ys, bonds)
    cross = count_bond_crossings(xs, ys, bonds)
    coin = count_near_coincident_bonds(xs, ys, bonds, median_len=med)
    atoms = count_atom_overlaps(xs, ys, median_len=med)
    # Crossings and coincident bonds are severe for bridged / macrocyclic diagrams.
    return 100.0 * cross + 80.0 * coin + 40.0 * atoms


def _iupac_pose_score(
    xs: list[float],
    ys: list[float],
    *,
    elements: Sequence[str],
    bonds: Sequence[tuple[int, int]],
    bond_orders: Sequence[int],
    ring: set[int],
    principal: set[int] | None = None,
) -> float:
    """
    Higher is better. Encodes GR-3.1 / GR-3.2 / GR-3.4 preferences minus overlap.
    """
    n = len(xs)
    if n == 0:
        return 0.0
    mx, my = _mean(xs), _mean(ys)
    width = max(xs) - min(xs)
    height = max(ys) - min(ys)
    score = 0.0
    princ = set(principal) if principal else set(ring)

    # GR-3.1.1: prefer horizontal when elongated.
    if width + height > 1e-9:
        score += 8.0 * (width - height) / (width + height)

    # GR-3.4.2 / GR-3.1.2: heteroatoms (esp. in principal ring system) toward the right.
    princ_het_x = [xs[i] for i, el in enumerate(elements) if el in _HETERO and i in princ]
    ring_het_x = [xs[i] for i, el in enumerate(elements) if el in _HETERO and i in ring]
    acyc_het_x = [xs[i] for i, el in enumerate(elements) if el in _HETERO and i not in ring]
    if princ_het_x:
        score += 14.0 * (_mean(princ_het_x) - mx)
        princ_het_y = [ys[i] for i, el in enumerate(elements) if el in _HETERO and i in princ]
        score += 4.0 * (my - _mean(princ_het_y))
    elif ring_het_x:
        score += 12.0 * (_mean(ring_het_x) - mx)
        ring_het_y = [ys[i] for i, el in enumerate(elements) if el in _HETERO and i in ring]
        score += 3.0 * (my - _mean(ring_het_y))
    if acyc_het_x:
        # Secondary to principal-ring placement (GR-3.4.1 / 3.4.3).
        score += 6.0 * (_mean(acyc_het_x) - mx)

    # GR-3.1.3 / GR-3.4.3: principal ring system toward bottom-left; substituents spread out.
    if princ and len(princ) < n:
        px = [xs[i] for i in princ]
        py = [ys[i] for i in princ]
        score += 14.0 * (mx - _mean(px))
        score += 14.0 * (my - _mean(py))
    elif ring and len(ring) < n:
        ring_x = [xs[i] for i in ring]
        ring_y = [ys[i] for i in ring]
        score += 6.0 * (mx - _mean(ring_x))
        score += 6.0 * (my - _mean(ring_y))

    # Prefer the principal system's own long axis roughly horizontal.
    if len(princ) >= 3:
        pxs = [xs[i] for i in princ]
        pys = [ys[i] for i in princ]
        pw = max(pxs) - min(pxs)
        ph = max(pys) - min(pys)
        if pw + ph > 1e-9:
            score += 10.0 * (pw - ph) / (pw + ph)

    # GR-3.2.2: branching C=O oxygens preferentially above carbon.
    for (a, b), o in zip(bonds, bond_orders):
        if o != 2 or a < 0 or b < 0 or a >= n or b >= n:
            continue
        ea, eb = elements[a], elements[b]
        if ea == "C" and eb == "O":
            score += 4.0 * (ys[b] - ys[a])
        elif eb == "C" and ea == "O":
            score += 4.0 * (ys[a] - ys[b])

    # GR-3.4.2 isolated hex: prefer a near-vertical bond on the left.
    focus = princ if princ else ring
    if len(focus) == 6 and n <= 8:
        left_x = min(xs[i] for i in focus)
        vert = 0.0
        for a, b in bonds:
            if a not in focus or b not in focus:
                continue
            if min(xs[a], xs[b]) > left_x + 1e-6:
                continue
            dx, dy = xs[b] - xs[a], ys[b] - ys[a]
            length = math.hypot(dx, dy) or 1.0
            vert = max(vert, abs(dy) / length)
        score += 5.0 * vert

    score -= layout_overlap_penalty(xs, ys, bonds)
    return score


def _make_horizontal(
    xs: list[float],
    ys: list[float],
    bonds: Sequence[tuple[int, int]],
    *,
    principal: set[int] | None = None,
) -> tuple[list[float], list[float]]:
    """
    Align main axis to +X (GR-3.1.1).

    When a principal ring system is present (GR-3.4.1), align *its* principal axis
    first so orientation is driven by the largest ring system, not a long side chain.
    """
    xs, ys = list(xs), list(ys)
    princ = set(principal or ())
    if len(princ) >= 3:
        pxs = [xs[i] for i in sorted(princ)]
        pys = [ys[i] for i in sorted(princ)]
        pca = _principal_axis_angle(pxs, pys)
        xs, ys = rotate_points(xs, ys, -pca)
        pxs = [xs[i] for i in princ]
        pys = [ys[i] for i in princ]
        pw = max(pxs) - min(pxs) if pxs else 0.0
        ph = max(pys) - min(pys) if pys else 0.0
        if ph > pw + 1e-9:
            xs, ys = rotate_points(xs, ys, math.pi / 2.0)
    else:
        pca = _principal_axis_angle(xs, ys)
        xs, ys = rotate_points(xs, ys, -pca)
        width = max(xs) - min(xs) if xs else 0.0
        height = max(ys) - min(ys) if ys else 0.0
        if height > width + 1e-9:
            xs, ys = rotate_points(xs, ys, math.pi / 2.0)
            width, height = height, width
        if width > 1e-9 and height / max(width, 1e-12) > 0.85:
            bond_ang = _longest_bond_angle(xs, ys, bonds)
            if bond_ang is not None and abs(math.sin(bond_ang)) > 0.35:
                xs, ys = rotate_points(xs, ys, -bond_ang)
                if max(ys) - min(ys) > max(xs) - min(xs) + 1e-9:
                    xs, ys = rotate_points(xs, ys, math.pi / 2.0)
    return xs, ys


def apply_iupac_orientation(
    xs: list[float],
    ys: list[float],
    *,
    elements: Sequence[str],
    bonds: Sequence[tuple[int, int]],
    bond_orders: Sequence[int] | None = None,
) -> tuple[list[float], list[float]]:
    """
    Orient a 2D layout per IUPAC GR-3 (Y-up chemistry coordinates).

    Chooses among discrete reflections / 180° turns after horizontal alignment so that:
    - GR-3.4.1 / 3.4.3: largest (principal) ring system drives orientation and sits bottom-left
    - GR-3.1.1 / GR-3.2.1: main axis roughly horizontal
    - GR-3.1.2 / GR-3.4.2: heteroatoms (esp. ring) toward the right (and slightly bottom)
    - GR-3.2.2: branching carbonyl oxygens preferentially above the chain
    - GR-3.3.4: bond crossings / coincident bonds are heavily penalized
    """
    n = len(xs)
    if n == 0 or len(ys) != n:
        return xs, ys
    xs = list(xs)
    ys = list(ys)
    orders = list(bond_orders) if bond_orders is not None else [1] * len(bonds)
    ring = _ring_atom_indices(bonds, n)
    principal = principal_ring_system(bonds, n, elements=elements, bond_orders=orders)

    base_x, base_y = _make_horizontal(xs, ys, bonds, principal=principal)
    candidates: list[tuple[list[float], list[float]]] = []
    for flip_x in (False, True):
        for flip_y in (False, True):
            cx, cy = list(base_x), list(base_y)
            if flip_x:
                cx, cy = reflect_x(cx, cy)
            if flip_y:
                cx, cy = reflect_y(cx, cy)
            candidates.append((cx, cy))
    # Compact / polycyclic: also try ±90° from the horizontalized pose.
    focus = principal if principal else ring
    if focus:
        fxs = [base_x[i] for i in focus]
        fys = [base_y[i] for i in focus]
        width = max(fxs) - min(fxs) if fxs else 0.0
        height = max(fys) - min(fys) if fys else 0.0
    else:
        width = max(base_x) - min(base_x) if base_x else 0.0
        height = max(base_y) - min(base_y) if base_y else 0.0
    if width > 1e-9 and height / max(width, 1e-12) > 0.7:
        for ang in (math.pi / 2.0, -math.pi / 2.0):
            rx, ry = rotate_points(base_x, base_y, ang)
            for flip_x in (False, True):
                for flip_y in (False, True):
                    cx, cy = list(rx), list(ry)
                    if flip_x:
                        cx, cy = reflect_x(cx, cy)
                    if flip_y:
                        cx, cy = reflect_y(cx, cy)
                    candidates.append((cx, cy))

    best = candidates[0]
    best_score = float("-inf")
    for cx, cy in candidates:
        sc = _iupac_pose_score(
            cx,
            cy,
            elements=elements,
            bonds=bonds,
            bond_orders=orders,
            ring=ring,
            principal=principal,
        )
        if sc > best_score:
            best_score = sc
            best = (cx, cy)
    return best


def resolve_layout_overlaps(
    xs: list[float],
    ys: list[float],
    *,
    elements: Sequence[str],
    bonds: Sequence[tuple[int, int]],
    bond_orders: Sequence[int] | None = None,
) -> tuple[list[float], list[float]]:
    """
    Re-pick an IUPAC pose when the current layout has bond/atom overlaps.

    Safe to call after macrocycle hex refine; prefers discrete flips over continuous morphs.
    """
    orders = list(bond_orders) if bond_orders is not None else [1] * len(bonds)
    pen = layout_overlap_penalty(xs, ys, bonds)
    if pen < 1e-6:
        # Still allow orientation improvement without overlap present.
        return apply_iupac_orientation(xs, ys, elements=elements, bonds=bonds, bond_orders=orders)
    return apply_iupac_orientation(xs, ys, elements=elements, bonds=bonds, bond_orders=orders)


def apply_iupac_orientation_to_conformer(
    conf,
    *,
    elements: Sequence[str],
    bonds: Sequence[tuple[int, int]],
    bond_orders: Sequence[int] | None = None,
) -> None:
    """In-place IUPAC orientation of an RDKit conformer (Y-up)."""
    na = conf.GetNumAtoms()
    xs = [float(conf.GetAtomPosition(i).x) for i in range(na)]
    ys = [float(conf.GetAtomPosition(i).y) for i in range(na)]
    xs, ys = apply_iupac_orientation(
        xs, ys, elements=elements, bonds=bonds, bond_orders=bond_orders
    )
    set_conformer_xy(conf, xs, ys)


def resolve_layout_overlaps_on_conformer(
    conf,
    *,
    elements: Sequence[str],
    bonds: Sequence[tuple[int, int]],
    bond_orders: Sequence[int] | None = None,
) -> None:
    """In-place overlap-aware reorientation of an RDKit conformer (Y-up)."""
    na = conf.GetNumAtoms()
    xs = [float(conf.GetAtomPosition(i).x) for i in range(na)]
    ys = [float(conf.GetAtomPosition(i).y) for i in range(na)]
    xs, ys = resolve_layout_overlaps(
        xs, ys, elements=elements, bonds=bonds, bond_orders=bond_orders
    )
    set_conformer_xy(conf, xs, ys)
