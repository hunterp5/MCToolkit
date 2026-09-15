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

"""Fast prepare, disconnect/neutralize, and render-2D batch tools."""

from __future__ import annotations

import logging
import threading

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QMessageBox,
)

from rdkit import Chem

from ...config import load_config
from ...utils import mol_from_binary_blob, mol_to_canonical_smiles
from ..strings import (
    TOOL_RENDER_2D,
)
from ...workers import (
    Render2DBatchProcessWorker,
    Render2DBatchHeldJob,
    DisconnectFragmentsWorker,
)
from ...display_constants import structure_depict_height, structure_depict_width

logger = logging.getLogger(__name__)


class PrepareStructuresMixin:
    def run_protonate(self) -> None:
        """Generate dominant protomer into a new column and optionally render it."""
        if not self.headers or self._table_model.rowCount() == 0:
            return
        from ..dialogs import ProtonateDialog

        candidates = self.chemistry_tool_structure_sources()
        n_sel = len(self._selected_logical_rows())
        dlg = ProtonateDialog(candidates, n_sel, self)
        self._prepare_tool_dialog(dlg)
        dlg.setAttribute(Qt.WA_DeleteOnClose, True)
        dlg.accepted.connect(lambda *_, d=dlg: self._on_protonate_dialog_accepted(d))
        dlg.show()

    def _ensure_protonate_signals(self):
        sig = getattr(self, "_protonate_signals", None)
        if sig is not None:
            return sig
        from ...workers.protonate_worker import ProtonateSignals

        sig = ProtonateSignals(self)
        sig.finished.connect(self._on_protonate_finished, Qt.QueuedConnection)
        sig.failed.connect(self._on_protonate_failed, Qt.QueuedConnection)
        self._protonate_signals = sig
        return sig

    def _on_protonate_dialog_accepted(self, dlg) -> None:
        src, ph, out_col, only_selected, render_2d = dlg.config()
        allowed = self._selected_oids_set() if only_selected else None
        if self._abort_if_only_selected_but_empty(only_selected, allowed, "Protonate"):
            return

        data: list[tuple[int, Chem.Mol | None]] = []
        oids_walk = self._all_oids_in_table_order()
        if allowed is not None:
            oids_walk = [o for o in oids_walk if o in allowed]
        for oid in oids_walk:
            mol = self._mol_for_structure_tool_oid(oid, src)
            data.append((int(oid), mol))

        data = [(oid, mol) for oid, mol in data if mol is not None]
        if not data:
            QMessageBox.information(
                self,
                "Protonate",
                "No rows match the current scope and structure field.",
            )
            self.status_label.setText("Ready.")
            return

        self._protonate_run_ctx = {
            "out_col": out_col,
            "ph": float(ph),
            "render_2d": bool(render_2d),
            "allowed_oids": set(oid for oid, _ in data),
        }

        sig = self._ensure_protonate_signals()
        n = len(data)
        prog = self._tool_progress_state
        self._begin_tool_progress("Protonate", n)
        from ...workers.protonate_worker import ProtonateWorker

        self.process_queue.enqueue(
            f"Protonate ({n} molecules)",
            lambda ev, r=data, ph=ph, s=sig, st=prog, ws=self.signals: ProtonateWorker(
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
        from ...workers.protonate_worker import protomer_percent_column_name

        ctx = getattr(self, "_protonate_run_ctx", {}) or {}
        out_col = str(ctx.get("out_col") or "Protonated")
        pct_col = protomer_percent_column_name(float(ctx.get("ph", 7.4)))
        render_2d = bool(ctx.get("render_2d"))
        allowed = ctx.get("allowed_oids") or None
        self._protonate_run_ctx = None

        if not rows:
            self._finish_tool_progress("Protonate")
            self.status_label.setText(
                self._consume_partial_results_notice() or "Protonate: no results."
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
        written = self.on_calc_finished(
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
            renders, row_by_oid = self._build_render2d_tasks_in_table_order(
                out_col, base_w, base_h, allowed
            )
            if renders:
                self._start_render_2d_batch(
                    renders,
                    row_by_oid,
                    out_col,
                    column_pixmap_mode=True,
                    queue_title_prefix="Protonate: ",
                )
        except Exception:
            logger.exception("Protonate: render 2D scheduling failed")

    def _on_protonate_failed(self, msg: str) -> None:
        self._finish_tool_progress("Protonate")
        if msg == "Cancelled.":
            self.status_label.setText(self._consume_partial_results_notice() or "Cancelled.")
        else:
            self.status_label.setText(f"Protonate failed: {msg or 'Computation failed.'}")

    def run_fast_prepare(self) -> None:
        if not self.headers or not self.mols:
            return
        from ..dialogs import FastPrepareDialog

        candidates = self.chemistry_tool_structure_sources()
        n_sel = len(self._selected_logical_rows())
        dlg = FastPrepareDialog(candidates, self.headers, n_sel, self)
        self._prepare_tool_dialog(dlg)
        dlg.setAttribute(Qt.WA_DeleteOnClose, True)
        dlg.accepted.connect(lambda *_, d=dlg: self._on_fast_prepare_dialog_accepted(d))
        dlg.show()

    def _on_fast_prepare_dialog_accepted(self, dlg) -> None:
        src, update_target, largest_col, fragments_col, only_selected, neutralize = dlg.config()
        allowed = self._selected_oids_set() if only_selected else None
        if self._abort_if_only_selected_but_empty(only_selected, allowed, "Fast Prepare"):
            return
        prepare_col = src if update_target else largest_col
        self._fast_prepare_source = prepare_col
        self._fast_prepare_allowed_oids = allowed
        self._fast_prepare_fragments_col = fragments_col
        self._fast_prepare_update_target = update_target
        self._enqueue_fast_prepare(
            src, prepare_col, only_selected=only_selected, neutralize=neutralize
        )

    def _fast_prepare_target_is_text(self, prepare_col: str) -> bool:
        """True when the Fast Prepare output column holds SMILES text rather than a depiction.

        A column the dialog named but that does not exist yet (New Column mode) counts as text: it
        is created as a plain data column before the results are written.
        """
        if prepare_col == "Structure":
            return False
        return not (
            prepare_col in self.headers and self._table_model.is_pixmap_data_column(prepare_col)
        )

    def _enqueue_fast_prepare(
        self, src: str, prepare_col: str, *, only_selected: bool, neutralize: bool = False
    ) -> None:
        """Queue the fused disconnect (and optional neutralize) pass over the rows in scope."""
        from ...workers import FastPrepareWorker

        allowed = self._selected_oids_set() if only_selected else None
        oids_walk = self._all_oids_in_table_order()
        if allowed is not None:
            oids_walk = [o for o in oids_walk if o in allowed]

        # Same source split the disconnect job used: the Structure column reads cached mols, any
        # other column is read as cell text.
        is_smiles = src != "Structure"
        data: list[tuple] = []
        if is_smiles:
            col = self.headers.index(src)
            for oid in oids_walk:
                row = self.logical_row_for_oid(oid)
                if row == -1:
                    continue
                data.append((oid, self._table_cell_text(row, col)))
        else:
            for oid in oids_walk:
                mol = self.mols.get(oid)
                if mol is None:
                    continue
                data.append((oid, mol, self._disconnect_source_text_for_oid(oid, src)))

        if not data:
            QMessageBox.information(
                self,
                "Fast Prepare",
                "No rows match the current scope and structure field.",
            )
            self.status_label.setText("Ready.")
            return

        # Canonical SMILES is only needed when the output column stores text; computing it in the
        # child processes keeps MolToSmiles off the GUI thread.
        need_smiles = self._fast_prepare_target_is_text(prepare_col)
        cfg = load_config()
        self._begin_tool_progress("Fast prepare", len(data))
        self.process_queue.enqueue(
            "Fast prepare: prepare structures",
            lambda ev, d=data, n=bool(neutralize), s=self.signals, ps=self._tool_progress_state: FastPrepareWorker(
                d,
                s,
                is_smiles=is_smiles,
                need_smiles=need_smiles,
                neutralize=n,
                cancel_event=ev,
                batch_size=int(cfg.fast_prepare_batch_size),
                process_pool_min_rows=int(cfg.fast_prepare_process_pool_min_rows),
                progress_state=ps,
            ),
        )

    def on_fast_prepare_finished(self, results) -> None:
        """Apply fused disconnect + neutralize results, then render the new depictions.

        One writeback per row: the old two-job chain wrote the disconnected parent and then
        immediately overwrote it with the neutralized molecule.
        """
        self.table.setSortingEnabled(False)
        prepare_col = getattr(self, "_fast_prepare_source", "Structure")
        fragments_col = getattr(self, "_fast_prepare_fragments_col", "Fragments")
        update_target = getattr(self, "_fast_prepare_update_target", True)
        allowed_oids = getattr(self, "_fast_prepare_allowed_oids", None)
        self._fast_prepare_source = "Structure"
        self._fast_prepare_allowed_oids = None
        self._fast_prepare_fragments_col = "Fragments"
        self._fast_prepare_update_target = True

        self._ensure_disconnect_output_column(fragments_col)
        if not update_target:
            self._ensure_disconnect_output_column(prepare_col)

        target_is_text = self._fast_prepare_target_is_text(prepare_col)
        write_fragments = fragments_col in self.headers
        smiles_h = self._canonical_smiles_header_for_updates()
        sync_smiles_col = smiles_h is not None and smiles_h == prepare_col and target_is_text

        for oid, blob, fragments, smiles in results:
            mol = self._fast_prepare_mol_from_blob(blob)
            if mol is None:
                continue
            if target_is_text:
                self._table_model.set_cell_text(oid, prepare_col, smiles)
                if sync_smiles_col:
                    self._table_model.set_cell_text(oid, smiles_h, smiles)
            else:
                self.mols[oid] = mol
                if prepare_col == "Structure":
                    self._table_model.set_structure_pixmap(oid, None)
                else:
                    self._table_model.set_column_pixmap(oid, prepare_col, None)
            if write_fragments:
                self._table_model.set_cell_text(oid, fragments_col, fragments)

        self.schedule_calculate_global_bounds()
        self._clear_tool_progress()

        if results and not getattr(self, "_render2d_batch_active", False):
            renders, row_by_oid = self._build_render2d_tasks_in_table_order(
                prepare_col, structure_depict_width(), structure_depict_height(), allowed_oids
            )
            if renders:
                self.status_label.setText("Fast prepare: rendering 2D…")
                self._start_render_2d_batch(
                    renders,
                    row_by_oid,
                    prepare_col,
                    column_pixmap_mode=(prepare_col != "Structure"),
                    queue_title_prefix="Fast prepare: ",
                )
                return
        self.status_label.setText(self._consume_partial_results_notice() or "Fast prepare done.")

    @staticmethod
    def _fast_prepare_mol_from_blob(blob) -> Chem.Mol | None:
        """Rebuild a molecule from the worker's binary payload."""
        return mol_from_binary_blob(blob)  # type: ignore[return-value]

    def run_disconnect_fragments(self) -> None:
        if not self.headers or not self.mols:
            return
        candidates = self.chemistry_tool_structure_sources()
        from ..dialogs import DisconnectFragmentsDialog

        n_sel = len(self._selected_logical_rows())
        dlg = DisconnectFragmentsDialog(candidates, self.headers, n_sel, self)
        self._prepare_tool_dialog(dlg)
        dlg.setAttribute(Qt.WA_DeleteOnClose, True)
        dlg.accepted.connect(lambda *_, d=dlg: self._on_disconnect_fragments_dialog_accepted(d))
        dlg.show()

    def _on_disconnect_fragments_dialog_accepted(self, dlg) -> None:
        src, update_target, largest_col, fragments_col, only_selected, no_render_2d = dlg.config()
        allowed = self._selected_oids_set() if only_selected else None
        if self._abort_if_only_selected_but_empty(
            only_selected, allowed, "Disconnect Largest Fragments"
        ):
            return
        self.status_label.setText("Disconnecting fragments…")
        self._enqueue_disconnect_fragments(
            src,
            update_target=update_target,
            largest_col=largest_col,
            fragments_col=fragments_col,
            only_selected=only_selected,
            no_render_2d=no_render_2d,
        )

    def _enqueue_disconnect_fragments(
        self,
        src: str,
        *,
        update_target: bool,
        largest_col: str | None,
        fragments_col: str,
        only_selected: bool,
        no_render_2d: bool,
        queue_title_prefix: str = "",
    ) -> None:
        allowed = self._selected_oids_set() if only_selected else None
        self._disconnect_source = src
        self._disconnect_update_target = update_target
        self._disconnect_largest_col = src if update_target else largest_col
        self._disconnect_fragments_col = fragments_col
        self._disconnect_no_render_2d = no_render_2d
        if src == "Structure":
            data = []
            oids_walk = self._all_oids_in_table_order()
            if allowed is not None:
                oids_walk = [o for o in oids_walk if o in allowed]
            for oid in oids_walk:
                mol = self.mols.get(oid)
                if mol is None:
                    continue
                raw = self._disconnect_source_text_for_oid(oid, src)
                data.append((oid, mol, raw))
            if not data:
                QMessageBox.information(
                    self,
                    "Disconnect Largest Fragments",
                    "No rows match the current scope and structure field.",
                )
                self.status_label.setText("Ready.")
                return
            title = f"{queue_title_prefix}disconnect largest fragments"
            self._begin_tool_progress("Disconnect fragments", len(data))
            self.process_queue.enqueue(
                title,
                lambda ev, d=data, s=self.signals, ps=self._tool_progress_state: DisconnectFragmentsWorker(
                    d, s, is_smiles=False, cancel_event=ev, progress_state=ps
                ),
            )
        else:
            col = self.headers.index(src)
            data = []
            oids_walk = self._all_oids_in_table_order()
            if allowed is not None:
                oids_walk = [o for o in oids_walk if o in allowed]
            for oid in oids_walk:
                r = self.logical_row_for_oid(oid)
                if r == -1:
                    continue
                data.append((oid, self._table_cell_text(r, col)))
            if not data:
                QMessageBox.information(
                    self,
                    "Disconnect Largest Fragments",
                    "No rows match the current scope and structure field.",
                )
                self.status_label.setText("Ready.")
                return
            title = f"{queue_title_prefix}disconnect largest fragments (column)"
            self._begin_tool_progress("Disconnect fragments", len(data))
            self.process_queue.enqueue(
                title,
                lambda ev, d=data, s=self.signals, ps=self._tool_progress_state: DisconnectFragmentsWorker(
                    d, s, is_smiles=True, cancel_event=ev, progress_state=ps
                ),
            )

    def _mol_for_structure_tool_oid(self, oid: int, src: str) -> Chem.Mol | None:
        """Molecule for a prepare-structures tool row and source column."""
        row = self.logical_row_for_oid(oid)
        if row < 0:
            return None
        if src == "Structure":
            mol = self.mols.get(oid)
            if mol is not None:
                return mol
            return self._mol_for_structure_row(row)
        if src not in self.headers:
            return None
        col = self.headers.index(src)
        raw = ""
        if self._table_model.is_pixmap_data_column(src):
            raw = (self._table_model.backing_value_for_row_header(row, src) or "").strip()
        else:
            raw = (self._table_cell_text(row, col) or "").strip()
            if not raw:
                raw = (self._table_model.backing_value_for_row_header(row, src) or "").strip()
        if not raw:
            return None
        return self._mol_from_structure_text(raw)

    def run_add_explicit_hydrogens(self) -> None:
        if not self.headers or not self.mols:
            return
        from ..dialogs import AddExplicitHydrogensDialog

        candidates = self.chemistry_tool_structure_sources()
        n_sel = len(self._selected_logical_rows())
        dlg = AddExplicitHydrogensDialog(candidates, n_sel, self)
        self._prepare_tool_dialog(dlg)
        dlg.setAttribute(Qt.WA_DeleteOnClose, True)
        dlg.accepted.connect(lambda *_, d=dlg: self._on_add_explicit_hydrogens_dialog_accepted(d))
        dlg.show()

    def _on_add_explicit_hydrogens_dialog_accepted(self, dlg) -> None:
        src, only_selected, no_render_2d = dlg.config()
        allowed = self._selected_oids_set() if only_selected else None
        if self._abort_if_only_selected_but_empty(only_selected, allowed, "Add Explicit Hydrogens"):
            return
        self.status_label.setText("Adding explicit hydrogens…")
        self._enqueue_add_explicit_hydrogens(
            src,
            only_selected=only_selected,
            no_render_2d=no_render_2d,
        )

    def _enqueue_add_explicit_hydrogens(
        self,
        src: str,
        *,
        only_selected: bool = False,
        no_render_2d: bool = False,
    ) -> None:
        from ...workers import AddExplicitHydrogensWorker

        self._add_explicit_hydrogens_source = src
        self._add_explicit_hydrogens_no_render_2d = no_render_2d
        allowed = self._selected_oids_set() if only_selected else None
        data: list[tuple[int, Chem.Mol]] = []
        oids_walk = self._all_oids_in_table_order()
        if allowed is not None:
            oids_walk = [o for o in oids_walk if o in allowed]
        for oid in oids_walk:
            mol = self._mol_for_structure_tool_oid(oid, src)
            if mol is not None:
                data.append((oid, mol))
        if not data:
            QMessageBox.information(
                self,
                "Add Explicit Hydrogens",
                "No rows match the current scope and structure field.",
            )
            self.status_label.setText("Ready.")
            return
        self._begin_tool_progress("Add explicit hydrogens", len(data))
        self.process_queue.enqueue(
            "Add explicit hydrogens",
            lambda ev, d=data, s=self.signals, ps=self._tool_progress_state: AddExplicitHydrogensWorker(
                d, s, is_smiles=False, cancel_event=ev, progress_state=ps
            ),
        )

    def run_remove_explicit_hydrogens(self) -> None:
        if not self.headers or not self.mols:
            return
        from ..dialogs import RemoveExplicitHydrogensDialog

        candidates = self.chemistry_tool_structure_sources()
        n_sel = len(self._selected_logical_rows())
        dlg = RemoveExplicitHydrogensDialog(candidates, n_sel, self)
        self._prepare_tool_dialog(dlg)
        dlg.setAttribute(Qt.WA_DeleteOnClose, True)
        dlg.accepted.connect(
            lambda *_, d=dlg: self._on_remove_explicit_hydrogens_dialog_accepted(d)
        )
        dlg.show()

    def _on_remove_explicit_hydrogens_dialog_accepted(self, dlg) -> None:
        src, only_selected, no_render_2d = dlg.config()
        allowed = self._selected_oids_set() if only_selected else None
        if self._abort_if_only_selected_but_empty(
            only_selected, allowed, "Remove Explicit Hydrogens"
        ):
            return
        self.status_label.setText("Removing explicit hydrogens…")
        self._enqueue_remove_explicit_hydrogens(
            src,
            only_selected=only_selected,
            no_render_2d=no_render_2d,
        )

    def _enqueue_remove_explicit_hydrogens(
        self,
        src: str,
        *,
        only_selected: bool = False,
        no_render_2d: bool = False,
    ) -> None:
        from ...workers import RemoveExplicitHydrogensWorker

        self._remove_explicit_hydrogens_source = src
        self._remove_explicit_hydrogens_no_render_2d = no_render_2d
        allowed = self._selected_oids_set() if only_selected else None
        data: list[tuple[int, Chem.Mol]] = []
        oids_walk = self._all_oids_in_table_order()
        if allowed is not None:
            oids_walk = [o for o in oids_walk if o in allowed]
        for oid in oids_walk:
            mol = self._mol_for_structure_tool_oid(oid, src)
            if mol is not None:
                data.append((oid, mol))
        if not data:
            QMessageBox.information(
                self,
                "Remove Explicit Hydrogens",
                "No rows match the current scope and structure field.",
            )
            self.status_label.setText("Ready.")
            return
        self._begin_tool_progress("Remove explicit hydrogens", len(data))
        self.process_queue.enqueue(
            "Remove explicit hydrogens",
            lambda ev, d=data, s=self.signals, ps=self._tool_progress_state: RemoveExplicitHydrogensWorker(
                d, s, is_smiles=False, cancel_event=ev, progress_state=ps
            ),
        )

    def run_neutralize(self) -> None:
        if not self.headers or not self.mols:
            return
        from ..dialogs import NeutralizeDialog

        candidates = self.chemistry_tool_structure_sources()
        n_sel = len(self._selected_logical_rows())
        dlg = NeutralizeDialog(candidates, n_sel, self)
        self._prepare_tool_dialog(dlg)
        dlg.setAttribute(Qt.WA_DeleteOnClose, True)
        dlg.accepted.connect(lambda *_, d=dlg: self._on_neutralize_dialog_accepted(d))
        dlg.show()

    def _on_neutralize_dialog_accepted(self, dlg) -> None:
        src, only_selected, no_render_2d = dlg.config()
        allowed = self._selected_oids_set() if only_selected else None
        if self._abort_if_only_selected_but_empty(only_selected, allowed, "Neutralize"):
            return
        self.status_label.setText("Neutralizing structures…")
        self._enqueue_neutralize(
            src,
            only_selected=only_selected,
            no_render_2d=no_render_2d,
        )

    def _enqueue_neutralize(
        self,
        src: str,
        *,
        only_selected: bool = False,
        no_render_2d: bool = False,
        rows: list[tuple[int, Chem.Mol]] | None = None,
        queue_title_prefix: str = "",
    ) -> None:
        from ...workers import NeutralizeWorker

        self._neutralize_source = src
        self._neutralize_no_render_2d = no_render_2d
        if rows is None:
            allowed = self._selected_oids_set() if only_selected else None
            data: list[tuple[int, Chem.Mol]] = []
            oids_walk = self._all_oids_in_table_order()
            if allowed is not None:
                oids_walk = [o for o in oids_walk if o in allowed]
            for oid in oids_walk:
                mol = self._mol_for_structure_tool_oid(oid, src)
                if mol is not None:
                    data.append((oid, mol))
        else:
            data = list(rows)
        if not data:
            QMessageBox.information(
                self,
                "Neutralize",
                "No rows match the current scope and structure field.",
            )
            self.status_label.setText("Ready.")
            return
        title = f"{queue_title_prefix}neutralize".strip() or "Neutralize"
        self._begin_tool_progress("Neutralize", len(data))
        self.process_queue.enqueue(
            title,
            lambda ev, d=data, s=self.signals, ps=self._tool_progress_state: NeutralizeWorker(
                d, s, is_smiles=False, cancel_event=ev, progress_state=ps
            ),
        )

    def on_neutralize_finished(self, results) -> None:
        src = getattr(self, "_neutralize_source", "Structure")
        no_render_2d = getattr(self, "_neutralize_no_render_2d", False)
        self._neutralize_source = "Structure"
        self._neutralize_no_render_2d = False

        render_target = src == "Structure" or (
            src in self.headers and self._table_model.is_pixmap_data_column(src)
        )
        smiles_h = self._canonical_smiles_header_for_updates()
        update_smiles_col = smiles_h is not None and src == smiles_h

        for oid, mol in results:
            if mol is None:
                continue
            if src == "Structure":
                self.mols[oid] = mol
                self._table_model.set_structure_pixmap(oid, None)
            elif src in self.headers:
                if self._table_model.is_pixmap_data_column(src):
                    try:
                        smi = mol_to_canonical_smiles(mol)
                    except Exception:
                        smi = ""
                    if smi:
                        self._table_model.set_backing_text(oid, src, smi)
                    self._table_model.set_column_pixmap(oid, src, None)
                else:
                    self._table_model.set_cell_text(oid, src, mol_to_canonical_smiles(mol))
            if update_smiles_col:
                self._table_model.set_cell_text(oid, smiles_h, mol_to_canonical_smiles(mol))

        self.schedule_calculate_global_bounds()
        self._clear_tool_progress()
        if (
            results
            and render_target
            and not no_render_2d
            and not getattr(self, "_render2d_batch_active", False)
        ):
            base_w, base_h = structure_depict_width(), structure_depict_height()
            renders = []
            row_by_oid: dict[int, int] = {}
            for oid, mol in results:
                if mol is None:
                    continue
                row = self.logical_row_for_oid(oid)
                if row < 0:
                    continue
                rw, rh = (
                    (structure_depict_width() * 2, structure_depict_height() * 2)
                    if oid in self.zoomed_ids
                    else (base_w, base_h)
                )
                renders.append((oid, mol, rw, rh))
                row_by_oid[oid] = row
            if renders:
                column_pixmap_mode = src != "Structure"
                self._start_render_2d_batch(
                    renders, row_by_oid, src, column_pixmap_mode=column_pixmap_mode
                )
                return
        self.status_label.setText(self._consume_partial_results_notice() or "Done.")

    def on_add_explicit_hydrogens_finished(self, results) -> None:
        src = getattr(self, "_add_explicit_hydrogens_source", "Structure")
        no_render_2d = getattr(self, "_add_explicit_hydrogens_no_render_2d", False)
        self._add_explicit_hydrogens_source = "Structure"
        self._add_explicit_hydrogens_no_render_2d = False

        render_target = src == "Structure" or (
            src in self.headers and self._table_model.is_pixmap_data_column(src)
        )
        smiles_h = self._canonical_smiles_header_for_updates()
        update_smiles_col = smiles_h is not None and src == smiles_h

        for oid, mol in results:
            if mol is None:
                continue
            if src == "Structure":
                self.mols[oid] = mol
                self._table_model.set_structure_pixmap(oid, None)
            elif src in self.headers:
                if self._table_model.is_pixmap_data_column(src):
                    try:
                        smi = mol_to_canonical_smiles(mol)
                    except Exception:
                        smi = ""
                    if smi:
                        self._table_model.set_backing_text(oid, src, smi)
                    self._table_model.set_column_pixmap(oid, src, None)
                else:
                    self._table_model.set_cell_text(oid, src, mol_to_canonical_smiles(mol))
            if update_smiles_col:
                self._table_model.set_cell_text(oid, smiles_h, mol_to_canonical_smiles(mol))

        self.schedule_calculate_global_bounds()
        self._clear_tool_progress()
        if (
            results
            and render_target
            and not no_render_2d
            and not getattr(self, "_render2d_batch_active", False)
        ):
            base_w, base_h = structure_depict_width(), structure_depict_height()
            renders = []
            row_by_oid: dict[int, int] = {}
            for oid, mol in results:
                if mol is None:
                    continue
                row = self.logical_row_for_oid(oid)
                if row < 0:
                    continue
                rw, rh = (
                    (structure_depict_width() * 2, structure_depict_height() * 2)
                    if oid in self.zoomed_ids
                    else (base_w, base_h)
                )
                renders.append((oid, mol, rw, rh))
                row_by_oid[oid] = row
            if renders:
                column_pixmap_mode = src != "Structure"
                self._start_render_2d_batch(
                    renders, row_by_oid, src, column_pixmap_mode=column_pixmap_mode
                )
                return
        self.status_label.setText(self._consume_partial_results_notice() or "Done.")

    def on_remove_explicit_hydrogens_finished(self, results) -> None:
        src = getattr(self, "_remove_explicit_hydrogens_source", "Structure")
        no_render_2d = getattr(self, "_remove_explicit_hydrogens_no_render_2d", False)
        self._remove_explicit_hydrogens_source = "Structure"
        self._remove_explicit_hydrogens_no_render_2d = False

        render_target = src == "Structure" or (
            src in self.headers and self._table_model.is_pixmap_data_column(src)
        )
        smiles_h = self._canonical_smiles_header_for_updates()
        update_smiles_col = smiles_h is not None and src == smiles_h

        for oid, mol in results:
            if mol is None:
                continue
            if src == "Structure":
                self.mols[oid] = mol
                self._table_model.set_structure_pixmap(oid, None)
            elif src in self.headers:
                if self._table_model.is_pixmap_data_column(src):
                    try:
                        smi = mol_to_canonical_smiles(mol)
                    except Exception:
                        smi = ""
                    if smi:
                        self._table_model.set_backing_text(oid, src, smi)
                    self._table_model.set_column_pixmap(oid, src, None)
                else:
                    self._table_model.set_cell_text(oid, src, mol_to_canonical_smiles(mol))
            if update_smiles_col:
                self._table_model.set_cell_text(oid, smiles_h, mol_to_canonical_smiles(mol))

        self.schedule_calculate_global_bounds()
        self._clear_tool_progress()
        if (
            results
            and render_target
            and not no_render_2d
            and not getattr(self, "_render2d_batch_active", False)
        ):
            base_w, base_h = structure_depict_width(), structure_depict_height()
            renders = []
            row_by_oid: dict[int, int] = {}
            for oid, mol in results:
                if mol is None:
                    continue
                row = self.logical_row_for_oid(oid)
                if row < 0:
                    continue
                rw, rh = (
                    (structure_depict_width() * 2, structure_depict_height() * 2)
                    if oid in self.zoomed_ids
                    else (base_w, base_h)
                )
                renders.append((oid, mol, rw, rh))
                row_by_oid[oid] = row
            if renders:
                column_pixmap_mode = src != "Structure"
                self._start_render_2d_batch(
                    renders, row_by_oid, src, column_pixmap_mode=column_pixmap_mode
                )
                return
        self.status_label.setText(self._consume_partial_results_notice() or "Done.")

    def _build_render2d_tasks_from_mols(
        self,
        base_w: int,
        base_h: int,
        allowed_oids: set[int] | None = None,
    ) -> tuple[list, dict[int, int]]:
        """Build render tasks from ``self.mols`` (O(n) with O(1) row lookup; used after file/SQL ingest)."""
        renders: list = []
        row_by_oid: dict[int, int] = {}
        for oid, mol in self.mols.items():
            if allowed_oids is not None and int(oid) not in allowed_oids:
                continue
            if mol is None:
                continue
            row = self._table_model.logical_row_for_oid(int(oid))
            if row < 0:
                continue
            rw, rh = (
                (structure_depict_width() * 2, structure_depict_height() * 2)
                if int(oid) in self.zoomed_ids
                else (base_w, base_h)
            )
            renders.append((int(oid), mol, rw, rh))
            row_by_oid[int(oid)] = row
        return renders, row_by_oid

    def _build_render2d_tasks_in_table_order(
        self,
        src: str,
        base_w: int,
        base_h: int,
        allowed_oids: set[int] | None = None,
    ) -> tuple[list, dict[int, int]]:
        """Collect (oid, mol, w, h) tasks in current visual row order (top to bottom) and oid→row map."""
        renders = []
        row_by_oid: dict[int, int] = {}
        if src != "Structure" and src not in self.headers:
            return [], {}
        for r in range(self._table_model.rowCount()):
            t0 = self._table_model.cell_text(r, 0)
            if not t0.isdigit():
                continue
            oid = int(t0)
            if allowed_oids is not None and oid not in allowed_oids:
                continue
            if src == "Structure":
                mol = self.mols.get(oid)
                if mol is None:
                    mol = self._mol_for_structure_row(r)
                if mol is None:
                    continue
                self.mols[oid] = mol
            else:
                mol = self._mol_for_render2d_source(r, src)
                if mol is None:
                    continue
            rw, rh = (
                (structure_depict_width() * 2, structure_depict_height() * 2)
                if oid in self.zoomed_ids
                else (base_w, base_h)
            )
            renders.append((oid, mol, rw, rh))
            row_by_oid[oid] = r
        return renders, row_by_oid

    def _build_render2d_tasks_for_oids(
        self,
        oids: list[int],
        base_w: int,
        base_h: int,
    ) -> tuple[list, dict[int, int]]:
        """Build render tasks for explicit oids (O(n) in ``oids``; used after bulk external append)."""
        renders: list = []
        row_by_oid: dict[int, int] = {}
        for oid in oids:
            row = self._table_model.logical_row_for_oid(int(oid))
            if row < 0:
                continue
            mol = self.mols.get(int(oid))
            if mol is None:
                mol = self._mol_for_structure_row(row)
            if mol is None:
                continue
            self.mols[int(oid)] = mol
            rw, rh = (
                (structure_depict_width() * 2, structure_depict_height() * 2)
                if int(oid) in self.zoomed_ids
                else (base_w, base_h)
            )
            renders.append((int(oid), mol, rw, rh))
            row_by_oid[int(oid)] = row
        return renders, row_by_oid

    def _try_auto_render_all_structures_after_ingest(self) -> bool:
        """Queue 2D renders for every row with an in-memory Structure mol (file ingest, SQL, or session)."""
        if getattr(self, "_render2d_batch_active", False):
            return False
        if not self.headers or self._table_model.rowCount() == 0:
            return False
        n_rows = self._table_model.rowCount()
        cfg = load_config()
        max_auto = int(cfg.auto_render_2d_max_rows)
        if max_auto > 0 and n_rows > max_auto:
            self.status_label.setText(
                f"Loaded {n_rows:,} rows — auto 2D render skipped (limit {max_auto:,}). "
                "Use Tools → Render 2D for visible or selected rows."
            )
            return False
        self.status_label.setText(f"{TOOL_RENDER_2D}: collecting structures…")
        base_w, base_h = structure_depict_width(), structure_depict_height()
        renders, row_by_oid = self._build_render2d_tasks_from_mols(base_w, base_h, None)
        if not renders:
            # Session restore may have rows before mols are keyed; rebuild from table cells.
            renders, row_by_oid = self._build_render2d_tasks_in_table_order(
                "Structure", base_w, base_h, None
            )
        if not renders:
            return False
        self._render2d_after_ingest = True
        self._start_render_2d_batch(renders, row_by_oid, "Structure")
        return True

    def _auto_render2d_blocks_workspace_reveal(self, n_rows: int | None = None) -> bool:
        """True when ingest/session should wait for auto Render 2D before showing the table.

        Always wait when auto-render is started so the loading overlay stays up until
        Structure images are ready. ``n_rows`` is accepted for call-site compatibility.
        """
        _ = n_rows
        return True

    def _restore_render2d_batch_environment(self) -> None:
        """Re-enable sorting and thread pool after a Render 2D run (or if cleared mid-batch)."""
        self._render2d_accept_session = None
        self._render2d_pending = {}
        self._render2d_batch_oids_ordered = []
        self._render2d_snapshot = None
        self._render2d_eager_flush_queue = None
        self._render2d_eager_flush_idx = 0
        self._render2d_eager_uniform_height = False
        self._render2d_row_by_oid = None
        pix_target = getattr(self, "_render2d_pixmap_target", None)
        self._render2d_pixmap_target = None
        self._render2d_column_pixmap_mode = True
        self._resize_columns_after_render2d(pix_target)
        finishing_batch = bool(getattr(self, "_render2d_batch_active", False))
        if finishing_batch:
            pending = getattr(self, "_pending_session_table_layout", None)
            restore_chrome = getattr(self, "_restore_session_table_chrome", None)
            if pending and callable(restore_chrome):
                restore_chrome(pending)
            elif pending:
                restore = getattr(self, "_restore_table_layout", None)
                if callable(restore):
                    restore(pending)
            restore_ws = getattr(self, "_restore_pending_workspace_layout", None)
            if callable(restore_ws):
                restore_ws()
            finish_ws = getattr(self, "_finish_deferred_session_workspace_restore", None)
            if callable(finish_ws):
                from PyQt5.QtCore import QTimer

                QTimer.singleShot(0, finish_ws)
        try:
            self.table.setUpdatesEnabled(True)
        except Exception:
            pass
        if self._render2d_saved_sort_enabled is not None:
            try:
                self.table.setSortingEnabled(self._render2d_saved_sort_enabled)
            except Exception:
                pass
            self._render2d_saved_sort_enabled = None
        self._render2d_batch_active = False
        self._render2d_cancel_event = None
        hub = getattr(self, "background_activity", None)
        if hub is not None:
            hub.notify_changed()
        done_ev = getattr(self, "_render2d_batch_done_event", None)
        if done_ev is not None:
            done_ev.set()
        pq = getattr(self, "process_queue", None)
        if pq is not None:
            pq.schedule_resume()
        on_ingest = getattr(self, "_ingest_on_render2d_batch_finished", None)
        if callable(on_ingest):
            on_ingest()
        on_session = getattr(self, "_session_on_render2d_batch_finished", None)
        if callable(on_session):
            on_session()

    def cancel_render_2d_batch(self) -> bool:
        """Stop a Tools → Render 2D batch: no further chunks, workers skip drawing if not started."""
        if not self._render2d_batch_active:
            return False
        ev = getattr(self, "_render2d_cancel_event", None)
        if ev is not None:
            ev.set()
        self._render2d_queue = None
        self._render2d_accept_session = None
        self._render2d_pending.clear()
        self._render2d_batch_oids_ordered.clear()
        self._render2d_eager_flush_queue = None
        self._render2d_eager_flush_idx = 0
        self._render2d_eager_uniform_height = False
        if getattr(self, "_render2d_lazy_flush", False) and not getattr(
            self, "_render2d_pixmap_target", None
        ):
            self._table_model.clear_structure_png_store()
        snap = getattr(self, "_render2d_snapshot", None)
        target = getattr(self, "_render2d_pixmap_target", None)
        if snap:
            column_pixmap_mode = getattr(self, "_render2d_column_pixmap_mode", True)
            set_pixmap = (
                self._table_model.set_column_pixmap
                if column_pixmap_mode
                else self._table_model.set_cell_pixmap
            )
            for oid, pm in snap.items():
                if target:
                    set_pixmap(oid, target, pm)
                else:
                    self._table_model.set_structure_pixmap(oid, pm)
        self._render2d_snapshot = None
        self._render2d_lazy_flush = False
        self._render2d_eager_flush_queue = None
        self._render2d_eager_flush_idx = 0
        self._render2d_eager_uniform_height = False
        self._import_progress_active = False
        self._clear_tool_progress()
        self._restore_render2d_batch_environment()
        return True

    def run_render_2d_structures(self) -> None:
        """Queue 2D structure renders for all rows (after deferred load)."""
        if not self.headers or self._table_model.rowCount() == 0:
            QMessageBox.information(
                self, TOOL_RENDER_2D, "Load a table with at least one row first."
            )
            return
        if self._render2d_batch_active or self.process_queue.has_running_job():
            QMessageBox.warning(
                self,
                TOOL_RENDER_2D,
                "A render or background tool is already running. Wait for it to finish or cancel it from Processes.",
            )
            return
        candidates = self.chemistry_tool_structure_sources()
        from ..dialogs import Render2DStructureDialog

        rd = Render2DStructureDialog(candidates, len(self._selected_logical_rows()), self)
        self._prepare_tool_dialog(rd)
        rd.setAttribute(Qt.WA_DeleteOnClose, True)
        rd.accepted.connect(lambda *_, d=rd: self._on_render_2d_dialog_accepted(d))
        rd.show()

    def _on_render_2d_dialog_accepted(self, rd) -> None:
        src = rd.chosen_source()
        only_selected = rd.only_selected_rows()
        allowed_oids = self._selected_oids_set() if only_selected else None
        if self._abort_if_only_selected_but_empty(only_selected, allowed_oids, TOOL_RENDER_2D):
            return
        self.status_label.setText(f"{TOOL_RENDER_2D}: collecting structures…")
        base_w, base_h = structure_depict_width(), structure_depict_height()
        renders, row_by_oid = self._build_render2d_tasks_in_table_order(
            src, base_w, base_h, allowed_oids
        )
        if not renders:
            QMessageBox.information(
                self,
                TOOL_RENDER_2D,
                "No valid structures were found for the selected source.",
            )
            self.status_label.setText("No structures rendered.")
            return
        self._start_render_2d_batch(
            renders, row_by_oid, src, column_pixmap_mode=(src != "Structure")
        )

    def _start_render_2d_batch(
        self,
        renders,
        row_by_oid,
        src: str = "Structure",
        *,
        column_pixmap_mode: bool = True,
        queue_title_prefix: str = "",
    ) -> None:
        """Queue batch 2D renders on the serial process queue (waits behind other tools)."""
        if getattr(self, "_render2d_batch_active", False):
            return
        title = f"{queue_title_prefix}render 2D ({len(renders)} rows)".strip()
        payload = (renders, row_by_oid, src, column_pixmap_mode)
        self.process_queue.enqueue(
            title,
            lambda ev, p=payload: Render2DBatchHeldJob(self, p, ev),
        )

    def _begin_render2d_batch_impl(
        self,
        renders,
        row_by_oid,
        src: str = "Structure",
        *,
        column_pixmap_mode: bool = True,
        cancel_event: threading.Event | None = None,
    ) -> None:
        """Start batch 2D rendering on the GUI thread (called from :class:`Render2DBatchHeldJob`)."""
        if cancel_event is not None and cancel_event.is_set():
            return
        self._render2d_session_id += 1
        self._render2d_batch_session_tag = self._render2d_session_id
        self._render2d_accept_session = self._render2d_batch_session_tag
        self._render2d_pixmap_target = None if src == "Structure" else src
        self._render2d_column_pixmap_mode = bool(column_pixmap_mode)
        if self._render2d_pixmap_target and self._render2d_column_pixmap_mode:
            self._table_model.register_pixmap_column(self._render2d_pixmap_target)
        self._render2d_saved_sort_enabled = self.table.isSortingEnabled()
        self.table.setSortingEnabled(False)
        self._render2d_batch_active = True
        self._render2d_row_by_oid = row_by_oid
        oids = [oid for oid, _, _, _ in renders]
        self._render2d_batch_oids_ordered = oids
        self._render2d_pending = {}
        structure_column = self._render2d_pixmap_target is None
        after_ingest = bool(getattr(self, "_render2d_after_ingest", False))
        self._render2d_after_ingest = False
        cfg = load_config()
        if after_ingest and structure_column:
            lazy_structure = len(oids) >= int(cfg.structure_render_lazy_after_ingest_min_rows)
        else:
            lazy_structure = self._render2d_use_lazy_structure_flush(
                len(oids), structure_column=structure_column
            )
        self._render2d_lazy_flush = lazy_structure
        skip_snapshot = after_ingest or lazy_structure
        tgt = self._render2d_pixmap_target
        if tgt:
            if self._render2d_column_pixmap_mode:
                self._render2d_snapshot = self._table_model.snapshot_column_pixmaps(tgt, oids)
                clear_pixmap = self._table_model.set_column_pixmap
            else:
                self._render2d_snapshot = {
                    oid: self._table_model.cell_pixmap_copy(oid, tgt) for oid in oids
                }
                clear_pixmap = self._table_model.set_cell_pixmap
            for oid in oids:
                clear_pixmap(oid, tgt, None)
        elif lazy_structure:
            self._render2d_snapshot = {}
            self._table_model.clear_structure_png_store()
            self._table_model.clear_structure_pixmaps_for_oids(oids, emit=False)
        else:
            if skip_snapshot:
                self._render2d_snapshot = {}
            elif len(oids) <= cfg.structure_render_lazy_min_rows:
                self._render2d_snapshot = self._table_model.snapshot_structure_pixmaps(oids)
            else:
                self._render2d_snapshot = {}
            self._table_model.clear_structure_pixmaps_for_oids(oids, emit=False)
        if structure_column and not lazy_structure:
            self._table_model.notify_structure_column_changed()
        self._render2d_progress_last_emit = 0.0
        self._render2d_progress_last_done = 0
        self._import_progress_active = True
        self._import_render_goal = len(renders)
        self._import_render_done = 0
        self._on_tool_progress(TOOL_RENDER_2D, 0, len(renders))
        self._render2d_cancel_event = (
            cancel_event if cancel_event is not None else threading.Event()
        )
        self._render2d_queue = None
        hub = getattr(self, "background_activity", None)
        if hub is not None:
            hub.notify_changed()
        self._render_threadpool.start(
            Render2DBatchProcessWorker(
                renders,
                self.signals,
                self._render2d_cancel_event,
                self._render2d_batch_session_tag,
            )
        )

    def _render2d_source_header_for_column(self, col: int) -> str:
        """Header used as Render 2D source and pixmap target (clicked column, else Structure)."""
        if 0 <= col < len(self.headers):
            return self.headers[col]
        return "Structure"

    def _mol_for_render2d_source(self, row: int, src: str) -> Chem.Mol | None:
        """Molecule to draw for one row from the chosen source column."""
        if row < 0 or row >= self._table_model.rowCount():
            return None
        if src == "Structure":
            return self._mol_for_structure_row(row)
        if src not in self.headers:
            return None
        ci = self.headers.index(src)
        if self._table_model.is_pixmap_data_column(src):
            raw = (self._table_model.backing_value_for_row_header(row, src) or "").strip()
            return self._mol_from_structure_text(raw) if raw else None
        raw = (self._table_cell_text(row, ci) or "").strip()
        if not raw:
            raw = (self._table_model.backing_value_for_row_header(row, src) or "").strip()
        if not raw:
            return None
        return self._mol_from_structure_text(raw)

    def run_render_2d_for_table_row(self, row: int, col: int | None = None) -> None:
        """Run Render 2D for one row: read chemistry from ``col`` and write the pixmap into that column."""
        if not self.headers or self._table_model.rowCount() == 0:
            QMessageBox.information(
                self, TOOL_RENDER_2D, "Load a table with at least one row first."
            )
            return
        if self._render2d_batch_active or self.process_queue.has_running_job():
            QMessageBox.warning(
                self,
                TOOL_RENDER_2D,
                "A render or background tool is already running. Wait for it to finish or cancel it from Processes.",
            )
            return
        if row < 0 or row >= self._table_model.rowCount():
            return
        t0 = self._table_model.cell_text(row, 0)
        oid = int(t0) if t0.isdigit() else None
        if oid is None:
            QMessageBox.information(
                self, TOOL_RENDER_2D, "Could not resolve this row’s compound id."
            )
            return
        src = self._render2d_source_header_for_column(col if col is not None else -1)
        mol = self._mol_for_render2d_source(row, src)
        if mol is None:
            QMessageBox.information(
                self,
                TOOL_RENDER_2D,
                f"No structure could be read from column “{src}” for this row.",
            )
            return
        if src == "Structure":
            self.mols[oid] = mol
        pixmap_mode = src != "Structure" and self._table_model.is_pixmap_data_column(src)
        base_w, base_h = structure_depict_width(), structure_depict_height()
        renders, row_by_oid = self._build_render2d_tasks_in_table_order(src, base_w, base_h, {oid})
        if not renders:
            QMessageBox.information(
                self,
                TOOL_RENDER_2D,
                f"No structure could be read from column “{src}” for this row.",
            )
            return
        self._start_render_2d_batch(renders, row_by_oid, src, column_pixmap_mode=pixmap_mode)

    def _disconnect_source_text_for_oid(self, oid: int, src: str) -> str | None:
        """Original cell text for the disconnect target column (for multi-component SMILES)."""
        row = self.logical_row_for_oid(oid)
        if row < 0:
            return None
        if src == "Structure":
            raw = (self._table_model.backing_value_for_row_header(row, "Structure") or "").strip()
            if raw:
                return raw
            smiles_h = self._canonical_smiles_header_for_updates()
            if smiles_h is not None:
                return (
                    self._table_cell_text(row, self.headers.index(smiles_h)) or ""
                ).strip() or None
            return None
        if src in self.headers and self._table_model.is_pixmap_data_column(src):
            raw = (self._table_model.backing_value_for_row_header(row, src) or "").strip()
            return raw or None
        col = self.headers.index(src)
        raw = (self._table_cell_text(row, col) or "").strip()
        if not raw:
            raw = (self._table_model.backing_value_for_row_header(row, src) or "").strip()
        return raw or None

    def _ensure_disconnect_output_column(self, header_name: str) -> None:
        """Insert a data column if the disconnect dialog named one that is not present yet."""
        if not header_name or header_name in self.headers:
            return
        if header_name == "Fragments" and "Salt" in self.headers:
            idx_old = self.headers.index("Salt")
            self.headers[idx_old] = "Fragments"
            self._table_model.rename_header_at(idx_old, "Fragments")
            return
        nc = self._table_model.columnCount()
        self.headers.append(header_name)
        self._table_model.insert_column_at(nc, header_name, None)

    def on_disconnect_fragments_finished(self, results):
        self.table.setSortingEnabled(False)
        src = getattr(self, "_disconnect_source", "Structure")
        update_target = getattr(self, "_disconnect_update_target", True)
        largest_col = getattr(self, "_disconnect_largest_col", src)
        fragments_col = getattr(self, "_disconnect_fragments_col", "Fragments")
        no_render_2d = getattr(self, "_disconnect_no_render_2d", False)
        self._disconnect_source = "Structure"
        self._disconnect_update_target = True
        self._disconnect_largest_col = "Structure"
        self._disconnect_fragments_col = "Fragments"
        self._disconnect_no_render_2d = False

        self._ensure_disconnect_output_column(fragments_col)
        if not update_target:
            self._ensure_disconnect_output_column(largest_col)

        update_mols_cache = update_target and src == "Structure"
        if no_render_2d:
            render_largest = False
        elif update_target:
            render_largest = src == "Structure" or (
                src in self.headers and self._table_model.is_pixmap_data_column(src)
            )
        else:
            render_largest = True
            if largest_col in self.headers:
                self._table_model.register_pixmap_column(largest_col)
        smiles_h = self._canonical_smiles_header_for_updates()
        update_smiles_col = (
            update_target
            and smiles_h is not None
            and src == smiles_h
            and not self._table_model.is_pixmap_data_column(smiles_h)
        )
        target_is_text = (
            update_target
            and src in self.headers
            and not self._table_model.is_pixmap_data_column(src)
            and src != "Structure"
        )
        new_largest_is_text = (
            not update_target
            and not render_largest
            and largest_col in self.headers
            and not self._table_model.is_pixmap_data_column(largest_col)
        )

        for oid, mol, fragments in results:
            if update_mols_cache:
                self.mols[oid] = mol
            row = self.logical_row_for_oid(oid)
            if row == -1:
                continue
            if update_target and src == "Structure":
                self._table_model.set_structure_pixmap(oid, None)
            elif render_largest and not update_target and largest_col in self.headers:
                self._table_model.set_column_pixmap(oid, largest_col, None)
            elif target_is_text:
                self._table_model.set_cell_text(oid, src, mol_to_canonical_smiles(mol))
            elif new_largest_is_text:
                self._table_model.set_cell_text(oid, largest_col, mol_to_canonical_smiles(mol))
            if fragments_col in self.headers:
                self._table_model.set_cell_text(oid, fragments_col, fragments)
            if update_smiles_col:
                self._table_model.set_cell_text(oid, smiles_h, mol_to_canonical_smiles(mol))
        self.schedule_calculate_global_bounds()
        self.table.setSortingEnabled(False)
        self._clear_tool_progress()

        render_src = src if update_target else largest_col
        if (
            results
            and render_largest
            and not no_render_2d
            and not getattr(self, "_render2d_batch_active", False)
        ):
            base_w, base_h = structure_depict_width(), structure_depict_height()
            renders = []
            row_by_oid: dict[int, int] = {}
            for oid, mol, _frag in results:
                if mol is None:
                    continue
                row = self.logical_row_for_oid(oid)
                if row < 0:
                    continue
                rw, rh = (
                    (structure_depict_width() * 2, structure_depict_height() * 2)
                    if oid in self.zoomed_ids
                    else (base_w, base_h)
                )
                renders.append((oid, mol, rw, rh))
                row_by_oid[oid] = row
            if renders:
                column_pixmap_mode = render_src != "Structure"
                self._start_render_2d_batch(
                    renders, row_by_oid, render_src, column_pixmap_mode=column_pixmap_mode
                )
                return
        self.status_label.setText(self._consume_partial_results_notice() or "Done.")
