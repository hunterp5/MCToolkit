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

"""Decide whether a table-driven tool can start, and with which activity columns.

Pure decisions: no Qt, no main window. ``ui/analysis_job_support.py`` adapts these
results into ``QMessageBox`` text.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum


class ToolBlocker(Enum):
    """Why a tool cannot start. The UI adapter maps these to user-facing text."""

    NO_TABLE = "no_table"
    NO_ROWS = "no_rows"
    NO_ACTIVITY_COLUMN = "no_activity_column"


@dataclass(frozen=True)
class TableReadiness:
    """Whether the compound table can host a tool."""

    blocked_by: ToolBlocker | None = None

    @property
    def is_ready(self) -> bool:
        return self.blocked_by is None


@dataclass(frozen=True)
class ActivityAnalysisPlan:
    """Activity columns an analysis may offer, or why it cannot run."""

    activity_columns: tuple[str, ...] = ()
    blocked_by: ToolBlocker | None = None

    @property
    def is_ready(self) -> bool:
        return self.blocked_by is None


def plan_table_readiness(
    *,
    headers: Sequence[str],
    row_count: int,
    require_rows: bool = False,
) -> TableReadiness:
    """Decide whether a tool can run against a table of *headers* and *row_count* rows."""
    if not headers:
        return TableReadiness(blocked_by=ToolBlocker.NO_TABLE)
    if require_rows and int(row_count) <= 0:
        return TableReadiness(blocked_by=ToolBlocker.NO_ROWS)
    return TableReadiness()


def plan_activity_analysis(
    *,
    headers: Sequence[str],
    row_count: int,
    activity_columns: Sequence[str],
) -> ActivityAnalysisPlan:
    """Decide whether an activity analysis (MMP, cliffs, SALI, pair network) can run.

    Activity analyses need a populated table and at least one usable numeric column.
    """
    table = plan_table_readiness(headers=headers, row_count=row_count, require_rows=True)
    if not table.is_ready:
        return ActivityAnalysisPlan(blocked_by=table.blocked_by)
    usable = tuple(str(name) for name in activity_columns if str(name or "").strip())
    if not usable:
        return ActivityAnalysisPlan(blocked_by=ToolBlocker.NO_ACTIVITY_COLUMN)
    return ActivityAnalysisPlan(activity_columns=usable)
