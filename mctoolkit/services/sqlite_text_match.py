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

"""SQLite text-match fragments for search and filter pushdown (no Qt)."""

from __future__ import annotations


def sqlite_text_match_clause(
    header_quoted: str,
    needle: str,
    *,
    partial: bool,
    case_sensitive: bool,
) -> tuple[str, list[object]]:
    """
    SQLite fragment for substring or whole-cell text match.

    ``LIKE`` is case-insensitive for ASCII in SQLite, so case-sensitive partial
    matches use ``instr`` (case-sensitive) instead of ``LIKE``.
    """
    qh = header_quoted
    if partial:
        if case_sensitive:
            return f'(instr("{qh}", ?) > 0)', [needle]
        return f'(LOWER("{qh}") LIKE ? ESCAPE "\\")', [f"%{needle.lower()}%"]
    if case_sensitive:
        return f'("{qh}" = ?)', [needle]
    return f'(LOWER("{qh}") = ?)', [needle.lower()]
