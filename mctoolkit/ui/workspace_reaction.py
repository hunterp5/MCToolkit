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

"""Tools → Reaction (extract components, reaction-based enumeration)."""

from __future__ import annotations
import logging
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox
from .analysis_job_support import ensure_text_column_tool_ready
from .strings import TOOL_REACTION_ENUMERATION, TOOL_REACTION_EXTRACT
from ..chem.reaction_extract import extract_reaction_column_values, preferred_reaction_source_column
from ..chem.reaction_file_io import reaction_smarts_from_app_selection
from ..workers import ReactionEnumerationWorker

logger = logging.getLogger(__name__)


class ReactionTools:
    def __init__(self, app) -> None:
        self._app = app

    def open_reaction_extract(self) -> None:
        columns = self._app._filterable_data_column_names() if self._app.headers else []
        if not ensure_text_column_tool_ready(
            self._app,
            TOOL_REACTION_EXTRACT,
            columns,
            empty_message="Open a file or add rows so the table has a reaction column to extract from.",
            no_text_message="No text columns are available to extract from.",
        ):
            return
        from .dialogs import ReactionExtractDialog

        d = ReactionExtractDialog(
            columns,
            len(self._app._selected_logical_rows()),
            self._app,
            default_column=preferred_reaction_source_column(self._app.headers),
        )
        self._app._prepare_tool_dialog(d)
        d.setAttribute(Qt.WA_DeleteOnClose, True)
        d.accepted.connect(lambda *_, dlg=d: self._on_reaction_extract_dialog_accepted(dlg))
        d.show()

    def _on_reaction_extract_dialog_accepted(self, d) -> None:
        p = d.params()
        source = p.source_column
        if not source or source not in self._app.headers:
            QMessageBox.warning(self._app, TOOL_REACTION_EXTRACT, "Choose a reaction column.")
            return
        only_selected = d.only_selected_rows()
        allowed = self._app._selected_oids_set() if only_selected else None
        if self._app._abort_if_only_selected_but_empty(
            only_selected, allowed, TOOL_REACTION_EXTRACT
        ):
            return
        oids = self._app._all_oids_in_table_order()
        if allowed is not None:
            oids = [o for o in oids if o in allowed]
        if not oids:
            QMessageBox.information(
                self._app, TOOL_REACTION_EXTRACT, "No rows to process for this scope."
            )
            return
        try:
            ci = self._app.headers.index(source)
        except ValueError:
            QMessageBox.warning(self._app, TOOL_REACTION_EXTRACT, "Choose a reaction column.")
            return
        texts: list[str] = []
        for oid in oids:
            row = self._app._table_model.logical_row_for_oid(int(oid))
            if row < 0:
                texts.append("")
                continue
            raw = self._app._table_model.backing_value_for_row_header(row, source) or ""
            if not raw:
                raw = self._app._table_cell_text(row, ci) or ""
            texts.append(raw)
        try:
            headers, row_dicts = extract_reaction_column_values(
                texts, p.mode, reactant_prefix=p.reactant_prefix, product_prefix=p.product_prefix
            )
        except ValueError as exc:
            QMessageBox.warning(
                self._app, TOOL_REACTION_EXTRACT, str(exc) or "Could not extract that column."
            )
            return
        if not headers:
            QMessageBox.information(
                self._app,
                TOOL_REACTION_EXTRACT,
                "No reactants or products could be parsed from that column.",
            )
            return
        rows = [(int(oid), row_dicts[j]) for j, oid in enumerate(oids)]
        written = self._app.on_calc_finished(rows, headers, progress_label=TOOL_REACTION_EXTRACT)
        self._app.status_label.setText(
            f'{TOOL_REACTION_EXTRACT}: {len(written)} column(s) from "{source}".'
        )

    def open_reaction_enumeration(self) -> None:
        from .dialogs import ReactionEnumerationDialog

        d = ReactionEnumerationDialog(
            parent=self._app, initial_smarts=reaction_smarts_from_app_selection(self._app)
        )
        self._app._prepare_tool_dialog(d)
        d.setAttribute(Qt.WA_DeleteOnClose, True)
        d.accepted.connect(lambda *_, dlg=d: self._on_reaction_enumeration_dialog_accepted(dlg))
        d.show()

    def _on_reaction_enumeration_dialog_accepted(self, d) -> None:
        p = d.params()
        from ..platform_support.memory_guards import check_product_enumeration

        guard = check_product_enumeration(p.max_products)
        if not guard.ok:
            QMessageBox.warning(self._app, TOOL_REACTION_ENUMERATION, guard.message)
            return
        ps = self._app._tool_progress_state
        self._app._begin_tool_progress(TOOL_REACTION_ENUMERATION, p.max_products)
        self._app.process_queue.enqueue(
            f"{TOOL_REACTION_ENUMERATION} ({p.reaction_name})",
            lambda ev, req=p, sigs=self._app.signals, prog=ps: ReactionEnumerationWorker(
                req, TOOL_REACTION_ENUMERATION, sigs, cancel_event=ev, progress_state=prog
            ),
        )

    def on_reaction_enum_finished(self, result) -> None:
        self._app._finish_tool_progress(TOOL_REACTION_ENUMERATION)
        parts: list[str] = []
        if result.add_to_table and result.products:
            records = [
                (
                    str(smi),
                    {"Reaction": str(result.reaction_name or ""), "Enumeration_Method": "Reaction"},
                )
                for smi in result.products
                if (smi or "").strip()
            ]
            n = self._app.add_rows_from_external_records_batch(records, render_structures=True)
            parts.append(f"added {n:,} row(s) to table")
        if result.save_to_file and result.save_path:
            parts.append(f"wrote {int(result.written_count):,} structure(s) to {result.save_path}")
        suffix = ""
        if int(result.skipped) > 0:
            suffix = f" ({int(result.skipped):,} outcome(s) skipped by constraints or duplicates)"
        if self._app.has_partial_results_notice():
            return
        if parts:
            self._app.status_label.setText(
                f"{TOOL_REACTION_ENUMERATION}: {', '.join(parts)}{suffix}."
            )
        elif not result.products:
            self._app.status_label.setText(
                f"{TOOL_REACTION_ENUMERATION}: no products generated{suffix}."
            )

    def on_reaction_enum_failed(self, message: str, tool_title: str) -> None:
        if message == "Cancelled.":
            self._app._finish_tool_progress(tool_title)
            self._app.status_label.setText(
                self._app._consume_partial_results_notice() or "Cancelled."
            )
            return
        self._app._clear_tool_progress()
        self._app.status_label.setText("Ready.")
        QMessageBox.warning(self._app, tool_title, message or "Reaction enumeration failed.")
