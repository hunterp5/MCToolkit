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
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with MolManager.  If not, see <https://www.gnu.org/licenses/>.

from __future__ import annotations

from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from ...config import load_config
from ...plot_radar import resolve_entry_row_oid
from ...utils import parse_molecule_from_cell_text
from ...workers import (
    FPSimilaritySignals,
    FPSimilarityWorker,
    SIMILARITY_FP_TYPE_LABELS,
    SIMILARITY_METRIC_LABELS,
)
from ..strings import COLUMN_TANIMOTO_SIMILARITY
from ..qt_widget_utils import make_window_minimizable
from .scope import selection_scope_checked

_DEFAULT_METRIC = "Tanimoto"


class FPSimilarityDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_app = parent
        self.setWindowTitle("Fingerprint Similarity")
        self.setMinimumWidth(420)
        n_sel = len(parent._selected_logical_rows()) if parent is not None else 0
        self._have_selection = n_sel > 0
        self._compare_oids: set[int] = set()
        self._pending_column_name = ""

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 6)
        root.setSpacing(6)

        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        root.addLayout(form)

        self.src_combo = QComboBox()
        self._refresh_structure_sources()
        form.addRow("Structure source:", self.src_combo)

        self.fp_combo = QComboBox()
        self.fp_combo.addItems(SIMILARITY_FP_TYPE_LABELS)
        form.addRow("Fingerprint:", self.fp_combo)

        self.metric_combo = QComboBox()
        self.metric_combo.addItems(SIMILARITY_METRIC_LABELS)
        form.addRow("Similarity metric:", self.metric_combo)

        self.column_name_edit = QLineEdit()
        self.column_name_edit.setPlaceholderText("Column name in table")
        self._sync_default_column_name()
        self.metric_combo.currentTextChanged.connect(self._sync_default_column_name)
        form.addRow("Output column:", self.column_name_edit)

        query_row = QHBoxLayout()
        self.query_combo = QComboBox()
        self.query_combo.addItems(["From Table Row", "SMILES Input"])
        query_row.addWidget(self.query_combo)
        self.row_input = QLineEdit()
        self.row_input.setPlaceholderText("Row ID (OID or row number)")
        self.row_input.setToolTip("Table OID or 1-based row number.")
        query_row.addWidget(self.row_input, 1)
        self.smi_input = QLineEdit()
        self.smi_input.setPlaceholderText("Enter SMILES")
        self.smi_input.setVisible(False)
        query_row.addWidget(self.smi_input, 1)
        form.addRow("Query:", query_row)

        self.only_selected_cb = QCheckBox("Only compare to selected rows")
        self._only_selected_scope_prefix = "Only compare to selected rows"
        if self._have_selection:
            self.only_selected_cb.setText(f"{self._only_selected_scope_prefix} ({n_sel} row(s))")
        else:
            self.only_selected_cb.setEnabled(False)
        form.addRow("", self.only_selected_cb)

        btn_row = QHBoxLayout()
        self.compute_btn = QPushButton("Compute and Add Column")
        self.compute_btn.clicked.connect(self.compute)
        btn_row.addWidget(self.compute_btn)
        btn_row.addStretch()
        root.addLayout(btn_row)

        self._fp_sim_signals = FPSimilaritySignals(self.parent_app)
        self._fp_sim_signals.finished.connect(self._on_fp_similarity_finished)
        self._fp_sim_signals.failed.connect(self._on_fp_similarity_failed)

        self.query_combo.currentIndexChanged.connect(self._toggle_query_mode)
        make_window_minimizable(self)

    def _refresh_structure_sources(self) -> None:
        self.src_combo.clear()
        if self.parent_app is None:
            return
        self.src_combo.addItems(self.parent_app.chemistry_tool_structure_sources())

    def _default_column_base(self) -> str:
        metric = self.metric_combo.currentText().strip() or _DEFAULT_METRIC
        if metric == _DEFAULT_METRIC:
            return COLUMN_TANIMOTO_SIMILARITY
        return f"{metric} Similarity"

    def _sync_default_column_name(self, *_args) -> None:
        if self.column_name_edit.text().strip():
            return
        self.column_name_edit.setText(self._default_column_base())

    def _toggle_query_mode(self, idx: int) -> None:
        from_table = idx == 0
        self.row_input.setVisible(from_table)
        self.smi_input.setVisible(not from_table)

    def _unique_column_name(self, base: str) -> str:
        name = (base or "").strip() or self._default_column_base()
        if name not in self.parent_app.headers:
            return name
        cnt = 1
        while f"{name} ({cnt})" in self.parent_app.headers:
            cnt += 1
        return f"{name} ({cnt})"

    def _compare_oids_in_scope(self, only_selected: bool) -> set[int]:
        allowed = self.parent_app._selected_oids_set() if only_selected else None
        oids: set[int] = set()
        m = self.parent_app._table_model
        for r in range(m.rowCount()):
            oid = m.row_oid(r)
            if allowed is not None and oid not in allowed:
                continue
            oids.add(oid)
        return oids

    def _resolve_query_oid(self) -> int | None:
        app = self.parent_app
        return resolve_entry_row_oid(
            self.row_input.text(),
            model=app._table_model,
            row_for_oid=app.logical_row_for_oid,
        )

    def _query_mol_and_oid(self, src: str) -> tuple[object | None, int | None]:
        if self.query_combo.currentIndex() == 0:
            qid = self._resolve_query_oid()
            if qid is None:
                return None, None
            for oid, mol in self.parent_app.collect_scoped_table_mols(src, only_selected=False):
                if oid == qid:
                    return mol, qid
            return None, qid
        smi = self.smi_input.text().strip()
        if not smi:
            return None, None
        return parse_molecule_from_cell_text(smi), None

    def compute(self) -> None:
        fp_choice = self.fp_combo.currentText()
        metric = self.metric_combo.currentText().strip() or _DEFAULT_METRIC
        src = self.src_combo.currentText()
        only_sel = selection_scope_checked(self)
        if only_sel and not self.parent_app._selected_oids_set():
            self.parent_app.status_label.setText(
                "Fingerprint similarity: \u201cOnly compare to selected rows\u201d "
                "is checked but nothing is selected."
            )
            return

        qmol, _qid = self._query_mol_and_oid(src)
        if qmol is None:
            if self.query_combo.currentIndex() == 0:
                self.parent_app.status_label.setText(
                    "Fingerprint similarity: enter a valid row ID (OID or row number)."
                )
            else:
                self.parent_app.status_label.setText(
                    "Fingerprint similarity: could not parse query SMILES."
                )
            return

        compare_oids = self._compare_oids_in_scope(only_sel)
        targets = self.parent_app.collect_scoped_table_mols(src, only_selected=only_sel)

        if not compare_oids:
            self.parent_app.status_label.setText(
                "Fingerprint similarity: no rows in scope for comparison."
            )
            return

        self._compare_oids = compare_oids
        self._pending_column_name = self._unique_column_name(self.column_name_edit.text())

        self.compute_btn.setEnabled(False)
        n_targets = len(targets)
        prog = self.parent_app._tool_progress_state
        self.parent_app._begin_tool_progress("Fingerprint similarity", max(1, n_targets + 1))
        self.parent_app.process_queue.enqueue_fast(
            "Fingerprint similarity",
            lambda ev, q=qmol, t=targets, c=fp_choice, m=metric, sig=self._fp_sim_signals, st=prog: FPSimilarityWorker(
                q,
                t,
                c,
                sig,
                metric=m,
                cancel_event=ev,
                progress_state=st,
            ),
        )

    def _write_similarity_column(self, rows) -> None:
        success = {oid: f"{sim:.4f}" for oid, sim, _ in (rows or [])}
        oid_map = {oid: success.get(oid, "N/A") for oid in self._compare_oids}
        name = self._pending_column_name
        m = self.parent_app._table_model
        nc = m.columnCount()
        self.parent_app.headers.append(name)
        m.insert_column_at(nc, name, None)
        n_rows = m.rowCount()
        n_scored = len(success)
        n_na = len(self._compare_oids) - n_scored
        chunk = max(250, int(load_config().ingest_gui_chunk_size))
        async_min = max(500, int(load_config().table_selection_chunk_rows))
        if n_rows < async_min:
            try:
                self.parent_app.table.setUpdatesEnabled(False)
            except Exception:
                pass
            try:
                m.fill_column_from_oid_map(name, oid_map, default="")
                self.parent_app._sync_global_bounds_for_headers([name], refresh_filters=True)
            finally:
                try:
                    self.parent_app.table.setUpdatesEnabled(True)
                except Exception:
                    pass
            self.parent_app.status_label.setText(
                f"Added '{name}' with {n_scored} score(s); {n_na} N/A in scope"
            )
            return
        self._fp_write_gen = int(getattr(self, "_fp_write_gen", 0)) + 1
        gen = self._fp_write_gen
        self.parent_app._begin_tool_progress("Writing results", n_rows)
        self._fp_write_ctx = {
            "gen": gen,
            "name": name,
            "oid_map": oid_map,
            "idx": 0,
            "chunk": chunk,
            "n_rows": n_rows,
            "n_scored": n_scored,
            "n_na": n_na,
        }
        QTimer.singleShot(0, self._fp_write_step)

    def _fp_write_step(self) -> None:
        ctx = getattr(self, "_fp_write_ctx", None)
        app = self.parent_app
        if not ctx or ctx.get("gen") != getattr(self, "_fp_write_gen", -1) or app is None:
            return
        name = ctx["name"]
        oid_map = ctx["oid_map"]
        idx = int(ctx["idx"])
        chunk = int(ctx["chunk"])
        n_rows = int(ctx["n_rows"])
        end = min(idx + chunk, n_rows)
        last = end >= n_rows
        try:
            app.table.setUpdatesEnabled(False)
        except Exception:
            pass
        try:
            app._table_model.fill_column_from_oid_map(
                name,
                oid_map,
                default="",
                start_row=idx,
                end_row=end,
                emit=True,
                rebuild_color=last,
            )
        finally:
            try:
                app.table.setUpdatesEnabled(True)
            except Exception:
                pass
        ctx["idx"] = end
        app._on_tool_progress("Writing results…", end, n_rows)
        if not last:
            QTimer.singleShot(0, self._fp_write_step)
            return
        self._fp_write_ctx = None
        if name in app._table_model._bounds_data_headers():
            app._table_model._mark_numeric_bounds_dirty({name})
        app._sync_global_bounds_for_headers([name], refresh_filters=True)
        app._finish_tool_progress("Writing results", status_message=None)
        app.status_label.setText(
            f"Added '{name}' with {ctx['n_scored']} score(s); {ctx['n_na']} N/A in scope"
        )

    def _on_fp_similarity_finished(self, rows) -> None:
        self.compute_btn.setEnabled(True)
        self.parent_app._finish_tool_progress("Fingerprint similarity")
        if not self._pending_column_name:
            return
        self._write_similarity_column(rows)

    def _on_fp_similarity_failed(self, msg: str) -> None:
        self.compute_btn.setEnabled(True)
        self.parent_app._finish_tool_progress("Fingerprint similarity")
        self.parent_app.status_label.setText(
            f"Fingerprint similarity failed: {msg or 'Computation failed.'}"
        )
