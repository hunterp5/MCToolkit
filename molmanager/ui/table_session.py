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

"""Selection, chemistry-column lookup, and the sticky visible-row cache."""

from __future__ import annotations

from typing import Any, Protocol

from .app_roles import ProgressChrome, TableData, TableSelection
from .table_session_chemistry import TableSessionChemistry
from .table_session_selection import TableSessionSelection


class TableSessionHost(TableData, TableSelection, ProgressChrome, Protocol):
    """What table selection and chemistry lookup need from the window.

    Kernel selection caches stay on the window (``plot_table_sync`` and filters
    read them there). Chunked-selection job state lives on ``TableSession``.
    Plot/dock leftovers that do not fit this contract are reached with getattr.
    """

    _in_programmatic_table_selection: bool
    _column_selection_anchor: int | None
    _plot_table_select_pending: Any
    _structure_field_override: Any

    def cell_text(self, row: int, col: int) -> str: ...
    def canonical_structure_key_from_smiles(self, smiles: str) -> str | None: ...
    def calculate_global_bounds(self) -> None: ...
    def apply_filters(self) -> None: ...


class TableSession(TableSessionSelection, TableSessionChemistry):
    """Table selection + molecule access. Kernel caches stay on the window."""

    def __init__(self, app: TableSessionHost) -> None:
        self._app = app
        self._table_selection_job_gen = 0
        self._table_selection_ctx = None
        self._invalidate_visible_source_rows_cache()
