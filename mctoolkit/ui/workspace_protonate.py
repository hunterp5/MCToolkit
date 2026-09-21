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

"""Protomer generation adapter bound on ``WorkspaceTools.structure_prep`` (not a window base)."""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox

from ..table.structure_depiction_layout import structure_depict_height, structure_depict_width

logger = logging.getLogger(__name__)


class ProtonateTools:
    def run_protonate(self) -> None:
        """Generate dominant protomer into a new column and optionally render it."""
        if not self._app.headers or self._app._table_model.rowCount() == 0:
            return
        from .dialogs import ProtonateDialog
        from .pka_gpu_hint import maybe_remind_unipka_cuda_wheel

        maybe_remind_unipka_cuda_wheel(self._app)
        candidates = self._app.chemistry_tool_structure_sources()
        n_sel = len(self._app._selected_logical_rows())
        dlg = ProtonateDialog(candidates, n_sel, self._app)
        self._app._prepare_tool_dialog(dlg)
        dlg.setAttribute(Qt.WA_DeleteOnClose, True)
        dlg.accepted.connect(lambda *_, d=dlg: self._on_protonate_dialog_accepted(d))
        dlg.show()

    def _ensure_protonate_signals(self):
        sig = getattr(self._app, "_protonate_signals", None)
        if sig is not None:
            return sig
        from ..workers.protonate_worker import ProtonateSignals

        sig = ProtonateSignals(self._app)
        sig.finished.connect(self._on_protonate_finished, Qt.QueuedConnection)
        sig.failed.connect(self._on_protonate_failed, Qt.QueuedConnection)
        self._app._protonate_signals = sig
        return sig

    def _on_protonate_dialog_accepted(self, dlg) -> None:
        src, ph, out_col, only_selected, render_2d = dlg.config()
        allowed = self._app._selected_oids_set() if only_selected else None
        if self._app._abort_if_only_selected_but_empty(only_selected, allowed, "Protonate"):
            return

        data: list[tuple[int, object | None]] = []
        oids_walk = self._app._all_oids_in_table_order()
        if allowed is not None:
            oids_walk = [o for o in oids_walk if o in allowed]
        for oid in oids_walk:
            mol = self._mol_for_structure_tool_oid(oid, src)
            data.append((int(oid), mol))

        data = [(oid, mol) for oid, mol in data if mol is not None]
        if not data:
            QMessageBox.information(
                self._app,
                "Protonate",
                "No rows match the current scope and structure field.",
            )
            self._app.status_label.setText("Ready.")
            return

        self._app._protonate_run_ctx = {
            "out_col": out_col,
            "ph": float(ph),
            "render_2d": bool(render_2d),
            "allowed_oids": set(oid for oid, _ in data),
        }

        sig = self._ensure_protonate_signals()
        n = len(data)
        prog = self._app._tool_progress_state
        self._app._begin_tool_progress("Protonate", n)
        from ..workers.protonate_worker import ProtonateWorker

        self._app.process_queue.enqueue(
            f"Protonate ({n} molecules)",
            lambda ev, r=data, ph=ph, s=sig, st=prog, ws=self._app.signals: ProtonateWorker(
                r,
                ph,
                signals=s,
                cancel_event=ev,
                progress_state=st,
                worker_signals=ws,
                progress_message="Protonate",
            ),
        )

    def _on_protonate_finished(self, rows: list) -> None:
        from ..workers.protonate_worker import protomer_percent_column_name

        ctx = getattr(self._app, "_protonate_run_ctx", {}) or {}
        out_col = str(ctx.get("out_col") or "Protonated")
        pct_col = protomer_percent_column_name(float(ctx.get("ph", 7.4)))
        render_2d = bool(ctx.get("render_2d"))
        allowed = ctx.get("allowed_oids") or None
        self._app._protonate_run_ctx = None

        if not rows:
            self._app._finish_tool_progress("Protonate")
            self._app.status_label.setText(
                self._app._consume_partial_results_notice() or "Protonate: no results."
            )
            return

        res = []
        for row in rows:
            oid, smi, pct, pka = row[0], row[1], row[2], row[3]
            res.append(
                (
                    int(oid),
                    {
                        out_col: str(smi),
                        pct_col: f"{float(pct):.2f}",
                        "pKa": str(pka),
                    },
                )
            )
        written = self._app.on_calc_finished(
            res,
            [out_col, pct_col, "pKa"],
            progress_label="Protonate",
            on_complete=lambda cols, a=allowed, r=render_2d: self._protonate_after_table_write(
                cols, a, r
            ),
        )
        if written:
            out_col = written[0]

    def _protonate_after_table_write(
        self,
        written: list[str],
        allowed,
        render_2d: bool,
    ) -> None:
        if not render_2d or not written:
            return
        out_col = written[0]
        try:
            base_w, base_h = structure_depict_width(), structure_depict_height()
            renders, row_by_oid = self._app._build_render2d_tasks_in_table_order(
                out_col, base_w, base_h, allowed
            )
            if renders:
                self._app._start_render_2d_batch(
                    renders,
                    row_by_oid,
                    out_col,
                    column_pixmap_mode=True,
                    queue_title_prefix="Protonate: ",
                )
        except Exception:
            logger.exception("Protonate: render 2D scheduling failed")

    def _on_protonate_failed(self, msg: str) -> None:
        self._app._finish_tool_progress("Protonate")
        if msg == "Cancelled.":
            self._app.status_label.setText(
                self._app._consume_partial_results_notice() or "Cancelled."
            )
        else:
            self._app.status_label.setText(f"Protonate failed: {msg or 'Computation failed.'}")
