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
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with mctoolkit.  If not, see <https://www.gnu.org/licenses/>.

"""MPO Scoring tool window (Data menu)."""

from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox


class MpoTools:
    def __init__(self, app) -> None:
        self._app = app

    def open_mpo_scoring_dialog(self) -> None:
        if not self._app.headers or self._app._table_model.rowCount() == 0:
            QMessageBox.information(
                self._app,
                "MPO Scoring",
                "Open a file or add rows with numeric property columns first.",
            )
            return
        if not getattr(self._app, "global_bounds", None):
            try:
                self._app.calculate_global_bounds()
            except Exception:
                pass
        if not getattr(self._app, "global_bounds", None):
            QMessageBox.information(
                self._app,
                "MPO Scoring",
                "No numeric columns are available yet. Compute descriptors or import numeric data first.",
            )
            return
        from .dialogs.mpo_scoring import MPOScoringDialog
        from .singleton_modeless_dialog import reuse_or_show_modeless_singleton

        def _factory():
            d = MPOScoringDialog(self._app)
            self._app._prepare_tool_dialog(d)
            d.setAttribute(Qt.WA_DeleteOnClose, True)
            d.accepted.connect(lambda *_, dlg=d: self._on_mpo_scoring_dialog_accepted(dlg))
            return d

        reuse_or_show_modeless_singleton(
            self._app,
            "_mpo_scoring_dialog",
            _factory,
            on_reused_visible=lambda dlg: self._app._sync_dialog_only_selected_scope(dlg),
        )

    def _on_mpo_scoring_dialog_accepted(self, d) -> None:
        try:
            p = d.params()
        except Exception as exc:
            QMessageBox.warning(self._app, "MPO Scoring", str(exc))
            return
        if not p.specs:
            QMessageBox.information(
                self._app, "MPO Scoring", "Add at least one property criterion."
            )
            return
        only_selected = d.only_selected_rows()
        allowed = self._app._selected_oids_set() if only_selected else None
        if self._app._abort_if_only_selected_but_empty(only_selected, allowed, "MPO Scoring"):
            return
        cols = [s.column for s in p.specs]
        missing = [c for c in cols if c not in self._app.headers]
        if missing:
            QMessageBox.warning(
                self._app,
                "MPO Scoring",
                "These columns are no longer in the table:\n" + ", ".join(missing),
            )
            return
        from ..workers.mpo_scoring import MpoScoreSignals, MpoScoreWorker
        from .table_dataframe import scoped_oid_column_snapshot
        from .threadpool_access import start_runnable_on_app_pool

        oids, texts = scoped_oid_column_snapshot(self._app, cols, allowed_oids=allowed)
        if not oids:
            QMessageBox.information(self._app, "MPO Scoring", "No rows to process for this scope.")
            return

        out_cols = [p.output_column]
        if p.write_individual:
            for s in p.specs:
                out_cols.append(f"MPO_d_{s.column}")

        n_crit = len(p.specs)
        crit_word = "on" if n_crit == 1 else "a"
        status = (
            f'MPO Scoring: wrote "{p.output_column}" for {{n}} row(s) '
            f"({n_crit} criteri{crit_word})."
        )
        signals = MpoScoreSignals(self._app)

        def _on_ok(rows, written_cols) -> None:
            if not rows:
                QMessageBox.information(self._app, "MPO Scoring", "No rows could be scored.")
                return
            self._app.on_calc_finished(rows, written_cols, progress_label="MPO Scoring")
            self._app.status_label.setText(status.format(n=len(rows)))

        def _on_fail(message: str) -> None:
            QMessageBox.warning(self._app, "MPO Scoring", message)

        worker = MpoScoreWorker(
            oids,
            texts,
            p.specs,
            combine=p.combine,
            output_column=p.output_column,
            write_individual=p.write_individual,
            decimals=p.decimals,
            out_cols=out_cols,
            signals=signals,
        )
        if "pytest" in sys.modules:
            signals.finished.connect(_on_ok, type=Qt.DirectConnection)
            signals.failed.connect(_on_fail, type=Qt.DirectConnection)
            worker.run()
            return
        signals.finished.connect(_on_ok)
        signals.failed.connect(_on_fail)
        self._app._mpo_score_signals = signals
        self._app.status_label.setText("MPO Scoring…")
        start_runnable_on_app_pool(self._app, worker)
