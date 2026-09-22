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

"""Tools → Prepare Structures → Tautomers."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from ...chem.tautomer_enumeration import DEFAULT_MAX_TAUTOMERS, ENUMERATOR_MAX_TAUTOMERS
from ...reference.method_citations import tautomer_dialog_footer_html
from ...workers.tautomer_generator import (
    TautomerGeneratorRequest,
    TautomerGeneratorSignals,
    TautomerGeneratorWorker,
)
from ..analysis_job_support import enqueue_process_queue_job
from ..qt_widget_utils import make_window_minimizable
from .conformer_output import citation_footer_label
from .structure_input import attach_structure_input

TOOL_TAUTOMERS = "Tautomers"


class TautomerGeneratorDialog(QDialog):
    """Enumerate likely tautomers and optionally add chosen forms to the table."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_app = parent
        self._init_tautomer_state(parent)
        self._build_tautomer_ui()
        self._wire_tautomer_ui()

    def _init_tautomer_state(self, parent) -> None:
        self.setWindowTitle(TOOL_TAUTOMERS)
        self.setMinimumWidth(460)
        n_sel = len(parent._selected_logical_rows()) if parent is not None else 0
        self._selected_row_count = n_sel
        self._have_selection = n_sel > 0
        self._active_job_id: str | None = None

    def _build_tautomer_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 6)
        root.setSpacing(4)

        attach_structure_input(self, root, selected_row_count=self._selected_row_count)

        cap_row = QHBoxLayout()
        cap_row.setSpacing(6)
        cap_row.addWidget(QLabel("Max tautomers:"))
        self.max_spin = QSpinBox()
        self.max_spin.setRange(1, ENUMERATOR_MAX_TAUTOMERS)
        self.max_spin.setValue(DEFAULT_MAX_TAUTOMERS)
        self.max_spin.setToolTip(
            "Keep at most this many likely forms per input (plus the input structure "
            "when it would otherwise be dropped)."
        )
        cap_row.addWidget(self.max_spin)
        cap_row.addStretch()
        root.addLayout(cap_row)

        gen_row = QHBoxLayout()
        gen_row.setSpacing(6)
        self.generate_btn = QPushButton("Generate")
        gen_row.addWidget(self.generate_btn)
        gen_row.addStretch()
        root.addLayout(gen_row)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        root.addWidget(self.status_label)

        root.addWidget(citation_footer_label(tautomer_dialog_footer_html(), self))

    def _wire_tautomer_ui(self) -> None:
        self.generate_btn.clicked.connect(self._on_generate)
        self._taut_signals = TautomerGeneratorSignals(self.parent_app)
        self._taut_signals.finished.connect(self._on_finished)
        self._taut_signals.failed.connect(self._on_failed)
        self._refresh_structure_sources()
        self.adjustSize()
        make_window_minimizable(self)

    def _refresh_structure_sources(self) -> None:
        self._structure_input.refresh_sources(self.parent_app)

    def _on_generate(self) -> None:
        if self.parent_app is None:
            return
        rows = self._structure_input.collect_rows(self, TOOL_TAUTOMERS)
        if rows is None:
            return

        self.generate_btn.setEnabled(False)
        req = TautomerGeneratorRequest(rows=rows, max_tautomers=int(self.max_spin.value()))
        n = len(rows)
        prog = self.parent_app._tool_progress_state
        self._active_job_id = enqueue_process_queue_job(
            self.parent_app,
            "Generate tautomers",
            n,
            lambda ev, r=req, ws=self.parent_app.signals, ps=self._taut_signals, st=prog: (
                TautomerGeneratorWorker(r, ws, ps, cancel_event=ev, progress_state=st)
            ),
            queue_label=f"Generate tautomers ({n} molecules)",
        )

    def _on_finished(self, rows: list) -> None:
        self.generate_btn.setEnabled(True)
        rows_sorted = sorted(rows, key=lambda t: (-int(t[2]), str(t[1])))
        n_forms = len(rows_sorted)
        n_sources = len({oid for oid, *_rest in rows_sorted if oid is not None})
        if n_forms == 0:
            self.status_label.setText("No tautomers were generated.")
        elif n_forms == n_sources or (n_sources == 0 and n_forms == 1):
            self.status_label.setText("No alternative tautomers were found.")
        else:
            self.status_label.setText(f"{n_forms} tautomer form(s).")
        if self.parent_app is not None:
            job_id = self._active_job_id
            self._active_job_id = None
            self.parent_app._finish_tool_progress(
                "Generate tautomers",
                status_message=self.parent_app._consume_partial_results_notice() or "Ready.",
                job_id=job_id,
            )
            opener = getattr(self.parent_app, "open_tautomer_browser", None)
            if n_forms and callable(opener):
                opener(rows_sorted)

    def _on_failed(self, msg: str) -> None:
        self.generate_btn.setEnabled(True)
        if self.parent_app is not None:
            job_id = self._active_job_id
            self._active_job_id = None
            self.parent_app._finish_tool_progress("Generate tautomers", job_id=job_id)
        QMessageBox.warning(self, TOOL_TAUTOMERS, msg or "Generation failed.")
