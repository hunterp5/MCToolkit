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

"""Unit tests for analysis_job_support helpers (no full GUI)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from mctoolkit.ui.analysis_job_support import (
    enqueue_process_queue_job,
    ensure_table_ready_for_tool,
    finish_analysis_pairs,
    prepare_scoped_structure_mols,
    report_analysis_failure,
    report_cancellable_job_failure,
)


def test_finish_analysis_pairs_empty_returns_none(monkeypatch):
    infos: list[tuple] = []
    monkeypatch.setattr(
        "mctoolkit.ui.analysis_job_support.QMessageBox.information",
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
        "mctoolkit.ui.analysis_job_support.QMessageBox.information",
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
        "mctoolkit.ui.analysis_job_support.QMessageBox.warning",
        lambda *a, **k: warns.append(a),
    )
    app = SimpleNamespace(
        _clear_tool_progress=MagicMock(),
        status_label=SimpleNamespace(setText=MagicMock()),
    )
    report_analysis_failure(app, "Tool", "", fallback="failed")
    app._clear_tool_progress.assert_called_once()
    assert warns and warns[0][2] == "failed"


def test_ensure_table_ready_for_tool_no_headers(monkeypatch):
    infos: list[tuple] = []
    monkeypatch.setattr(
        "mctoolkit.ui.analysis_job_support.QMessageBox.information",
        lambda *a, **k: infos.append(a),
    )
    app = SimpleNamespace(headers=[], _table_model=SimpleNamespace(rowCount=lambda: 0))
    assert ensure_table_ready_for_tool(app, "Cluster") is False
    assert infos


def test_ensure_table_ready_for_tool_ok():
    app = SimpleNamespace(headers=["SMILES"], _table_model=SimpleNamespace(rowCount=lambda: 1))
    assert ensure_table_ready_for_tool(app, "Cluster") is True


def test_prepare_scoped_structure_mols_empty_selection(monkeypatch):
    infos: list[tuple] = []
    monkeypatch.setattr(
        "mctoolkit.ui.analysis_job_support.QMessageBox.information",
        lambda *a, **k: infos.append(a),
    )
    app = SimpleNamespace(
        _abort_if_only_selected_but_empty=MagicMock(return_value=True),
        _selected_oids_set=MagicMock(return_value=set()),
        collect_scoped_table_mols=MagicMock(),
    )
    assert (
        prepare_scoped_structure_mols(
            app,
            tool_label="Cluster",
            structure_source="SMILES",
            only_selected=True,
        )
        is None
    )
    app.collect_scoped_table_mols.assert_not_called()


def test_prepare_scoped_structure_mols_too_few(monkeypatch):
    infos: list[tuple] = []
    monkeypatch.setattr(
        "mctoolkit.ui.analysis_job_support.QMessageBox.information",
        lambda *a, **k: infos.append(a),
    )
    app = SimpleNamespace(
        _abort_if_only_selected_but_empty=MagicMock(return_value=False),
        _selected_oids_set=MagicMock(return_value=set()),
        collect_scoped_table_mols=MagicMock(return_value=[(1, object())]),
    )
    assert (
        prepare_scoped_structure_mols(
            app,
            tool_label="Cluster",
            structure_source="SMILES",
            only_selected=False,
            min_mols=2,
            too_few_message="need two",
        )
        is None
    )
    assert infos and infos[0][2] == "need two"


def test_enqueue_process_queue_job_returns_id():
    app = SimpleNamespace(
        _begin_tool_progress=MagicMock(),
        process_queue=SimpleNamespace(enqueue=MagicMock(return_value="job-1")),
    )
    factory = MagicMock()
    assert (
        enqueue_process_queue_job(app, "Clustering", 3, factory, queue_label="Cluster (3)")
        == "job-1"
    )
    app._begin_tool_progress.assert_called_once_with("Clustering", 3, job_id="job-1")
    app.process_queue.enqueue.assert_called_once_with("Cluster (3)", factory)


def test_report_cancellable_job_failure_cancelled(monkeypatch):
    warns: list[tuple] = []
    monkeypatch.setattr(
        "mctoolkit.ui.analysis_job_support.QMessageBox.warning",
        lambda *a, **k: warns.append(a),
    )
    after = MagicMock()
    app = SimpleNamespace(
        _finish_tool_progress=MagicMock(),
        status_label=SimpleNamespace(setText=MagicMock()),
        _consume_partial_results_notice=MagicMock(return_value="Partial kept."),
    )
    report_cancellable_job_failure(
        app,
        "Cluster",
        "Cancelled.",
        progress_label="Clustering",
        failure_fallback="failed",
        after_finish=after,
    )
    after.assert_called_once()
    app.status_label.setText.assert_called_once_with("Partial kept.")
    assert not warns


def test_report_cancellable_job_failure_error(monkeypatch):
    warns: list[tuple] = []
    monkeypatch.setattr(
        "mctoolkit.ui.analysis_job_support.QMessageBox.warning",
        lambda *a, **k: warns.append(a),
    )
    app = SimpleNamespace(
        _finish_tool_progress=MagicMock(),
        status_label=SimpleNamespace(setText=MagicMock()),
    )
    report_cancellable_job_failure(
        app,
        "Cluster",
        "boom",
        progress_label="Clustering",
        failure_fallback="failed",
    )
    assert warns and warns[0][2] == "boom"
