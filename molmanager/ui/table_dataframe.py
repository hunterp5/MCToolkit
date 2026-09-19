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

"""Read the main compound table into pandas for analysis tools.

These helpers used to live in the Statistics dialog module. QSAR, MMP,
dimensionality reduction, and medchem-space only needed a DataFrame, so
importing them from there also constructed the six-tab Statistics UI.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import TYPE_CHECKING

import pandas as pd

if TYPE_CHECKING:
    from .main_window import ChemistryWorkspaceWindow

__all__ = [
    "iter_scoped_table_analysis_rows",
    "numeric_subset",
    "selected_table_column_headers",
    "table_to_dataframe",
]


def iter_scoped_table_analysis_rows(
    app: ChemistryWorkspaceWindow,
    *,
    visible_only: bool = True,
    only_selected: bool = False,
) -> Iterator[tuple[int, dict[str, str]]]:
    """Yield (table_row_index, row_dict) for rows included in analysis scope."""
    m = app._table_model
    ncols = m.columnCount()
    nrows = m.rowCount()
    if not app.headers or ncols < 1 or nrows < 1:
        return

    selected_oids: set[int] | None = None
    if only_selected:
        selected_oids = app._selected_oids_set()

    visible_rows: set[int] | None = None
    if visible_only:
        vis = app._visible_source_row_indices()
        visible_rows = None if vis is None else set(vis)

    for r in range(nrows):
        if visible_rows is not None and r not in visible_rows:
            continue
        if only_selected:
            t0 = m.cell_text(r, 0)
            if not t0.isdigit() or int(t0) not in (selected_oids or set()):
                continue
        row: dict[str, str] = {}
        for c in range(ncols):
            if c >= len(app.headers):
                break
            name = app.headers[c]
            if name == "Structure":
                continue
            text = (m.cell_text(r, c) or "").strip()
            if not text:
                text = (m.backing_value_for_row_header(r, name) or "").strip()
            row[name] = text
        yield r, row


def table_to_dataframe(
    app: ChemistryWorkspaceWindow,
    *,
    visible_only: bool = True,
    only_selected: bool = False,
) -> tuple[pd.DataFrame, list[int]]:
    """Build a DataFrame from the main table (skips Structure) and parallel source row indices."""
    rows: list[dict[str, str]] = []
    source_rows: list[int] = []
    for r, row in iter_scoped_table_analysis_rows(
        app, visible_only=visible_only, only_selected=only_selected
    ):
        source_rows.append(r)
        rows.append(row)
    return pd.DataFrame(rows), source_rows


def selected_table_column_headers(app: ChemistryWorkspaceWindow) -> list[str]:
    """Distinct data-column header names currently spanned by the main-table selection."""
    sm = app.table.selectionModel()
    if sm is None or not app.headers:
        return []
    view_cols = sorted({ix.column() for ix in sm.selectedIndexes() if ix.isValid()})
    names: list[str] = []
    for col in view_cols:
        if col <= 0 or col >= len(app.headers):
            continue
        name = app.headers[col]
        if name in ("ID_HIDDEN", "Structure"):
            continue
        if name not in names:
            names.append(name)
    return names


def numeric_subset(df: pd.DataFrame, *, exclude_id: bool = True) -> pd.DataFrame:
    """Columns that have at least one finite numeric value; optionally drop ID_HIDDEN."""
    if df.empty:
        return df
    cols = [c for c in df.columns if not (exclude_id and c == "ID_HIDDEN")]
    num = df[cols].apply(pd.to_numeric, errors="coerce")
    keep = [c for c in num.columns if num[c].notna().any()]
    return num[keep] if keep else pd.DataFrame(index=df.index)
