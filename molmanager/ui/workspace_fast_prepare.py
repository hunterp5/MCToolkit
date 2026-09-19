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

"""Fast Prepare adapter bound on ``WorkspaceTools.structure_prep`` (not a window base)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox

from ..platform_support.config import load_config
from ..table.structure_depiction_layout import structure_depict_height, structure_depict_width
from ..chem.molecule_conversion import mol_from_binary_blob


class FastPrepareTools:
    def run_fast_prepare(self) -> None:
        if not self._app.headers or not self._app.mols:
            return
        from .dialogs import FastPrepareDialog

        candidates = self._app.chemistry_tool_structure_sources()
        n_sel = len(self._app._selected_logical_rows())
        dlg = FastPrepareDialog(candidates, self._app.headers, n_sel, self._app)
        self._app._prepare_tool_dialog(dlg)
        dlg.setAttribute(Qt.WA_DeleteOnClose, True)
        dlg.accepted.connect(lambda *_, d=dlg: self._on_fast_prepare_dialog_accepted(d))
        dlg.show()

    def _on_fast_prepare_dialog_accepted(self, dlg) -> None:
        cfg = dlg.config()
        allowed = self._app._selected_oids_set() if cfg.only_selected else None
        if self._app._abort_if_only_selected_but_empty(cfg.only_selected, allowed, "Fast Prepare"):
            return
        prepare_col = cfg.source_column if cfg.update_target else cfg.largest_column
        self._app._fast_prepare_source = prepare_col
        self._app._fast_prepare_allowed_oids = allowed
        self._app._fast_prepare_fragments_col = cfg.fragments_column
        self._app._fast_prepare_update_target = cfg.update_target
        self._enqueue_fast_prepare(
            cfg.source_column,
            prepare_col,
            only_selected=cfg.only_selected,
            neutralize=cfg.neutralize,
        )

    def _fast_prepare_target_is_text(self, prepare_col: str) -> bool:
        """True when the Fast Prepare output column holds SMILES text rather than a depiction.

        A column the dialog named but that does not exist yet (New Column mode) counts as text: it
        is created as a plain data column before the results are written.
        """
        if prepare_col == "Structure":
            return False
        return not (
            prepare_col in self._app.headers
            and self._app._table_model.is_pixmap_data_column(prepare_col)
        )

    def _enqueue_fast_prepare(
        self, src: str, prepare_col: str, *, only_selected: bool, neutralize: bool = False
    ) -> None:
        """Queue the fused disconnect (and optional neutralize) pass over the rows in scope."""
        from ..workers.fast_prepare import FastPrepareParams, FastPrepareWorker

        allowed = self._app._selected_oids_set() if only_selected else None
        oids_walk = self._app._all_oids_in_table_order()
        if allowed is not None:
            oids_walk = [o for o in oids_walk if o in allowed]

        # Same source split the disconnect job used: the Structure column reads cached mols, any
        # other column is read as cell text.
        is_smiles = src != "Structure"
        data: list[tuple] = []
        if is_smiles:
            col = self._app.headers.index(src)
            for oid in oids_walk:
                row = self._app.logical_row_for_oid(oid)
                if row == -1:
                    continue
                data.append((oid, self._app._table_cell_text(row, col)))
        else:
            for oid in oids_walk:
                mol = self._app.mols.get(oid)
                if mol is None:
                    continue
                data.append((oid, mol, self._disconnect_source_text_for_oid(oid, src)))

        if not data:
            QMessageBox.information(
                self._app,
                "Fast Prepare",
                "No rows match the current scope and structure field.",
            )
            self._app.status_label.setText("Ready.")
            return

        # Canonical SMILES is only needed when the output column stores text; computing it in the
        # child processes keeps MolToSmiles off the GUI thread.
        need_smiles = self._fast_prepare_target_is_text(prepare_col)
        cfg = load_config()
        params = FastPrepareParams(
            is_smiles=is_smiles,
            need_smiles=need_smiles,
            neutralize=bool(neutralize),
            batch_size=int(cfg.fast_prepare_batch_size),
            process_pool_min_rows=int(cfg.fast_prepare_process_pool_min_rows),
        )
        self._app._begin_tool_progress("Fast prepare", len(data))
        self._app.process_queue.enqueue(
            "Fast prepare: prepare structures",
            lambda ev, d=data, p=params, s=self._app.signals, ps=self._app._tool_progress_state: (
                FastPrepareWorker(d, p, s, cancel_event=ev, progress_state=ps)
            ),
        )

    def on_fast_prepare_finished(self, results) -> None:
        """Apply fused disconnect + neutralize results, then render the new depictions.

        One writeback per row: the old two-job chain wrote the disconnected parent and then
        immediately overwrote it with the neutralized molecule.
        """
        self._app.table.setSortingEnabled(False)
        prepare_col = getattr(self._app, "_fast_prepare_source", "Structure")
        fragments_col = getattr(self._app, "_fast_prepare_fragments_col", "Fragments")
        update_target = getattr(self._app, "_fast_prepare_update_target", True)
        allowed_oids = getattr(self._app, "_fast_prepare_allowed_oids", None)
        self._app._fast_prepare_source = "Structure"
        self._app._fast_prepare_allowed_oids = None
        self._app._fast_prepare_fragments_col = "Fragments"
        self._app._fast_prepare_update_target = True

        self._ensure_disconnect_output_column(fragments_col)
        if not update_target:
            self._ensure_disconnect_output_column(prepare_col)

        target_is_text = self._fast_prepare_target_is_text(prepare_col)
        write_fragments = fragments_col in self._app.headers
        smiles_h = self._app._canonical_smiles_header_for_updates()
        sync_smiles_col = smiles_h is not None and smiles_h == prepare_col and target_is_text

        for oid, blob, fragments, smiles in results:
            mol = self._fast_prepare_mol_from_blob(blob)
            if mol is None:
                continue
            if target_is_text:
                self._app._table_model.set_cell_text(oid, prepare_col, smiles)
                if sync_smiles_col:
                    self._app._table_model.set_cell_text(oid, smiles_h, smiles)
            else:
                self._app.mols[oid] = mol
                if prepare_col == "Structure":
                    self._app._table_model.set_structure_pixmap(oid, None)
                else:
                    self._app._table_model.set_column_pixmap(oid, prepare_col, None)
            if write_fragments:
                self._app._table_model.set_cell_text(oid, fragments_col, fragments)

        self._app.schedule_calculate_global_bounds()
        self._app._clear_tool_progress()

        if results and not getattr(self._app, "_render2d_batch_active", False):
            renders, row_by_oid = self._app._build_render2d_tasks_in_table_order(
                prepare_col, structure_depict_width(), structure_depict_height(), allowed_oids
            )
            if renders:
                self._app.status_label.setText("Fast prepare: rendering 2D…")
                self._app._start_render_2d_batch(
                    renders,
                    row_by_oid,
                    prepare_col,
                    column_pixmap_mode=(prepare_col != "Structure"),
                    queue_title_prefix="Fast prepare: ",
                )
                return
        self._app.status_label.setText(
            self._app._consume_partial_results_notice() or "Fast prepare done."
        )

    @staticmethod
    def _fast_prepare_mol_from_blob(blob) -> object | None:
        """Rebuild a molecule from the worker's binary payload."""
        return mol_from_binary_blob(blob)  # type: ignore[return-value]
