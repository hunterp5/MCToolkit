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

"""Main-table columns written from matched molecular pair results."""

from __future__ import annotations

from collections import defaultdict

from .mmp_analysis import MmpPair


def is_mmp_result_header(header: str) -> bool:
    """True for table columns written by MMP analysis (partners / transforms / deltas)."""
    h = (header or "").strip()
    if not h:
        return False
    if h in ("MMP_Partners", "MMP_Transforms"):
        return True
    return h.startswith("MMP_Delta_")


def assemble_mmp_table_annotations(
    pairs: list[MmpPair],
    *,
    activity_column: str,
) -> tuple[list[tuple[int, dict[str, str]]], list[str]]:
    """
    Build per-molecule annotation columns for write-back to the main table.

    Columns: ``MMP_Partners``, ``MMP_Transforms``, ``MMP_Delta_<activity>``.
    Multiple pairs for one OID are joined with ``; `` (sorted by |Δ| desc).
    """
    delta_header = f"MMP_Delta_{activity_column}" if activity_column else "MMP_Delta"
    headers = ["MMP_Partners", "MMP_Transforms", delta_header]
    by_oid: dict[int, list[tuple[float, str, str, str]]] = defaultdict(list)

    for p in pairs:
        by_oid[p.oid_a].append(
            (abs(p.delta_activity), str(p.oid_b), p.transform, _fmt_delta(p.delta_activity))
        )
        rev = f"{p.sidechain_b}>>{p.sidechain_a}"
        by_oid[p.oid_b].append(
            (abs(p.delta_activity), str(p.oid_a), rev, _fmt_delta(-p.delta_activity))
        )

    rows: list[tuple[int, dict[str, str]]] = []
    for oid, items in by_oid.items():
        items.sort(key=lambda t: (-t[0], t[1], t[2]))
        partners = "; ".join(t[1] for t in items)
        transforms = "; ".join(t[2] for t in items)
        deltas = "; ".join(t[3] for t in items)
        rows.append(
            (
                oid,
                {
                    "MMP_Partners": partners,
                    "MMP_Transforms": transforms,
                    delta_header: deltas,
                },
            )
        )
    rows.sort(key=lambda r: r[0])
    return rows, headers


def _fmt_delta(value: float) -> str:
    text = f"{value:.4g}"
    if text.startswith("-") or text == "0":
        return text
    return f"+{text}"
