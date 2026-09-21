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

"""Validate sketch diagrams against selected IUPAC graphical representation rules."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from .bonds import BOND_STEREO_HASH, BOND_STEREO_WEDGE, _bond_unpack
from .constants import SKETCH_MEDIAN_BOND_PX
from .iupac_style import (
    ATOM_OVERLAP_PX,
    BOND_LENGTH_MAX_FRAC,
    BOND_LENGTH_MIN_FRAC,
    NEAR_COLLINEAR_DEG,
)


@dataclass(frozen=True)
class IupacIssue:
    """One validation finding (atom and/or bond indices may be unset)."""

    code: str
    message: str
    atom_ids: tuple[int, ...] = ()
    bond_indices: tuple[int, ...] = ()


def _median(vals: list[float], default: float) -> float:
    if not vals:
        return default
    s = sorted(vals)
    return s[len(s) // 2]


def validate_iupac_sketch(
    nodes: list[dict[str, Any]],
    bonds: list[tuple[int, int, int, int]],
    *,
    chiral_center_ids: set[int] | None = None,
    median_bond_px: float | None = None,
) -> list[IupacIssue]:
    """Return IUPAC-related issues for the current sketch (empty when clean)."""
    issues: list[IupacIssue] = []
    if not nodes:
        return issues
    by_id = {int(n["id"]): n for n in nodes}
    chiral = set(chiral_center_ids or ())

    lengths: list[float] = []
    for bi, bond in enumerate(bonds):
        a, b, order, stereo = _bond_unpack(bond)
        na, nb = by_id.get(a), by_id.get(b)
        if na is None or nb is None:
            continue
        dx = float(nb["pos"].x() - na["pos"].x())
        dy = float(nb["pos"].y() - na["pos"].y())
        length = math.hypot(dx, dy)
        lengths.append(length)
        if order != 1 and stereo in (BOND_STEREO_WEDGE, BOND_STEREO_HASH):
            issues.append(
                IupacIssue(
                    "stereo_on_multiple",
                    "Wedge/hash stereo must be drawn on single bonds only.",
                    atom_ids=(a, b),
                    bond_indices=(bi,),
                )
            )
        if stereo in (BOND_STEREO_WEDGE, BOND_STEREO_HASH) and a in chiral and b in chiral:
            issues.append(
                IupacIssue(
                    "stereo_between_centers",
                    "Avoid wedge/hash bonds that connect two stereocenters (ST-0.5).",
                    atom_ids=(a, b),
                    bond_indices=(bi,),
                )
            )

    med = (
        float(median_bond_px)
        if median_bond_px and median_bond_px > 0
        else _median(lengths, float(SKETCH_MEDIAN_BOND_PX))
    )
    for bi, bond in enumerate(bonds):
        a, b, _o, _s = _bond_unpack(bond)
        na, nb = by_id.get(a), by_id.get(b)
        if na is None or nb is None:
            continue
        length = math.hypot(
            float(nb["pos"].x() - na["pos"].x()),
            float(nb["pos"].y() - na["pos"].y()),
        )
        if length < med * BOND_LENGTH_MIN_FRAC or length > med * BOND_LENGTH_MAX_FRAC:
            issues.append(
                IupacIssue(
                    "bond_length",
                    "Bond length is far from the diagram median (GR-1.1).",
                    atom_ids=(a, b),
                    bond_indices=(bi,),
                )
            )

    # Near-collinear single bonds at an atom (looks like one long bond).
    adj: dict[int, list[tuple[int, int]]] = {int(n["id"]): [] for n in nodes}
    for bi, bond in enumerate(bonds):
        a, b, order, _s = _bond_unpack(bond)
        if order != 1:
            continue
        if a in adj and b in adj:
            adj[a].append((b, bi))
            adj[b].append((a, bi))
    for nid, neigh in adj.items():
        if len(neigh) < 2:
            continue
        n0 = by_id.get(nid)
        if n0 is None:
            continue
        # Hypervalent S/P often have near-linear ligand angles in 2D; not a GR-1.5 issue.
        el = str(n0.get("element") or "")
        if el in ("S", "P", "Se", "As"):
            continue
        x0, y0 = float(n0["pos"].x()), float(n0["pos"].y())
        angs: list[tuple[float, int, int]] = []
        for oid, bi in neigh:
            on = by_id.get(oid)
            if on is None:
                continue
            angs.append((math.atan2(float(on["pos"].y()) - y0, float(on["pos"].x()) - x0), oid, bi))
        angs.sort(key=lambda t: t[0])
        for i in range(len(angs)):
            a1, _o1, bi1 = angs[i]
            a2, _o2, bi2 = angs[(i + 1) % len(angs)]
            gap = (a2 - a1) % (2.0 * math.pi)
            # Near 180° opening between two singles → collinear appearance.
            if abs(gap - math.pi) <= math.radians(NEAR_COLLINEAR_DEG):
                issues.append(
                    IupacIssue(
                        "near_collinear",
                        "Near-collinear single bonds can look like one bond (GR-1.5).",
                        atom_ids=(nid,),
                        bond_indices=(bi1, bi2),
                    )
                )

    ids = list(by_id.keys())
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            ni, nj = by_id[ids[i]], by_id[ids[j]]
            d = math.hypot(
                float(nj["pos"].x() - ni["pos"].x()),
                float(nj["pos"].y() - ni["pos"].y()),
            )
            if d < ATOM_OVERLAP_PX:
                issues.append(
                    IupacIssue(
                        "atom_overlap",
                        "Atoms overlap or nearly overlap (GR-4.3).",
                        atom_ids=(ids[i], ids[j]),
                    )
                )

    # Bond–bond crossings / near-coincident stacking (GR-3.3.4 software caution).
    from .iupac_orient import count_bond_crossings, count_near_coincident_bonds

    xs = [float(by_id[i]["pos"].x()) for i in ids]
    ys = [float(by_id[i]["pos"].y()) for i in ids]
    id_to_idx = {nid: i for i, nid in enumerate(ids)}
    bond_pairs = []
    for bi, bond in enumerate(bonds):
        a, b, _o, _s = _bond_unpack(bond)
        if a in id_to_idx and b in id_to_idx:
            bond_pairs.append((id_to_idx[a], id_to_idx[b]))
    if count_bond_crossings(xs, ys, bond_pairs) > 0:
        issues.append(
            IupacIssue(
                "bond_crossing",
                "Non-adjacent bonds cross; prefer a bridged/fused pose without crossings (GR-3.3.4).",
            )
        )
    if count_near_coincident_bonds(xs, ys, bond_pairs, median_len=med) > 0:
        issues.append(
            IupacIssue(
                "bond_overlap",
                "Distinct bonds nearly coincide or stack; avoid overlapping bonds (GR-3.3.4).",
            )
        )
    return issues


def format_iupac_issues(issues: list[IupacIssue], *, limit: int = 3) -> str:
    if not issues:
        return ""
    msgs = [iss.message for iss in issues[:limit]]
    extra = len(issues) - limit
    text = "; ".join(msgs)
    if extra > 0:
        text += f" (+{extra} more)"
    return text
