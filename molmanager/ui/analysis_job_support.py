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

"""Shared enqueue / record prep / finish handlers for analysis and predict tools.

Thin UI adapters (mixins and dialogs) call these helpers so dialog → scoped mols →
process-queue wiring stays in one place (AnalysisJobRunner pattern without a heavy class).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any, Protocol

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QMessageBox

from ..services.activity_records import build_oid_mol_activity_records, parse_activity_float
from ..workflows.tool_readiness import ToolBlocker, plan_activity_analysis, plan_table_readiness
from .app_roles import JobScheduler, ProgressChrome, TableData, TableSelection
from .tool_dialog_scope import abort_if_only_selected_but_empty, prepare_tool_dialog

WorkerFactory = Callable[..., Any]


class AnalysisJobOps(Protocol):
    """Window forwards scoped analysis jobs need beyond the kernel roles."""

    def logical_row_for_oid(self, oid: int) -> int: ...
    def cell_text(self, row: int, col: int) -> str: ...
    def collect_scoped_table_mols(
        self, src: str, *, only_selected: bool = False, only_visible: bool = False
    ) -> list[tuple[int, object]]: ...
    def _clear_tool_progress(self, *, status_message: str | None = None) -> None: ...


class AnalysisJobHost(
    TableData,
    TableSelection,
    ProgressChrome,
    JobScheduler,
    AnalysisJobOps,
    Protocol,
):
    """What MMP / SALI / cluster / predict enqueue helpers read from the window.

    Dialog show/abort still go through ``tool_dialog_scope`` via getattr.
    """


_BLOCKER_TEXT = {
    ToolBlocker.NO_TABLE: "Open a file or start a session first.",
    ToolBlocker.NO_ROWS: "Load a table with at least one row first.",
}


def activity_value_for_table_oid(
    app: AnalysisJobHost,
    oid: int,
    *,
    activity_column: str,
    activity_col_index: int,
) -> float | None:
    """Read a numeric activity for *oid* from cell text or backing value."""
    row = app.logical_row_for_oid(oid)
    if row < 0:
        return None
    raw = (app.cell_text(row, activity_col_index) or "").strip()
    if not raw:
        raw = (app._table_model.backing_value_for_row_header(row, activity_column) or "").strip()
    return parse_activity_float(raw)


def ensure_table_ready_for_tool(
    app: AnalysisJobHost,
    tool_label: str,
    *,
    require_rows: bool = False,
    empty_message: str | None = None,
) -> bool:
    """Return True when the table can host *tool_label*; otherwise inform and return False."""
    plan = plan_table_readiness(
        headers=app.headers,
        row_count=app._table_model.rowCount(),
        require_rows=require_rows,
    )
    if plan.is_ready:
        return True
    QMessageBox.information(app, tool_label, empty_message or _BLOCKER_TEXT[plan.blocked_by])
    return False


def ensure_activity_analysis_ready(
    app: AnalysisJobHost,
    tool_label: str,
    *,
    missing_activity_message: str,
) -> list[str] | None:
    """Return numeric activity columns, or ``None`` after informing the user."""
    from .dialogs.mmp import activity_columns_for_mmp

    plan = plan_activity_analysis(
        headers=app.headers,
        row_count=app._table_model.rowCount(),
        activity_columns=activity_columns_for_mmp(app, only_selected=False),
    )
    if plan.is_ready:
        return list(plan.activity_columns)
    message = (
        missing_activity_message
        if plan.blocked_by is ToolBlocker.NO_ACTIVITY_COLUMN
        else "Load a table with at least one row first."
    )
    QMessageBox.information(app, tool_label, message)
    return None


def show_activity_tool_dialog(
    app: AnalysisJobHost,
    dialog: QDialog,
    *,
    on_accepted: Callable[[QDialog], None],
) -> None:
    """Standard modeless tool-dialog show + accepted handoff."""
    prepare_tool_dialog(app, dialog)
    dialog.setAttribute(Qt.WA_DeleteOnClose, True)
    dialog.accepted.connect(lambda *_, dlg=dialog: on_accepted(dlg))
    dialog.show()


def prepare_scoped_structure_mols(
    app: AnalysisJobHost,
    *,
    tool_label: str,
    structure_source: str,
    only_selected: bool,
    min_mols: int = 1,
    empty_message: str | None = None,
    too_few_message: str | None = None,
) -> list[tuple[int, object]] | None:
    """Validate scope and collect ``(oid, mol)`` pairs for structure-only jobs.

    Returns ``None`` after informing the user when the job should not start.
    """
    if abort_if_only_selected_but_empty(app, only_selected, app._selected_oids_set(), tool_label):
        return None
    mol_data = app.collect_scoped_table_mols(structure_source, only_selected=only_selected)
    if not mol_data:
        QMessageBox.information(
            app,
            tool_label,
            empty_message or "No valid structures were found for the selected source and scope.",
        )
        return None
    if len(mol_data) < int(min_mols):
        QMessageBox.information(
            app,
            tool_label,
            too_few_message
            or f"Need at least {int(min_mols)} row(s) with valid structures in this scope.",
        )
        return None
    return list(mol_data)


def prepare_scoped_activity_mol_records(
    app: AnalysisJobHost,
    *,
    tool_label: str,
    structure_source: str,
    activity_column: str,
    only_selected: bool,
    min_records: int = 2,
) -> list[tuple[int, object, float]] | None:
    """Validate scope + activity column and build MMP/SALI worker records.

    Returns ``None`` after informing the user when the job should not start.
    """
    if abort_if_only_selected_but_empty(app, only_selected, app._selected_oids_set(), tool_label):
        return None
    if not activity_column or str(activity_column).startswith("("):
        QMessageBox.information(app, tool_label, "Select a numeric activity column.")
        return None
    if activity_column not in app.headers:
        QMessageBox.information(
            app,
            tool_label,
            f"Activity column “{activity_column}” is not in the table.",
        )
        return None

    mol_data = app.collect_scoped_table_mols(structure_source, only_selected=only_selected)
    if not mol_data:
        QMessageBox.information(
            app,
            tool_label,
            "No valid structures were found for the selected source and scope.",
        )
        app.status_label.setText("Ready.")
        return None

    act_col = app.headers.index(activity_column)
    records = build_oid_mol_activity_records(
        mol_data,
        activity_for_oid=lambda oid: activity_value_for_table_oid(
            app,
            oid,
            activity_column=activity_column,
            activity_col_index=act_col,
        ),
    )
    if len(records) < int(min_records):
        QMessageBox.information(
            app,
            tool_label,
            "Need at least two molecules with both a structure and a numeric activity value.",
        )
        app.status_label.setText("Ready.")
        return None
    return records


def enqueue_process_queue_job(
    app: AnalysisJobHost,
    tool_label: str,
    n_items: int,
    factory: Callable,
    *,
    queue_label: str | None = None,
) -> Any:
    """Begin tool progress and enqueue a process-queue worker factory.

    Returns the queue job id from ``process_queue.enqueue``.
    """
    app._begin_tool_progress(tool_label, int(n_items))
    label = queue_label or f"{tool_label} ({int(n_items)} rows)"
    return app.process_queue.enqueue(label, factory)


def start_scoped_structure_job(
    app: AnalysisJobHost,
    *,
    tool_label: str,
    structure_source: str,
    only_selected: bool,
    make_worker: WorkerFactory,
    min_mols: int = 1,
    queue_label: str | None = None,
    empty_message: str | None = None,
    too_few_message: str | None = None,
) -> Any | None:
    """Prepare scoped mols and enqueue ``make_worker(mols, …)``.

    ``make_worker`` receives ``(mols, *, cancel_event, signals, progress_state)``
    and must return a process-queue runnable. Returns the queue job id, or ``None``
    when the job did not start.
    """
    mols = prepare_scoped_structure_mols(
        app,
        tool_label=tool_label,
        structure_source=structure_source,
        only_selected=only_selected,
        min_mols=min_mols,
        empty_message=empty_message,
        too_few_message=too_few_message,
    )
    if not mols:
        return None
    ps = app._tool_progress_state
    return enqueue_process_queue_job(
        app,
        tool_label,
        len(mols),
        lambda ev, rows=mols, sigs=app.signals, prog=ps: make_worker(
            rows,
            cancel_event=ev,
            signals=sigs,
            progress_state=prog,
        ),
        queue_label=queue_label,
    )


def start_scoped_activity_job(
    app: AnalysisJobHost,
    *,
    tool_label: str,
    structure_source: str,
    activity_column: str,
    only_selected: bool,
    make_worker: WorkerFactory,
    min_records: int = 2,
) -> bool:
    """Prepare scoped records and enqueue ``make_worker(records, …)``.

    ``make_worker`` receives ``(records, *, cancel_event, signals, progress_state)``
    and must return a process-queue runnable.
    """
    records = prepare_scoped_activity_mol_records(
        app,
        tool_label=tool_label,
        structure_source=structure_source,
        activity_column=activity_column,
        only_selected=only_selected,
        min_records=min_records,
    )
    if not records:
        return False
    ps = app._tool_progress_state
    enqueue_process_queue_job(
        app,
        tool_label,
        len(records),
        lambda ev, rec=records, sigs=app.signals, prog=ps: make_worker(
            rec,
            cancel_event=ev,
            signals=sigs,
            progress_state=prog,
        ),
    )
    return True


def finish_analysis_pairs(
    app: AnalysisJobHost,
    tool_label: str,
    pairs: Sequence[Any] | None,
    *,
    empty_message: str,
) -> list[Any] | None:
    """Finish tool progress; return pairs list or ``None`` when empty (after UI notice)."""
    app._finish_tool_progress(tool_label)
    out = list(pairs or [])
    if not out:
        app.status_label.setText("Ready.")
        QMessageBox.information(app, tool_label, empty_message)
        return None
    return out


def report_analysis_failure(
    app: AnalysisJobHost,
    tool_label: str,
    message: str,
    *,
    fallback: str,
) -> None:
    """Clear progress and show a warning for a failed analysis job."""
    app._clear_tool_progress()
    app.status_label.setText("Ready.")
    QMessageBox.warning(app, tool_label, message or fallback)


def report_cancellable_job_failure(
    app: AnalysisJobHost,
    tool_label: str,
    message: str,
    *,
    progress_label: str,
    failure_fallback: str,
    cancelled_status: str | None = None,
    after_finish: Callable[[], None] | None = None,
) -> None:
    """Finish progress for cancellable queue jobs (Cluster, Diverse subset, predictors).

    Cancelled jobs update the status bar only; other failures show a warning.
    """
    app._finish_tool_progress(progress_label)
    if after_finish is not None:
        after_finish()
    if message == "Cancelled.":
        notice = getattr(app, "_consume_partial_results_notice", None)
        text = cancelled_status
        if text is None and callable(notice):
            text = notice() or "Cancelled."
        if text is None:
            text = "Cancelled."
        app.status_label.setText(text)
        return
    app.status_label.setText("Ready.")
    QMessageBox.warning(app, tool_label, message or failure_fallback)
