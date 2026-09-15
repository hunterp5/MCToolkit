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

"""Build (oid, mol, activity) records for MMP-family and SALI tools (no Qt)."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any, TypeVar

MolT = TypeVar("MolT")


def build_oid_mol_activity_records(
    mol_data: Sequence[tuple[int, MolT]],
    *,
    activity_for_oid: Callable[[int], float | None],
) -> list[tuple[int, MolT, float]]:
    """Keep scoped molecules that have a numeric activity value."""
    out: list[tuple[int, MolT, float]] = []
    for oid, mol in mol_data:
        activity = activity_for_oid(int(oid))
        if activity is None:
            continue
        out.append((int(oid), mol, float(activity)))
    return out


def parse_activity_float(raw: Any) -> float | None:
    """Parse a table cell into a float activity, or ``None`` if empty/invalid."""
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        return float(text)
    except (TypeError, ValueError):
        return None
