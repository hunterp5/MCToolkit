# This file is part of MCToolkit.
# Copyright (C) 2026 Hunter Picard
#
# MCToolkit is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# MCToolkit is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with MCToolkit. If not, see <https://www.gnu.org/licenses/>.

"""Tools → Predict → Generate Protomers."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from ...workers.protomer_generator import (
    ProtomerGeneratorRequest,
    ProtomerGeneratorSignals,
    ProtomerGeneratorWorker,
)
from ..analysis_job_support import enqueue_process_queue_job
from ..qt_widget_utils import make_window_minimizable
from .structure_input import attach_structure_input


def pka_text_for_source_oid(app, oid: int | None) -> str:
    """Format cached Uni-pKa values for a parent table row, or ``N/A``."""
    if oid is None or app is None:
        return "N/A"
    from mctoolkit.ionization.microstate_cache import lookup as cache_lookup
    from mctoolkit.ionization.unipka_ensembles import format_pka_values, pka_values_from_states
    from mctoolkit.services.structure_grouping import structure_key

    mol = app.mols.get(int(oid))
    if mol is None:
        row = app._table_model.logical_row_for_oid(int(oid))
        if row >= 0:
            mol = app._mol_for_structure_row(row)
    if mol is None:
        return "N/A"
    hit, states = cache_lookup(structure_key(mol))
    if not hit:
        return "N/A"
    return format_pka_values(pka_values_from_states(states))


class ProtomerGeneratorDialog(QDialog):
    """Enumerate protomers from a Uni-pKa ionization ensemble and estimate populations at a target pH."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_app = parent
        self._init_protomer_state(parent)
        self._build_protomer_ui()
        self._wire_protomer_ui()

    def _init_protomer_state(self, parent) -> None:
        self.setWindowTitle("Generate Protomers")
        self.setMinimumWidth(420)
        n_sel = len(parent._selected_logical_rows()) if parent is not None else 0
        self._selected_row_count = n_sel
        self._have_selection = n_sel > 0

    def _build_protomer_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 6)
        root.setSpacing(4)

        attach_structure_input(self, root, selected_row_count=self._selected_row_count)

        ph_row = QHBoxLayout()
        ph_row.setSpacing(6)
        ph_row.addWidget(QLabel("pH:"))
        self.ph_spin = QDoubleSpinBox()
        self.ph_spin.setRange(0.0, 14.0)
        self.ph_spin.setDecimals(2)
        self.ph_spin.setSingleStep(0.1)
        self.ph_spin.setValue(7.40)
        self.ph_spin.setToolTip("Target pH for approximate protomer population weights.")
        ph_row.addWidget(self.ph_spin)
        ph_row.addStretch()
        root.addLayout(ph_row)

        gen_row = QHBoxLayout()
        gen_row.setSpacing(6)
        self.generate_btn = QPushButton("Generate")
        gen_row.addWidget(self.generate_btn)
        gen_row.addStretch()
        root.addLayout(gen_row)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        root.addWidget(self.status_label)

    def _wire_protomer_ui(self) -> None:
        self.generate_btn.clicked.connect(self._on_generate)
        self._prot_signals = ProtomerGeneratorSignals(self.parent_app)
        self._prot_signals.finished.connect(self._on_finished)
        self._prot_signals.failed.connect(self._on_failed)
        self._refresh_structure_sources()
        self.adjustSize()
        make_window_minimizable(self)

    def _refresh_structure_sources(self) -> None:
        self._structure_input.refresh_sources(self.parent_app)

    def _on_generate(self) -> None:
        if self.parent_app is None:
            return
        rows = self._structure_input.collect_rows(self, "Generate Protomers")
        if rows is None:
            return

        self.generate_btn.setEnabled(False)
        req = ProtomerGeneratorRequest(rows=rows, pH=float(self.ph_spin.value()))
        n = len(rows)
        prog = self.parent_app._tool_progress_state
        enqueue_process_queue_job(
            self.parent_app,
            "Generate protomers",
            n,
            lambda ev, r=req, ws=self.parent_app.signals, ps=self._prot_signals, st=prog: (
                ProtomerGeneratorWorker(r, ws, ps, cancel_event=ev, progress_state=st)
            ),
            queue_label=f"Generate protomers ({n} molecules)",
        )

    def _on_finished(self, rows: list) -> None:
        self.generate_btn.setEnabled(True)
        n_forms = len(rows or ())
        if n_forms == 0:
            self.status_label.setText("No protomers were generated.")
        else:
            n_sources = len({oid for oid, *_rest in rows if oid is not None})
            self.status_label.setText(
                f"{n_forms} protomer form(s) from {max(n_sources, 1)} parent(s)."
            )
        if self.parent_app is not None:
            self.parent_app._finish_tool_progress(
                "Generate protomers",
                status_message=self.parent_app._consume_partial_results_notice() or "Ready.",
            )
            source_oids = {int(oid) for oid, _smi, _pct in rows if oid is not None}
            self._write_unipka_pka_for_oids(source_oids)
            opener = getattr(self.parent_app, "open_protomer_browser", None)
            if n_forms and callable(opener):
                opener(rows)

    def _on_failed(self, msg: str) -> None:
        self.generate_btn.setEnabled(True)
        if self.parent_app is not None:
            self.parent_app._finish_tool_progress("Generate protomers")
        QMessageBox.warning(self, "Generate Protomers", msg or "Generation failed.")

    def _write_unipka_pka_for_oids(self, source_oids: set[int]) -> None:
        if not source_oids or self.parent_app is None:
            return
        rows = []
        for oid in sorted(source_oids):
            rows.append((int(oid), {"pKa": pka_text_for_source_oid(self.parent_app, oid)}))
        if rows:
            self.parent_app.on_calc_finished(
                rows, ["pKa"], finish_progress=False, progress_label=None
            )
