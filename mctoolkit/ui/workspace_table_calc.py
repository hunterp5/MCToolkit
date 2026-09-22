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

"""Calculator, random columns, split/join columns, fingerprint similarity, and diverse subset."""

from __future__ import annotations

from typing import Any, Protocol

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QMessageBox
from ..platform_support.config import load_config
from ..chem.molecule_conversion import safe_float
from ..workers import CustomCalcWorker
from .analysis_job_support import (
    ensure_calculator_ready,
    ensure_table_ready_for_tool,
    ensure_text_column_tool_ready,
    report_cancellable_job_failure,
)
from .singleton_modeless_dialog import reuse_or_show_modeless_singleton
from .strings import TOOL_CALCULATOR, TOOL_JOIN_COLUMNS, TOOL_RANDOM_NUMBER, TOOL_SPLIT_COLUMN


class TableCalcOps(Protocol):
    """Diverse-subset handle and selection writeback used by the calculator tools."""

    _diverse_subset_signals: Any
    _fp_similarity_signals: Any

    def _finish_oid_override_selection(self, *args: Any, **kwargs: Any) -> Any: ...


class TableCalcTools:
    def __init__(self, app) -> None:
        self._app = app

    def _run_calculator_from_dialog(self, dlg) -> None:
        from .dialogs import CalculatorDialog

        if not isinstance(dlg, CalculatorDialog):
            return
        self._app.new_c = dlg.name_input.text().strip()
        if not self._app.new_c:
            QMessageBox.warning(self._app, TOOL_CALCULATOR, "Enter a name for the new column.")
            return
        self._app.new_c = self._app._unique_table_column_names([self._app.new_c])[0]
        expr = dlg.expr_input.text().strip()
        if not expr:
            QMessageBox.warning(self._app, TOOL_CALCULATOR, "Enter an expression to evaluate.")
            return
        only_selected = dlg.only_selected_rows()
        allowed = self._app._selected_oids_set() if only_selected else None
        if self._app._abort_if_only_selected_but_empty(only_selected, allowed, TOOL_CALCULATOR):
            return
        numeric_vars = [v for v in self._app.global_bounds.keys() if v in self._app.headers]
        from .table_dataframe import scoped_oid_column_snapshot

        oids_list, texts = scoped_oid_column_snapshot(self._app, numeric_vars, allowed_oids=allowed)
        if not oids_list:
            QMessageBox.information(
                self._app, TOOL_CALCULATOR, "No rows to process for this scope."
            )
            self._app.status_label.setText("Ready.")
            return
        row_data = (oids_list, texts)
        ps = self._app._tool_progress_state
        self._app._begin_tool_progress("Calculator…", len(oids_list))
        self._app.process_queue.enqueue(
            f"Calculator ({len(oids_list)} rows)",
            lambda ev, rd=row_data, ex=expr, sigs=self._app.signals, p=ps: CustomCalcWorker(
                rd, ex, sigs, cancel_event=ev, progress_state=p
            ),
        )

    def open_random_number_dialog(self) -> None:
        if not ensure_table_ready_for_tool(self._app, TOOL_RANDOM_NUMBER, require_rows=True):
            return
        from .dialogs import RandomNumberDialog

        d = RandomNumberDialog(len(self._app._selected_logical_rows()), self._app)
        self._app._prepare_tool_dialog(d)
        d.setAttribute(Qt.WA_DeleteOnClose, True)
        d.accepted.connect(lambda *_, dlg=d: self._on_random_number_dialog_accepted(dlg))
        d.show()

    def open_random_molecule_dialog(self) -> None:
        from .dialogs import RandomMoleculeDialog

        d = RandomMoleculeDialog(self._app)
        self._app._prepare_tool_dialog(d)
        d.setAttribute(Qt.WA_DeleteOnClose, True)
        d.show()

    def _on_random_number_dialog_accepted(self, d) -> None:
        from ..table.random_number_columns import generate_random_values

        p = d.params()
        col = p.column_name
        if not col:
            QMessageBox.warning(
                self._app, TOOL_RANDOM_NUMBER, "Enter a name for the output column."
            )
            return
        only_selected = d.only_selected_rows()
        allowed = self._app._selected_oids_set() if only_selected else None
        if self._app._abort_if_only_selected_but_empty(only_selected, allowed, TOOL_RANDOM_NUMBER):
            return
        oids = self._scoped_table_oids(allowed)
        if not oids:
            QMessageBox.information(
                self._app, TOOL_RANDOM_NUMBER, "No rows to process for this scope."
            )
            self._app.status_label.setText("Ready.")
            return
        try:
            values = generate_random_values(len(oids), p.params)
        except ValueError as exc:
            QMessageBox.warning(
                self._app, TOOL_RANDOM_NUMBER, str(exc) or "Invalid random-number settings."
            )
            return
        rows = [(int(oid), {col: text}) for oid, text in zip(oids, values)]
        written = self._app.on_calc_finished(
            rows, [col], progress_label=TOOL_RANDOM_NUMBER, immediate=True
        )
        final_col = written[0] if written else col
        self._app.status_label.setText(
            f'{TOOL_RANDOM_NUMBER}: column "{final_col}" updated ({len(rows)} row(s)).'
        )

    def open_calculator(self):
        if load_config().disable_custom_calc:
            ensure_calculator_ready(self._app, disabled=True)
            return
        if not self._app.headers:
            return
        numeric_vars = list(self._app.global_bounds.keys())
        from .dialogs import CalculatorDialog

        def _factory():
            d = CalculatorDialog(numeric_vars, len(self._app._selected_logical_rows()), self._app)
            d.setModal(False)
            d.setAttribute(Qt.WA_DeleteOnClose, True)
            d.apply_requested.connect(lambda dlg=d: self._run_calculator_from_dialog(dlg))
            self._app._prepare_tool_dialog(d)
            return d

        reuse_or_show_modeless_singleton(
            self._app,
            "_calculator_dialog",
            _factory,
            on_reused_visible=lambda dlg: self._app._sync_dialog_only_selected_scope(dlg),
        )

    def _ensure_blank_table_headers(self) -> None:
        """Create ID and Structure columns so Add Row/Column work before a file is loaded."""
        if self._app.headers and self._app._table_model.columnCount() >= 2:
            return
        self._app.headers = ["ID_HIDDEN", "Structure"]
        self._app.table.setSortingEnabled(False)
        self._app._table_model.clear_rows()
        self._app._table_model.set_headers(list(self._app.headers))
        self._app.table.setColumnHidden(0, True)
        set_stack = getattr(self._app, "_set_workspace_stack_index", None)
        if callable(set_stack):
            set_stack(1)

    def add_blank_table_row(self, count: int | None = None) -> None:
        """Append empty rows (Data → Table → Operations → Add Row). *count* skips the dialog."""
        from .dialogs.add_table import MAX_ADD_ROWS, AddTableRowsDialog
        from .main_window.table_undo_commands import UndoAddBlankRowCommand

        if count is None:
            dlg = AddTableRowsDialog(self._app)
            if dlg.exec() != QDialog.Accepted:
                return
            count = dlg.row_count()
        n = max(1, min(MAX_ADD_ROWS, int(count)))
        self._ensure_blank_table_headers()
        self._app._undo_stack.push(UndoAddBlankRowCommand(self._app, n))

    def add_blank_table_column(self, name: str | None = None, *, count: int | None = None) -> None:
        """Append empty data columns (Data → Table → Operations → Add Column)."""
        from .dialogs.add_table import MAX_ADD_COLUMNS, AddTableColumnsDialog
        from .main_window.table_undo_commands import UndoAddBlankColumnCommand

        if name is None and count is None:
            dlg = AddTableColumnsDialog(self._app)
            if dlg.exec() != QDialog.Accepted:
                return
            name = dlg.column_name()
            count = dlg.column_count()
        label = (name or "").strip() or "Column"
        if label in ("ID_HIDDEN", "Structure"):
            QMessageBox.warning(
                self._app, "Add Column", "That name is reserved. Choose a different column name."
            )
            return
        n = 1 if count is None else max(1, min(MAX_ADD_COLUMNS, int(count)))
        self._ensure_blank_table_headers()
        unique = self._app._unique_table_column_names([label] * n)
        self._app._undo_stack.push(UndoAddBlankColumnCommand(self._app, unique))

    def _scoped_table_oids(self, allowed: set | frozenset | None) -> list[int]:
        """Table-order row OIDs, optionally restricted to *allowed*."""
        m = self._app._table_model
        if allowed is None:
            return [int(m.row_oid(r)) for r in range(m.rowCount())]
        return [oid for r in range(m.rowCount()) if (oid := int(m.row_oid(r))) in allowed]

    def _oids_and_column_texts(
        self, headers: str | list[str], *, allowed: set | frozenset | None
    ) -> tuple[list[int], list[list[str]]]:
        """One pass: table-order OIDs and backing text for each *headers* entry."""
        names = [headers] if isinstance(headers, str) else list(headers)
        m = self._app._table_model
        oids: list[int] = []
        columns: list[list[str]] = [[] for _ in names]
        for r in range(m.rowCount()):
            oid = int(m.row_oid(r))
            if allowed is not None and oid not in allowed:
                continue
            oids.append(oid)
            for i, header in enumerate(names):
                columns[i].append(m.backing_value_for_row_header(r, header) or "")
        return (oids, columns)

    def open_split_column_dialog(self) -> None:
        columns = self._app._filterable_data_column_names() if self._app.headers else []
        if not ensure_text_column_tool_ready(
            self._app,
            TOOL_SPLIT_COLUMN,
            columns,
            empty_message="Open a file or add rows so the table has a column to split.",
            no_text_message="No text columns are available to split.",
        ):
            return
        from .dialogs import SplitColumnDialog

        d = SplitColumnDialog(columns, len(self._app._selected_logical_rows()), self._app)
        self._app._prepare_tool_dialog(d)
        d.setAttribute(Qt.WA_DeleteOnClose, True)
        d.accepted.connect(lambda *_, dlg=d: self._on_split_column_dialog_accepted(dlg))
        d.show()

    def _on_split_column_dialog_accepted(self, d) -> None:
        from ..table.column_split import (
            MAX_SPLIT_COLUMNS,
            apply_keep_mode,
            output_column_names,
            pad_split_rows,
            split_column_values,
            split_width,
        )

        p = d.params()
        source = p.source_column
        if not source or source not in self._app.headers:
            QMessageBox.warning(self._app, TOOL_SPLIT_COLUMN, "Choose a column to split.")
            return
        only_selected = d.only_selected_rows()
        allowed = self._app._selected_oids_set() if only_selected else None
        if self._app._abort_if_only_selected_but_empty(only_selected, allowed, TOOL_SPLIT_COLUMN):
            return
        oids, (texts,) = self._oids_and_column_texts(source, allowed=allowed)
        if not oids:
            QMessageBox.information(
                self._app, TOOL_SPLIT_COLUMN, "No rows to process for this scope."
            )
            return
        try:
            _delim, parts = split_column_values(texts, p.mode, custom=p.custom)
        except ValueError as exc:
            QMessageBox.warning(
                self._app, TOOL_SPLIT_COLUMN, str(exc) or "Could not split the column."
            )
            return
        keep = getattr(p, "keep", "all") or "all"
        if keep in ("largest", "smallest"):
            parts = apply_keep_mode(parts, keep)
        n_cols = split_width(parts)
        if keep == "all" and n_cols < 2:
            QMessageBox.information(
                self._app,
                TOOL_SPLIT_COLUMN,
                "No split fields were found. Check the separator and try again.",
            )
            return
        if n_cols < 1:
            QMessageBox.information(
                self._app,
                TOOL_SPLIT_COLUMN,
                "No values were found. Check the separator and try again.",
            )
            return
        truncated = any((len(row) > MAX_SPLIT_COLUMNS for row in parts))
        padded = pad_split_rows(parts, n_cols)
        if keep in ("largest", "smallest"):
            headers = [p.prefix or source]
        else:
            headers = output_column_names(p.prefix or source, n_cols)
        rows = [
            (int(oid), {headers[i]: padded[j][i] for i in range(n_cols)})
            for j, oid in enumerate(oids)
        ]
        written = self._app.on_calc_finished(
            rows, headers, progress_label=TOOL_SPLIT_COLUMN, immediate=True
        )
        extra = f" (capped at {n_cols})" if truncated else ""
        self._app.status_label.setText(
            f'{TOOL_SPLIT_COLUMN}: {len(written)} column(s) from "{source}"{extra}.'
        )

    def open_join_columns_dialog(self) -> None:
        columns = self._app._filterable_data_column_names() if self._app.headers else []
        if not ensure_text_column_tool_ready(
            self._app,
            TOOL_JOIN_COLUMNS,
            columns,
            empty_message="Open a file or add rows so the table has columns to join.",
            no_text_message="No text columns are available to join.",
        ):
            return
        from .dialogs import JoinColumnsDialog

        d = JoinColumnsDialog(columns, len(self._app._selected_logical_rows()), self._app)
        self._app._prepare_tool_dialog(d)
        d.setAttribute(Qt.WA_DeleteOnClose, True)
        d.accepted.connect(lambda *_, dlg=d: self._on_join_columns_dialog_accepted(dlg))
        d.show()

    def _on_join_columns_dialog_accepted(self, d) -> None:
        from ..table.column_join import join_two_values, resolve_join_delimiter

        p = d.params()
        left = p.left_column
        right = p.right_column
        if (
            not left
            or left not in self._app.headers
            or (not right)
            or (right not in self._app.headers)
        ):
            QMessageBox.warning(self._app, TOOL_JOIN_COLUMNS, "Choose two columns to join.")
            return
        only_selected = d.only_selected_rows()
        allowed = self._app._selected_oids_set() if only_selected else None
        if self._app._abort_if_only_selected_but_empty(only_selected, allowed, TOOL_JOIN_COLUMNS):
            return
        oids, (left_texts, right_texts) = self._oids_and_column_texts(
            [left, right], allowed=allowed
        )
        if not oids:
            QMessageBox.information(
                self._app, TOOL_JOIN_COLUMNS, "No rows to process for this scope."
            )
            return
        try:
            delim = resolve_join_delimiter(p.mode, p.custom)
        except ValueError as exc:
            QMessageBox.warning(
                self._app, TOOL_JOIN_COLUMNS, str(exc) or "Could not join the columns."
            )
            return
        out_name = (p.output_column or "").strip() or f"{left}_{right}"
        skip_empty = bool(p.skip_empty)
        rows = [
            (
                int(oid),
                {
                    out_name: join_two_values(
                        left_texts[i], right_texts[i], delim, skip_empty=skip_empty
                    )
                },
            )
            for i, oid in enumerate(oids)
        ]
        written = self._app.on_calc_finished(
            rows, [out_name], progress_label=TOOL_JOIN_COLUMNS, immediate=True
        )
        final_col = written[0] if written else out_name
        self._app.status_label.setText(
            f'{TOOL_JOIN_COLUMNS}: column "{final_col}" from "{left}" and "{right}" ({len(rows)} row(s)).'
        )

    def open_fp_similarity(self):
        if not self._app.headers:
            return
        from .dialogs import FPSimilarityDialog

        dlg = FPSimilarityDialog(self._app)
        self._app._prepare_tool_dialog(dlg)
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()

    def _ensure_fp_similarity_signals(self):
        """Signals on the main window so fingerprint-similarity jobs survive dialog close."""
        sig = getattr(self._app, "_fp_similarity_signals", None)
        if sig is not None:
            return sig
        from ..workers import FPSimilaritySignals

        sig = FPSimilaritySignals(self._app)
        sig.finished.connect(self._on_fp_similarity_finished)
        sig.failed.connect(self._on_fp_similarity_failed)
        self._app._fp_similarity_signals = sig
        return sig

    def _on_fp_similarity_finished(self, rows) -> None:
        self._app._finish_tool_progress("Fingerprint similarity")
        ctx = getattr(self._app, "_fp_similarity_run_ctx", None) or {}
        from .dialogs.fp_similarity import apply_fp_similarity_column

        apply_fp_similarity_column(
            self._app,
            compare_oids=set(ctx.get("compare_oids") or []),
            column_name=str(ctx.get("pending_column_name") or ""),
            rows=rows,
        )

    def _on_fp_similarity_failed(self, msg: str) -> None:
        report_cancellable_job_failure(
            self._app,
            "Fingerprint Similarity",
            msg,
            progress_label="Fingerprint similarity",
            failure_fallback="Fingerprint similarity failed.",
            cancelled_status="Cancelled.",
        )

    def open_diverse_subset(self) -> None:
        if not self._app.headers:
            return
        from .dialogs import DiverseSubsetDialog

        dlg = DiverseSubsetDialog(self._app)
        self._app._prepare_tool_dialog(dlg)
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()

    def _ensure_diverse_subset_signals(self):
        """Signals on the main window so diverse subset jobs survive dialog close."""
        sig = getattr(self._app, "_diverse_subset_signals", None)
        if sig is not None:
            return sig
        from ..workers import DiverseSubsetSignals

        sig = DiverseSubsetSignals(self._app)
        sig.finished.connect(self._on_diverse_subset_finished)
        sig.failed.connect(self._on_diverse_subset_failed)
        self._app._diverse_subset_signals = sig
        return sig

    def _on_diverse_subset_finished(
        self, picked_oids: list, column_rows: list, n_cached: int, n_computed: int
    ) -> None:
        from PySide6.QtCore import QTimer

        self._app._finish_tool_progress("Diverse subset")
        ctx = getattr(self._app, "_diverse_subset_run_ctx", None) or {}
        picked = [int(o) for o in picked_oids or []]

        def _apply_results() -> None:
            col_name = (ctx.get("pending_column_name") or "").strip()
            if col_name and column_rows:
                m = self._app._table_model
                nc = m.columnCount()
                self._app.headers.append(col_name)
                m.insert_column_at(nc, col_name, None)
                try:
                    self._app.table.setUpdatesEnabled(False)
                except Exception:
                    pass
                try:
                    m.set_column_text_by_oids(
                        col_name, [(int(oid), str(rank)) for oid, rank in column_rows]
                    )
                    self._app._sync_global_bounds_for_headers([col_name], refresh_filters=True)
                finally:
                    try:
                        self._app.table.setUpdatesEnabled(True)
                    except Exception:
                        pass
            if ctx.get("select_subset") and picked:
                source_rows: list[int] = []
                for oid in picked:
                    try:
                        row = self._app.logical_row_for_oid(int(oid))
                    except (TypeError, ValueError):
                        continue
                    if row >= 0:
                        source_rows.append(int(row))
                self._app._finish_oid_override_selection(
                    source_rows,
                    frozenset((int(o) for o in picked)),
                    clear_oid_override=False,
                    extra_status="",
                )
            cache_note = ""
            if n_cached or n_computed:
                cache_note = f" ({n_cached} cached fingerprint(s), {n_computed} computed)"
            col_note = f" Column '{col_name}' added." if col_name else ""
            self._app.status_label.setText(
                f"Diverse subset: picked {len(picked)} compound(s).{cache_note}{col_note}"
            )

        QTimer.singleShot(0, _apply_results)

    def _on_diverse_subset_failed(self, msg: str) -> None:
        self._app._finish_tool_progress("Diverse subset")
        if msg == "Cancelled.":
            self._app.status_label.setText("Cancelled.")
        else:
            self._app.status_label.setText(f"Diverse subset failed: {msg or 'Computation failed.'}")

    def on_custom_calc_finished(self, res):
        ok_any = False
        for _idx, val in res:
            t = (val or "").strip()
            if safe_float(t) is not None:
                ok_any = True
                break
        if not ok_any:
            QMessageBox.warning(
                self._app,
                TOOL_CALCULATOR,
                "The expression produced no numeric results (all rows failed). No column was added.",
            )
            self._app.status_label.setText(f"{TOOL_CALCULATOR}: no numeric results.")
            self._app._clear_tool_progress()
            return
        self._app._finish_tool_progress("Calculator…")
        self._app.on_calc_finished(
            [(int(oid), {self._app.new_c: str(val)}) for oid, val in res],
            [self._app.new_c],
            finish_progress=False,
        )
        self._app.status_label.setText(
            self._app._consume_partial_results_notice()
            or f'{TOOL_CALCULATOR}: column "{self._app.new_c}" updated.'
        )
