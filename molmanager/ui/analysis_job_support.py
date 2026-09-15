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

"""Shared enqueue / record prep / finish handlers for MMP-family and SALI tools.

Thin UI adapters (mixins) call these helpers so dialog → records → process-queue
wiring stays in one place (AnalysisJobRunner pattern without a heavy class).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QDialog, QMessageBox
from rdkit import Chem

from ..services.activity_records import build_oid_mol_activity_records, parse_activity_float

WorkerFactory = Callable[..., Any]


def activity_value_for_table_oid(
    app: Any,
    oid: int,
    *,
    activity_column: str,
    activity_col_index: int,
) -> float | None:
    """Read a numeric activity for *oid* from cell text or backing value."""
    row = app.logical_row_for_oid(oid)
    if row < 0:
        return None
    raw = (app._table_cell_text(row, activity_col_index) or "").strip()
    if not raw:
        raw = (
            app._table_model.backing_value_for_row_header(row, activity_column) or ""
        ).strip()
    return parse_activity_float(raw)


def ensure_activity_analysis_ready(
    app: Any,
    tool_label: str,
    *,
    missing_activity_message: str,
) -> list[str] | None:
    """Return numeric activity columns, or ``None`` after informing the user."""
    if not app.headers or app._table_model.rowCount() == 0:
        QMessageBox.information(
            app,
            tool_label,
            "Load a table with at least one row first.",
        )
        return None
    from .dialogs.mmp import activity_columns_for_mmp

    activity_cols = activity_columns_for_mmp(app, only_selected=False)
    if not activity_cols:
        QMessageBox.information(app, tool_label, missing_activity_message)
        return None
    return activity_cols


def show_activity_tool_dialog(
    app: Any,
    dialog: QDialog,
    *,
    on_accepted: Callable[[QDialog], None],
) -> None:
    """Standard modeless tool-dialog show + accepted handoff."""
    app._prepare_tool_dialog(dialog)
    dialog.setAttribute(Qt.WA_DeleteOnClose, True)
    dialog.accepted.connect(lambda *_, dlg=dialog: on_accepted(dlg))
    dialog.show()


def prepare_scoped_activity_mol_records(
    app: Any,
    *,
    tool_label: str,
    structure_source: str,
    activity_column: str,
    only_selected: bool,
    min_records: int = 2,
) -> list[tuple[int, Chem.Mol, float]] | None:
    """Validate scope + activity column and build MMP/SALI worker records.

    Returns ``None`` after informing the user when the job should not start.
    """
    if app._abort_if_only_selected_but_empty(
        only_selected, app._selected_oids_set(), tool_label
    ):
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

    mol_data = app.collect_scoped_table_mols(
        structure_source, only_selected=only_selected
    )
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
    app: Any,
    tool_label: str,
    n_items: int,
    factory: Callable,
) -> None:
    """Begin tool progress and enqueue a process-queue worker factory."""
    app._begin_tool_progress(tool_label, int(n_items))
    app.process_queue.enqueue(f"{tool_label} ({int(n_items)} rows)", factory)


def start_scoped_activity_job(
    app: Any,
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
    app: Any,
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
    app: Any,
    tool_label: str,
    message: str,
    *,
    fallback: str,
) -> None:
    """Clear progress and show a warning for a failed analysis job."""
    app._clear_tool_progress()
    app.status_label.setText("Ready.")
    QMessageBox.warning(app, tool_label, message or fallback)
