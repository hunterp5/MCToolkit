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

"""Split delimited table-cell text into fields (Data → Table → Split Column)."""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from typing import Literal

from .utils import safe_float

DelimiterMode = Literal["auto", "comma", "semicolon", "tab", "pipe", "space", "custom"]
KeepMode = Literal["all", "largest", "smallest"]

DELIMITER_MODES: tuple[tuple[str, DelimiterMode], ...] = (
    ("Auto (detect)", "auto"),
    ("Comma (,)", "comma"),
    ("Semicolon (;)", "semicolon"),
    ("Tab", "tab"),
    ("Pipe (|)", "pipe"),
    ("Space", "space"),
    ("Custom", "custom"),
)

_MODE_CHAR: dict[str, str] = {
    "comma": ",",
    "semicolon": ";",
    "tab": "\t",
    "pipe": "|",
    "space": " ",
}

_AUTO_CHARS: tuple[str, ...] = (",", ";", "\t", "|")
MAX_SPLIT_COLUMNS = 256


@dataclass(frozen=True)
class SplitColumnParams:
    """Settings for splitting one table column into new fields."""

    source_column: str
    mode: DelimiterMode
    custom: str
    prefix: str
    keep: KeepMode = "all"


def unescape_custom_delimiter(raw: str) -> str:
    """Turn a custom-delimiter field into a single split character."""
    text = (raw or "").replace("\\t", "\t").replace("\\n", "\n")
    if not text:
        return ""
    return text[0]


def detect_delimiter(texts: list[str]) -> str:
    """Pick the delimiter that best splits *texts* (punctuation first, then whitespace)."""
    scores = {d: 0 for d in _AUTO_CHARS}
    nonempty = 0
    whitespace_multi = 0
    for raw in texts:
        text = str(raw or "")
        if not text.strip():
            continue
        nonempty += 1
        for d in _AUTO_CHARS:
            scores[d] += text.count(d)
        if len(text.split()) > 1:
            whitespace_multi += 1
    if nonempty and max(scores.values()) > 0:
        return max(scores, key=scores.get)
    if whitespace_multi:
        return " "
    return ","


def split_cell_text(text: str, delimiter: str) -> list[str]:
    """Split one cell with *delimiter* (``\" \"`` uses whitespace split)."""
    raw = str(text or "")
    if delimiter == " ":
        return raw.split()
    if not delimiter:
        stripped = raw.strip()
        return [stripped] if stripped else []
    if not raw.strip():
        return []
    reader = csv.reader(io.StringIO(raw), delimiter=delimiter, skipinitialspace=True)
    try:
        row = next(reader)
    except (StopIteration, csv.Error):
        stripped = raw.strip()
        return [stripped] if stripped else []
    return [part.strip() for part in row]


def extreme_split_field(parts: list[str], *, largest: bool) -> str:
    """Return the largest or smallest field; prefer numeric values, then text."""
    numeric: list[tuple[float, int, str]] = []
    textual: list[tuple[str, int, str]] = []
    for i, raw in enumerate(parts):
        token = str(raw or "").strip()
        if not token:
            continue
        num = safe_float(token)
        if num is not None:
            numeric.append((float(num), i, token))
        else:
            textual.append((token.casefold(), i, token))
    if numeric:
        if largest:
            return max(numeric, key=lambda item: (item[0], -item[1]))[2]
        return min(numeric, key=lambda item: (item[0], item[1]))[2]
    if textual:
        if largest:
            return max(textual, key=lambda item: (item[0], -item[1]))[2]
        return min(textual, key=lambda item: (item[0], item[1]))[2]
    return ""


def apply_keep_mode(parts_per_row: list[list[str]], keep: KeepMode) -> list[list[str]]:
    """Reduce each row to one field when *keep* is largest or smallest."""
    if keep not in ("largest", "smallest"):
        return parts_per_row
    largest = keep == "largest"
    out: list[list[str]] = []
    for parts in parts_per_row:
        chosen = extreme_split_field(parts, largest=largest)
        out.append([chosen] if chosen else [""])
    return out


def split_column_values(
    texts: list[str],
    mode: DelimiterMode,
    *,
    custom: str = "",
) -> tuple[str, list[list[str]]]:
    """
    Split each cell.

    Returns ``(resolved_delimiter, parts_per_row)``. Auto inspects the whole
    column so every row uses the same delimiter.
    """
    if mode == "auto":
        delim = detect_delimiter(texts)
    elif mode == "custom":
        delim = unescape_custom_delimiter(custom)
        if not delim:
            raise ValueError("Enter a custom delimiter character.")
    else:
        delim = _MODE_CHAR.get(mode, "")
        if not delim:
            raise ValueError(f"Unknown delimiter mode: {mode!r}")
    parts = [split_cell_text(t, delim) for t in texts]
    return delim, parts


def output_column_names(prefix: str, n: int) -> list[str]:
    """``Prefix_1`` … ``Prefix_n`` (1-based)."""
    base = (prefix or "").strip() or "Split"
    count = max(0, int(n))
    return [f"{base}_{i}" for i in range(1, count + 1)]


def pad_split_rows(parts_per_row: list[list[str]], n_cols: int) -> list[list[str]]:
    """Right-pad/truncate each row to *n_cols* fields."""
    width = max(0, int(n_cols))
    out: list[list[str]] = []
    for parts in parts_per_row:
        row = list(parts[:width])
        if len(row) < width:
            row.extend([""] * (width - len(row)))
        out.append(row)
    return out


def split_width(parts_per_row: list[list[str]]) -> int:
    """Number of output columns (capped)."""
    widest = max((len(p) for p in parts_per_row), default=0)
    return min(widest, MAX_SPLIT_COLUMNS)
