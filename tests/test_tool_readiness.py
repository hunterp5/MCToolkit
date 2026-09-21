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

"""Tool-readiness decisions. No Qt, no qapp fixture, no main window."""

from __future__ import annotations

import sys

from mctoolkit.workflows.tool_readiness import (
    ToolBlocker,
    plan_activity_analysis,
    plan_calculator,
    plan_table_readiness,
    plan_text_column_tool,
)


def test_workflow_layer_does_not_pull_in_qt():
    """The point of the layer: importing a decision must not load PySide6."""
    for name in list(sys.modules):
        if name.startswith("mctoolkit.workflows"):
            del sys.modules[name]
    qt_already_loaded = "PySide6.QtWidgets" in sys.modules
    import mctoolkit.workflows.tool_readiness  # noqa: F401

    if not qt_already_loaded:
        assert "PySide6.QtWidgets" not in sys.modules


def test_empty_table_blocks_on_no_table():
    plan = plan_table_readiness(headers=[], row_count=0)
    assert not plan.is_ready
    assert plan.blocked_by is ToolBlocker.NO_TABLE


def test_headers_alone_are_enough_when_rows_are_not_required():
    assert plan_table_readiness(headers=["SMILES"], row_count=0).is_ready


def test_row_requirement_blocks_an_empty_table():
    plan = plan_table_readiness(headers=["SMILES"], row_count=0, require_rows=True)
    assert plan.blocked_by is ToolBlocker.NO_ROWS


def test_populated_table_is_ready():
    assert plan_table_readiness(headers=["SMILES"], row_count=3, require_rows=True).is_ready


def test_activity_analysis_needs_rows():
    plan = plan_activity_analysis(headers=["SMILES"], row_count=0, activity_columns=["IC50"])
    assert plan.blocked_by is ToolBlocker.NO_ROWS
    assert plan.activity_columns == ()


def test_activity_analysis_needs_a_numeric_column():
    plan = plan_activity_analysis(headers=["SMILES"], row_count=5, activity_columns=[])
    assert plan.blocked_by is ToolBlocker.NO_ACTIVITY_COLUMN


def test_blank_activity_column_names_are_not_usable():
    plan = plan_activity_analysis(headers=["SMILES"], row_count=5, activity_columns=["", "   "])
    assert plan.blocked_by is ToolBlocker.NO_ACTIVITY_COLUMN


def test_activity_analysis_returns_usable_columns():
    plan = plan_activity_analysis(
        headers=["SMILES", "IC50", "MW"],
        row_count=5,
        activity_columns=["IC50", "", "MW"],
    )
    assert plan.is_ready
    assert plan.activity_columns == ("IC50", "MW")
    assert plan.blocked_by is None


def test_text_column_tool_needs_rows_and_a_text_column():
    assert (
        plan_text_column_tool(headers=["SMILES"], row_count=0, text_columns=["SMILES"]).blocked_by
        is ToolBlocker.NO_ROWS
    )
    assert (
        plan_text_column_tool(headers=["SMILES"], row_count=3, text_columns=[]).blocked_by
        is ToolBlocker.NO_TEXT_COLUMN
    )
    assert plan_text_column_tool(headers=["SMILES"], row_count=3, text_columns=["SMILES"]).is_ready


def test_calculator_blocks_when_policy_disabled():
    plan = plan_calculator(headers=["SMILES"], disabled=True)
    assert plan.blocked_by is ToolBlocker.CALCULATOR_DISABLED
    assert plan_calculator(headers=["SMILES"], disabled=False).is_ready
    assert plan_calculator(headers=[], disabled=False).blocked_by is ToolBlocker.NO_TABLE
