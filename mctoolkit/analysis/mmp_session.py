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
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with mctoolkit. If not, see <https://www.gnu.org/licenses/>.

"""Session payload for the MMP Transform Ledger (no UI widgets)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from .mmp_analysis import MmpPair


def serialize_mmp_ledger_payload(
    pairs: Sequence[MmpPair] | None,
    *,
    activity_column: str = "",
) -> dict[str, Any] | None:
    """Session sidecar for Transform Ledger reopen (pairs + activity column)."""
    if not pairs:
        return None
    return {
        "activity_column": str(activity_column or ""),
        "pairs": [
            {
                "oid_a": int(p.oid_a),
                "oid_b": int(p.oid_b),
                "smiles_a": str(p.smiles_a or ""),
                "smiles_b": str(p.smiles_b or ""),
                "activity_a": float(p.activity_a),
                "activity_b": float(p.activity_b),
                "delta_activity": float(p.delta_activity),
                "transform": str(p.transform or ""),
                "core": str(p.core or ""),
                "sidechain_a": str(p.sidechain_a or ""),
                "sidechain_b": str(p.sidechain_b or ""),
            }
            for p in pairs
        ],
    }


def deserialize_mmp_ledger_payload(raw: Any) -> tuple[list[MmpPair], str]:
    """Parse ``serialize_mmp_ledger_payload`` output; returns ``(pairs, activity_column)``."""
    if not isinstance(raw, dict):
        return [], ""
    activity_column = str(raw.get("activity_column") or "")
    items = raw.get("pairs")
    if not isinstance(items, list):
        return [], activity_column
    pairs: list[MmpPair] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            pairs.append(
                MmpPair(
                    oid_a=int(item["oid_a"]),
                    oid_b=int(item["oid_b"]),
                    smiles_a=str(item.get("smiles_a") or ""),
                    smiles_b=str(item.get("smiles_b") or ""),
                    activity_a=float(item["activity_a"]),
                    activity_b=float(item["activity_b"]),
                    delta_activity=float(item["delta_activity"]),
                    transform=str(item.get("transform") or ""),
                    core=str(item.get("core") or ""),
                    sidechain_a=str(item.get("sidechain_a") or ""),
                    sidechain_b=str(item.get("sidechain_b") or ""),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    return pairs, activity_column
