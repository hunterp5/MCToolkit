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

"""Unit tests for analysis_job_support helpers (no full GUI)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from molmanager.ui.analysis_job_support import (
    finish_analysis_pairs,
    report_analysis_failure,
)


def test_finish_analysis_pairs_empty_returns_none(monkeypatch):
    infos: list[tuple] = []
    monkeypatch.setattr(
        "molmanager.ui.analysis_job_support.QMessageBox.information",
        lambda *a, **k: infos.append(a),
    )
    app = SimpleNamespace(
        _finish_tool_progress=MagicMock(),
        status_label=SimpleNamespace(setText=MagicMock()),
    )
    assert finish_analysis_pairs(app, "Tool", [], empty_message="none") is None
    app._finish_tool_progress.assert_called_once_with("Tool")
    assert infos and infos[0][2] == "none"


def test_finish_analysis_pairs_returns_list(monkeypatch):
    monkeypatch.setattr(
        "molmanager.ui.analysis_job_support.QMessageBox.information",
        lambda *a, **k: None,
    )
    app = SimpleNamespace(
        _finish_tool_progress=MagicMock(),
        status_label=SimpleNamespace(setText=MagicMock()),
    )
    out = finish_analysis_pairs(app, "Tool", [1, 2], empty_message="none")
    assert out == [1, 2]


def test_report_analysis_failure(monkeypatch):
    warns: list[tuple] = []
    monkeypatch.setattr(
        "molmanager.ui.analysis_job_support.QMessageBox.warning",
        lambda *a, **k: warns.append(a),
    )
    app = SimpleNamespace(
        _clear_tool_progress=MagicMock(),
        status_label=SimpleNamespace(setText=MagicMock()),
    )
    report_analysis_failure(app, "Tool", "", fallback="failed")
    app._clear_tool_progress.assert_called_once()
    assert warns and warns[0][2] == "failed"
