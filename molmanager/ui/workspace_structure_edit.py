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

"""Disconnect / neutralize / explicit-H adapters on ``WorkspaceTools.structure_prep``."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox

from ..chem.molecule_conversion import mol_to_canonical_smiles
from ..workers import DisconnectFragmentsWorker


class StructureEditTools:
    def run_disconnect_fragments(self) -> None:
        if not self._app.headers or not self._app.mols:
            return
        candidates = self._app.chemistry_tool_structure_sources()
        from .dialogs import DisconnectFragmentsDialog

        n_sel = len(self._app._selected_logical_rows())
        dlg = DisconnectFragmentsDialog(candidates, self._app.headers, n_sel, self._app)
        self._app._prepare_tool_dialog(dlg)
        dlg.setAttribute(Qt.WA_DeleteOnClose, True)
        dlg.accepted.connect(lambda *_, d=dlg: self._on_disconnect_fragments_dialog_accepted(d))
        dlg.show()

    def _on_disconnect_fragments_dialog_accepted(self, dlg) -> None:
        src, update_target, largest_col, fragments_col, only_selected, no_render_2d = dlg.config()
        allowed = self._app._selected_oids_set() if only_selected else None
        if self._app._abort_if_only_selected_but_empty(
            only_selected, allowed, "Disconnect Largest Fragments"
        ):
            return
        self._app.status_label.setText("Disconnecting fragments…")
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
        allowed = self._app._selected_oids_set() if only_selected else None
        self._app._disconnect_source = src
        self._app._disconnect_update_target = update_target
        self._app._disconnect_largest_col = src if update_target else largest_col
        self._app._disconnect_fragments_col = fragments_col
        self._app._disconnect_no_render_2d = no_render_2d
        if src == "Structure":
            data = []
            oids_walk = self._app._all_oids_in_table_order()
            if allowed is not None:
                oids_walk = [o for o in oids_walk if o in allowed]
            for oid in oids_walk:
                mol = self._app.mols.get(oid)
                if mol is None:
                    continue
                raw = self._disconnect_source_text_for_oid(oid, src)
                data.append((oid, mol, raw))
            if not data:
                QMessageBox.information(
                    self._app,
                    "Disconnect Largest Fragments",
                    "No rows match the current scope and structure field.",
                )
                self._app.status_label.setText("Ready.")
                return
            title = f"{queue_title_prefix}disconnect largest fragments"
            self._app._begin_tool_progress("Disconnect fragments", len(data))
            self._app.process_queue.enqueue(
                title,
                lambda ev, d=data, s=self._app.signals, ps=self._app._tool_progress_state: (
                    DisconnectFragmentsWorker(
                        d, s, is_smiles=False, cancel_event=ev, progress_state=ps
                    )
                ),
            )
        else:
            col = self._app.headers.index(src)
            data = []
            oids_walk = self._app._all_oids_in_table_order()
            if allowed is not None:
                oids_walk = [o for o in oids_walk if o in allowed]
            for oid in oids_walk:
                r = self._app.logical_row_for_oid(oid)
                if r == -1:
                    continue
                data.append((oid, self._app._table_cell_text(r, col)))
            if not data:
                QMessageBox.information(
                    self._app,
                    "Disconnect Largest Fragments",
                    "No rows match the current scope and structure field.",
                )
                self._app.status_label.setText("Ready.")
                return
            title = f"{queue_title_prefix}disconnect largest fragments (column)"
            self._app._begin_tool_progress("Disconnect fragments", len(data))
            self._app.process_queue.enqueue(
                title,
                lambda ev, d=data, s=self._app.signals, ps=self._app._tool_progress_state: (
                    DisconnectFragmentsWorker(
                        d, s, is_smiles=True, cancel_event=ev, progress_state=ps
                    )
                ),
            )

    def run_add_explicit_hydrogens(self) -> None:
        if not self._app.headers or not self._app.mols:
            return
        from .dialogs import AddExplicitHydrogensDialog

        candidates = self._app.chemistry_tool_structure_sources()
        n_sel = len(self._app._selected_logical_rows())
        dlg = AddExplicitHydrogensDialog(candidates, n_sel, self._app)
        self._app._prepare_tool_dialog(dlg)
        dlg.setAttribute(Qt.WA_DeleteOnClose, True)
        dlg.accepted.connect(lambda *_, d=dlg: self._on_add_explicit_hydrogens_dialog_accepted(d))
        dlg.show()

    def _on_add_explicit_hydrogens_dialog_accepted(self, dlg) -> None:
        src, only_selected, no_render_2d = dlg.config()
        allowed = self._app._selected_oids_set() if only_selected else None
        if self._app._abort_if_only_selected_but_empty(
            only_selected, allowed, "Add Explicit Hydrogens"
        ):
            return
        self._app.status_label.setText("Adding explicit hydrogens…")
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
        from ..workers import AddExplicitHydrogensWorker

        self._app._add_explicit_hydrogens_source = src
        self._app._add_explicit_hydrogens_no_render_2d = no_render_2d
        allowed = self._app._selected_oids_set() if only_selected else None
        data: list[tuple[int, object]] = []
        oids_walk = self._app._all_oids_in_table_order()
        if allowed is not None:
            oids_walk = [o for o in oids_walk if o in allowed]
        for oid in oids_walk:
            mol = self._mol_for_structure_tool_oid(oid, src)
            if mol is not None:
                data.append((oid, mol))
        if not data:
            QMessageBox.information(
                self._app,
                "Add Explicit Hydrogens",
                "No rows match the current scope and structure field.",
            )
            self._app.status_label.setText("Ready.")
            return
        self._app._begin_tool_progress("Add explicit hydrogens", len(data))
        self._app.process_queue.enqueue(
            "Add explicit hydrogens",
            lambda ev, d=data, s=self._app.signals, ps=self._app._tool_progress_state: (
                AddExplicitHydrogensWorker(
                    d, s, is_smiles=False, cancel_event=ev, progress_state=ps
                )
            ),
        )

    def run_remove_explicit_hydrogens(self) -> None:
        if not self._app.headers or not self._app.mols:
            return
        from .dialogs import RemoveExplicitHydrogensDialog

        candidates = self._app.chemistry_tool_structure_sources()
        n_sel = len(self._app._selected_logical_rows())
        dlg = RemoveExplicitHydrogensDialog(candidates, n_sel, self._app)
        self._app._prepare_tool_dialog(dlg)
        dlg.setAttribute(Qt.WA_DeleteOnClose, True)
        dlg.accepted.connect(
            lambda *_, d=dlg: self._on_remove_explicit_hydrogens_dialog_accepted(d)
        )
        dlg.show()

    def _on_remove_explicit_hydrogens_dialog_accepted(self, dlg) -> None:
        src, only_selected, no_render_2d = dlg.config()
        allowed = self._app._selected_oids_set() if only_selected else None
        if self._app._abort_if_only_selected_but_empty(
            only_selected, allowed, "Remove Explicit Hydrogens"
        ):
            return
        self._app.status_label.setText("Removing explicit hydrogens…")
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
        from ..workers import RemoveExplicitHydrogensWorker

        self._app._remove_explicit_hydrogens_source = src
        self._app._remove_explicit_hydrogens_no_render_2d = no_render_2d
        allowed = self._app._selected_oids_set() if only_selected else None
        data: list[tuple[int, object]] = []
        oids_walk = self._app._all_oids_in_table_order()
        if allowed is not None:
            oids_walk = [o for o in oids_walk if o in allowed]
        for oid in oids_walk:
            mol = self._mol_for_structure_tool_oid(oid, src)
            if mol is not None:
                data.append((oid, mol))
        if not data:
            QMessageBox.information(
                self._app,
                "Remove Explicit Hydrogens",
                "No rows match the current scope and structure field.",
            )
            self._app.status_label.setText("Ready.")
            return
        self._app._begin_tool_progress("Remove explicit hydrogens", len(data))
        self._app.process_queue.enqueue(
            "Remove explicit hydrogens",
            lambda ev, d=data, s=self._app.signals, ps=self._app._tool_progress_state: (
                RemoveExplicitHydrogensWorker(
                    d, s, is_smiles=False, cancel_event=ev, progress_state=ps
                )
            ),
        )

    def run_neutralize(self) -> None:
        if not self._app.headers or not self._app.mols:
            return
        from .dialogs import NeutralizeDialog

        candidates = self._app.chemistry_tool_structure_sources()
        n_sel = len(self._app._selected_logical_rows())
        dlg = NeutralizeDialog(candidates, n_sel, self._app)
        self._app._prepare_tool_dialog(dlg)
        dlg.setAttribute(Qt.WA_DeleteOnClose, True)
        dlg.accepted.connect(lambda *_, d=dlg: self._on_neutralize_dialog_accepted(d))
        dlg.show()

    def _on_neutralize_dialog_accepted(self, dlg) -> None:
        src, only_selected, no_render_2d = dlg.config()
        allowed = self._app._selected_oids_set() if only_selected else None
        if self._app._abort_if_only_selected_but_empty(only_selected, allowed, "Neutralize"):
            return
        self._app.status_label.setText("Neutralizing structures…")
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
        rows: list[tuple[int, object]] | None = None,
        queue_title_prefix: str = "",
    ) -> None:
        from ..workers import NeutralizeWorker

        self._app._neutralize_source = src
        self._app._neutralize_no_render_2d = no_render_2d
        if rows is None:
            allowed = self._app._selected_oids_set() if only_selected else None
            data: list[tuple[int, object]] = []
            oids_walk = self._app._all_oids_in_table_order()
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
                self._app,
                "Neutralize",
                "No rows match the current scope and structure field.",
            )
            self._app.status_label.setText("Ready.")
            return
        title = f"{queue_title_prefix}neutralize".strip() or "Neutralize"
        self._app._begin_tool_progress("Neutralize", len(data))
        self._app.process_queue.enqueue(
            title,
            lambda ev, d=data, s=self._app.signals, ps=self._app._tool_progress_state: (
                NeutralizeWorker(d, s, is_smiles=False, cancel_event=ev, progress_state=ps)
            ),
        )

    def on_disconnect_fragments_finished(self, results):
        self._app.table.setSortingEnabled(False)
        src = getattr(self._app, "_disconnect_source", "Structure")
        update_target = getattr(self._app, "_disconnect_update_target", True)
        largest_col = getattr(self._app, "_disconnect_largest_col", src)
        fragments_col = getattr(self._app, "_disconnect_fragments_col", "Fragments")
        no_render_2d = getattr(self._app, "_disconnect_no_render_2d", False)
        self._app._disconnect_source = "Structure"
        self._app._disconnect_update_target = True
        self._app._disconnect_largest_col = "Structure"
        self._app._disconnect_fragments_col = "Fragments"
        self._app._disconnect_no_render_2d = False

        self._ensure_disconnect_output_column(fragments_col)
        if not update_target:
            self._ensure_disconnect_output_column(largest_col)

        update_mols_cache = update_target and src == "Structure"
        if no_render_2d:
            render_largest = False
        elif update_target:
            render_largest = src == "Structure" or (
                src in self._app.headers and self._app._table_model.is_pixmap_data_column(src)
            )
        else:
            render_largest = True
            if largest_col in self._app.headers:
                self._app._table_model.register_pixmap_column(largest_col)
        smiles_h = self._app._canonical_smiles_header_for_updates()
        update_smiles_col = (
            update_target
            and smiles_h is not None
            and src == smiles_h
            and not self._app._table_model.is_pixmap_data_column(smiles_h)
        )
        target_is_text = (
            update_target
            and src in self._app.headers
            and not self._app._table_model.is_pixmap_data_column(src)
            and src != "Structure"
        )
        new_largest_is_text = (
            not update_target
            and not render_largest
            and largest_col in self._app.headers
            and not self._app._table_model.is_pixmap_data_column(largest_col)
        )

        for oid, mol, fragments in results:
            if update_mols_cache:
                self._app.mols[oid] = mol
            row = self._app.logical_row_for_oid(oid)
            if row == -1:
                continue
            if update_target and src == "Structure":
                self._app._table_model.set_structure_pixmap(oid, None)
            elif render_largest and not update_target and largest_col in self._app.headers:
                self._app._table_model.set_column_pixmap(oid, largest_col, None)
            elif target_is_text:
                self._app._table_model.set_cell_text(oid, src, mol_to_canonical_smiles(mol))
            elif new_largest_is_text:
                self._app._table_model.set_cell_text(oid, largest_col, mol_to_canonical_smiles(mol))
            if fragments_col in self._app.headers:
                self._app._table_model.set_cell_text(oid, fragments_col, fragments)
            if update_smiles_col:
                self._app._table_model.set_cell_text(oid, smiles_h, mol_to_canonical_smiles(mol))
        self._app.schedule_calculate_global_bounds()
        self._app.table.setSortingEnabled(False)
        self._app._clear_tool_progress()

        render_src = src if update_target else largest_col
        if (
            results
            and render_largest
            and not no_render_2d
            and not getattr(self._app, "_render2d_batch_active", False)
        ):
            mol_results = [(oid, mol) for oid, mol, _frag in results]
            if self._start_mol_tool_render2d(mol_results, render_src):
                return
        self._app.status_label.setText(self._app._consume_partial_results_notice() or "Done.")

    def on_neutralize_finished(self, results) -> None:
        src = getattr(self._app, "_neutralize_source", "Structure")
        no_render_2d = getattr(self._app, "_neutralize_no_render_2d", False)
        self._app._neutralize_source = "Structure"
        self._app._neutralize_no_render_2d = False
        self._apply_mol_tool_results(results, src=src, no_render_2d=no_render_2d)

    def on_add_explicit_hydrogens_finished(self, results) -> None:
        src = getattr(self._app, "_add_explicit_hydrogens_source", "Structure")
        no_render_2d = getattr(self._app, "_add_explicit_hydrogens_no_render_2d", False)
        self._app._add_explicit_hydrogens_source = "Structure"
        self._app._add_explicit_hydrogens_no_render_2d = False
        self._apply_mol_tool_results(results, src=src, no_render_2d=no_render_2d)

    def on_remove_explicit_hydrogens_finished(self, results) -> None:
        src = getattr(self._app, "_remove_explicit_hydrogens_source", "Structure")
        no_render_2d = getattr(self._app, "_remove_explicit_hydrogens_no_render_2d", False)
        self._app._remove_explicit_hydrogens_source = "Structure"
        self._app._remove_explicit_hydrogens_no_render_2d = False
        self._apply_mol_tool_results(results, src=src, no_render_2d=no_render_2d)
