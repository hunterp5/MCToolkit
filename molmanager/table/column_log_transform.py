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

"""Column-level log10 / antilog transforms for the compound table."""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping

from ..chem.molecule_conversion import safe_float


def format_transformed_number(value: float) -> str:
    """Stable string form for transformed numeric cells."""
    if not math.isfinite(value):
        return ""
    text = f"{value:.12g}"
    if text in ("-0", "-0.0"):
        return "0"
    return text


def column_can_apply_log10(cell_texts: Iterable[str]) -> bool:
    """
    True when the column has at least one positive finite numeric value and no
    parseable numeric value that cannot be converted with log10 (≤ 0).
    """
    saw_positive = False
    for raw in cell_texts:
        value = safe_float(raw)
        if value is None:
            continue
        if not math.isfinite(value) or value <= 0.0:
            return False
        saw_positive = True
    return saw_positive


def transform_column_values_log10(
    oid_to_text: Mapping[int, str],
    *,
    to_log: bool,
) -> dict[int, str]:
    """
    Return ``{oid: new_text}`` only for cells that change.

    Empty / non-numeric cells are left unchanged (omitted from the result).
    When ``to_log`` is True, only positive finite values are transformed.
    When False, finite values are converted with ``10 ** x``.
    """
    out: dict[int, str] = {}
    for oid, raw in oid_to_text.items():
        value = safe_float(raw)
        if value is None or not math.isfinite(value):
            continue
        try:
            if to_log:
                if value <= 0.0:
                    continue
                new_value = math.log10(value)
            else:
                new_value = 10.0**value
        except (OverflowError, ValueError):
            continue
        if not math.isfinite(new_value):
            continue
        new_text = format_transformed_number(new_value)
        if new_text != str(raw):
            out[int(oid)] = new_text
    return out


def column_can_apply_precision(cell_texts: Iterable[str]) -> bool:
    """True when the column has at least one finite numeric value."""
    for raw in cell_texts:
        value = safe_float(raw)
        if value is not None and math.isfinite(value):
            return True
    return False


def format_number_precision(value: float, decimals: int) -> str:
    """Format *value* to a fixed number of decimal places (0–12)."""
    places = max(0, min(12, int(decimals)))
    if not math.isfinite(value):
        return ""
    if places == 0:
        text = f"{round(value):.0f}"
    else:
        text = f"{value:.{places}f}"
    if text in ("-0", "-0.0") or (text.startswith("-0.") and set(text[3:]) <= {"0"}):
        return "0" if places == 0 else f"0.{'0' * places}"
    return text


def transform_column_values_precision(
    oid_to_text: Mapping[int, str],
    *,
    decimals: int,
) -> dict[int, str]:
    """Return ``{oid: new_text}`` for numeric cells whose formatted text changes."""
    out: dict[int, str] = {}
    for oid, raw in oid_to_text.items():
        value = safe_float(raw)
        if value is None or not math.isfinite(value):
            continue
        new_text = format_number_precision(value, decimals)
        if new_text != str(raw):
            out[int(oid)] = new_text
    return out
