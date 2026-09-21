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

"""Join two table-cell strings with a delimiter (Data → Table → Join Columns)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

JoinDelimiterMode = Literal[
    "comma",
    "comma_space",
    "semicolon",
    "tab",
    "pipe",
    "space",
    "none",
    "custom",
]

JOIN_DELIMITER_MODES: tuple[tuple[str, JoinDelimiterMode], ...] = (
    ("Comma (,)", "comma"),
    ("Comma + space (, )", "comma_space"),
    ("Semicolon (;)", "semicolon"),
    ("Tab", "tab"),
    ("Pipe (|)", "pipe"),
    ("Space", "space"),
    ("None (concatenate)", "none"),
    ("Custom", "custom"),
)

_MODE_DELIM: dict[str, str] = {
    "comma": ",",
    "comma_space": ", ",
    "semicolon": ";",
    "tab": "\t",
    "pipe": "|",
    "space": " ",
    "none": "",
}


@dataclass(frozen=True)
class JoinColumnsParams:
    """Settings for joining two table columns into one new column."""

    left_column: str
    right_column: str
    mode: JoinDelimiterMode
    custom: str
    output_column: str
    skip_empty: bool = True


def unescape_join_delimiter(raw: str) -> str:
    """Expand ``\\t`` / ``\\n`` in a custom join delimiter (any length)."""
    return (raw or "").replace("\\t", "\t").replace("\\n", "\n")


def resolve_join_delimiter(mode: JoinDelimiterMode, custom: str = "") -> str:
    """Return the delimiter string for *mode*."""
    if mode == "custom":
        return unescape_join_delimiter(custom)
    if mode not in _MODE_DELIM:
        raise ValueError(f"Unknown delimiter mode: {mode!r}")
    return _MODE_DELIM[mode]


def join_two_values(
    left: str,
    right: str,
    delimiter: str,
    *,
    skip_empty: bool = True,
) -> str:
    """Join two cell strings with *delimiter*.

    When *skip_empty* is true, a blank side is omitted (no extra delimiter).
    Both blank yields an empty string. Otherwise both sides are concatenated
    even when empty.
    """
    a = str(left or "")
    b = str(right or "")
    if skip_empty:
        a_blank = not a.strip()
        b_blank = not b.strip()
        if a_blank and b_blank:
            return ""
        if a_blank:
            return b
        if b_blank:
            return a
    return f"{a}{delimiter}{b}"


def default_join_output_name(left: str, right: str) -> str:
    """Default new-column name from the two source headers."""
    a = (left or "").strip() or "Column"
    b = (right or "").strip() or "Column"
    if a == b:
        return a
    return f"{a}_{b}"
