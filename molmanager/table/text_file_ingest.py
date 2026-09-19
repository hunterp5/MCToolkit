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

"""Text-first file ingest helpers (CSV/SMILES lines without RDKit on the load path)."""

from __future__ import annotations

import csv
import io


_TABLE_DELIMS = (",", ";", "\t", "|")
_SMILES_FIELD_NAMES = frozenset({"smiles", "smi", "structure", "mol"})


def find_smiles_column(fieldnames: list[str]) -> str | None:
    """Pick the structure column from a tabular header, else the first field."""
    names = list(fieldnames or [])
    for fn in names:
        if str(fn).lower() in _SMILES_FIELD_NAMES:
            return fn
    return names[0] if names else None


def _header_fields(line: str, delimiter: str) -> list[str]:
    return next(csv.reader(io.StringIO(line), delimiter=delimiter), [])


def sniff_table_delimiter(sample: str, *, default: str = ",") -> str:
    """Pick comma, semicolon, tab, or pipe from a CSV/TSV sample (ChEMBL uses ``;``)."""
    text = (sample or "").lstrip("\ufeff")
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        return default
    header = lines[0]
    ranked: list[tuple[int, int, int, str]] = []
    prefer = {",": 4, "\t": 3, ";": 2, "|": 1}
    for delim in _TABLE_DELIMS:
        fields = [f.strip() for f in _header_fields(header, delim) if f is not None]
        n = len(fields)
        if n <= 1:
            continue
        names = [f.lower() for f in fields]
        has_smi = int(
            any(
                name in _SMILES_FIELD_NAMES or name.endswith("smiles") or name.endswith(" smiles")
                for name in names
            )
        )
        ranked.append((has_smi, n, prefer.get(delim, 0), delim))
    if ranked:
        ranked.sort(reverse=True)
        return ranked[0][3]
    try:
        dialect = csv.Sniffer().sniff("\n".join(lines[:20]), delimiters=",;\t|")
    except csv.Error:
        return default
    delim = str(getattr(dialect, "delimiter", "") or "")
    return delim if delim in _TABLE_DELIMS else default


def csv_row_to_cells(
    row: dict[str, str],
    *,
    smi_col: str,
    fieldnames: list[str],
) -> dict[str, str] | None:
    """Build table cell values from one CSV/TSV row; returns None when SMILES is empty."""
    smi = (row.get(smi_col) or "").strip()
    if not smi:
        return None
    cells: dict[str, str] = {"SMILES": smi}
    for h in fieldnames:
        if h == smi_col:
            continue
        cells[h] = str(row.get(h, "") or "")
    return cells


def smi_line_to_cells(line: str) -> dict[str, str] | None:
    """Build cells for a one-SMILES-per-line text file."""
    smi = (line or "").strip()
    if not smi or smi.lower().startswith("smiles"):
        return None
    return {"SMILES": smi}


def is_ingest_cell_batch(batch: list) -> bool:
    """True when a worker batch carries pre-built cell dicts instead of RDKit mols."""
    return bool(batch) and isinstance(batch[0], dict)
