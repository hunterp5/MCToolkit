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


"""Conformer generation, superposition, and packed-ensemble writeback."""

from __future__ import annotations


from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog,
    QMessageBox,
)

from rdkit import Chem

import logging

from ...conformer_output import iter_single_conformer_mols, write_conformer_results_to_sdf
from ...confs_codec import (
    demote_v1_cell_to_sidecar,
    pack_confs_cell,
    rehydrate_v1_confs_cell,
    unpack_confs_blocks_json_b64,
)
from ...services.column_labels import COLUMN_PARENT_OID
from ...utils import mol_to_canonical_smiles
from ...workers import (
    ConformerGenerationWorker,
    SuperposeConformersWorker,
    SuperposeStructuresWorker,
    SystematicConformerWorker,
)

logger = logging.getLogger(__name__)


class ConformersToolsMixin:
    def open_generate_conformations(self):
        if not self.headers or self._table_model.rowCount() == 0:
            QMessageBox.information(
                self,
                "Generate Conformations",
                "Open a file or add rows so the table has molecules to process.",
            )
            return
        from ..dialogs import GenerateConformationsDialog

        d = GenerateConformationsDialog(len(self._selected_logical_rows()), self)
        self._prepare_tool_dialog(d)
        d.setAttribute(Qt.WA_DeleteOnClose, True)
        d.accepted.connect(lambda *_, dlg=d: self._on_generate_conformations_dialog_accepted(dlg))
        d.show()

    def open_systematic_conformations(self):
        if not self.headers or self._table_model.rowCount() == 0:
            QMessageBox.information(
                self,
                "Generate Conformations — Systematic",
                "Open a file or add rows so the table has molecules to process.",
            )
            return
        from ..dialogs import SystematicConformationsDialog

        d = SystematicConformationsDialog(len(self._selected_logical_rows()), self)
        self._prepare_tool_dialog(d)
        d.setAttribute(Qt.WA_DeleteOnClose, True)
        d.accepted.connect(lambda *_, dlg=d: self._on_systematic_conformations_dialog_accepted(dlg))
        d.show()

    def _collect_mols_for_conformer_tools(
        self, *, only_selected: bool
    ) -> list[tuple[int, Chem.Mol]]:
        allowed = self._selected_oids_set() if only_selected else None
        oids_list = self._all_oids_in_table_order()
        if allowed is not None:
            oids_list = [o for o in oids_list if o in allowed]
        data: list[tuple[int, Chem.Mol]] = []
        for o in oids_list:
            r = self.logical_row_for_oid(o)
            m = self.mols.get(o) if r >= 0 else None
            if m is None and r >= 0:
                m = self._mol_for_structure_row(r)
            if m is not None:
                data.append((o, m))
        return data

    def _on_generate_conformations_dialog_accepted(self, d) -> None:
        only_selected = d.only_selected_rows()
        allowed = self._selected_oids_set() if only_selected else None
        if self._abort_if_only_selected_but_empty(only_selected, allowed, "Generate Conformations"):
            return
        data = self._collect_mols_for_conformer_tools(only_selected=only_selected)
        if not data:
            QMessageBox.information(
                self,
                "Generate Conformations",
                "No parseable structures for those rows (in-memory molecules or chemistry in table cells).",
            )
            return
        params = d.params()
        self._conformer_output_options = d.output_options()
        self._pending_conformer_initial_superpose = bool((params.align_pattern or "").strip())
        n = len(data)
        from ...memory_guards import check_conformer_workload

        guard = check_conformer_workload(n, int(getattr(params, "num_confs", 1) or 1))
        if not guard.ok:
            QMessageBox.warning(self, "Generate Conformations", guard.message)
            return
        from ...workers import StrainEnergyParams

        self._pending_strain_params = StrainEnergyParams(
            force_field=str(params.force_field or "MMFF")
        )
        ps = self._tool_progress_state
        self._begin_tool_progress("Generate conformations", n)
        self.process_queue.enqueue(
            f"Generate conformations ({n} structures)",
            lambda ev, d=data, p=params, sigs=self.signals, prog=ps: ConformerGenerationWorker(
                d, p, sigs, cancel_event=ev, progress_state=prog
            ),
        )

    def _on_systematic_conformations_dialog_accepted(self, d) -> None:
        only_selected = d.only_selected_rows()
        allowed = self._selected_oids_set() if only_selected else None
        if self._abort_if_only_selected_but_empty(
            only_selected, allowed, "Generate Conformations — Systematic"
        ):
            return
        data = self._collect_mols_for_conformer_tools(only_selected=only_selected)
        if not data:
            QMessageBox.information(
                self,
                "Generate Conformations — Systematic",
                "No parseable structures for those rows (in-memory molecules or chemistry in table cells).",
            )
            return
        params = d.params()
        from ...openbabel_confab import ensure_openbabel_confab_ready

        missing = ensure_openbabel_confab_ready(params.obabel_path)
        if missing:
            QMessageBox.warning(self, "Generate Conformations — Systematic", missing)
            return
        self._conformer_output_options = d.output_options()
        self._pending_conformer_initial_superpose = False
        n = len(data)
        from ...memory_guards import check_conformer_workload

        guard = check_conformer_workload(n, int(getattr(params, "num_confs", 1) or 1))
        if not guard.ok:
            QMessageBox.warning(self, "Generate Conformations — Systematic", guard.message)
            return
        from ...workers import StrainEnergyParams

        self._pending_strain_params = StrainEnergyParams(force_field="MMFF")
        ps = self._tool_progress_state
        self._begin_tool_progress("Systematic conformations", n)
        self.process_queue.enqueue(
            f"Systematic conformations ({n} structures)",
            lambda ev, d=data, p=params, sigs=self.signals, prog=ps: SystematicConformerWorker(
                d, p, sigs, cancel_event=ev, progress_state=prog
            ),
        )

    def cancel_active_tool_process(self) -> None:
        """Request cooperative cancellation of the process-queue job, Render 2D, and/or Smina."""
        r2d = self.cancel_render_2d_batch()
        smina = self.cancel_smina_dock()
        pq_ok = self.process_queue.cancel_running()
        if pq_ok:
            self.status_label.setText("Cancelling…")
        elif r2d:
            self.status_label.setText("Render 2D cancelled.")
        elif smina:
            self.status_label.setText("Smina stopped.")
        else:
            QMessageBox.information(
                self,
                "Cancel Process",
                "Nothing to cancel (no process-queue job, Render 2D batch, or Smina run), "
                "or cancellation was already requested.",
            )

    def on_conformers_finished(self, results: list) -> None:
        self._finish_tool_progress()
        output_opts = getattr(self, "_conformer_output_options", None)
        self._conformer_output_options = None
        added_rows = 0
        saved_count = 0
        confs_col = "confs"
        self.table.setSortingEnabled(False)
        try:
            self.table.setUpdatesEnabled(False)
        except Exception:
            pass
        try:
            confs_col = self._next_packed_ensemble_column("confs")
            pairs: list[tuple[int, str]] = []
            for item in results:
                if len(item) < 3:
                    continue
                pairs.append((int(item[0]), str(item[2] or "")))
            self._write_packed_ensemble_cells(confs_col, pairs)
            if output_opts is not None and output_opts.add_to_table:
                added_rows = self._append_generated_conformers_as_rows(results)
            if output_opts is not None and output_opts.save_to_file and output_opts.save_path:
                try:
                    saved_count = write_conformer_results_to_sdf(output_opts.save_path, results)
                except OSError as e:
                    QMessageBox.warning(
                        self, "Generate Conformations", f"Could not write SDF file:\n{e}"
                    )
            self.schedule_calculate_global_bounds()
            self.table.setSortingEnabled(False)
        finally:
            try:
                self.table.setUpdatesEnabled(True)
            except Exception:
                pass
        notice = self._consume_partial_results_notice()
        parts = []
        if notice:
            parts.append(notice)
        if confs_col != "confs":
            parts.append(f"Wrote ensembles to “{confs_col}”.")
        if output_opts is not None and output_opts.add_to_table:
            parts.append(f"Added {added_rows} conformer row(s) to the table.")
        if output_opts is not None and output_opts.save_to_file and output_opts.save_path:
            if saved_count:
                parts.append(f"Wrote {saved_count} conformer(s) to {output_opts.save_path}.")
            elif not any(p.startswith("Could not") for p in parts):
                parts.append("No conformers were written to the SDF file.")
        self.status_label.setText(" ".join(parts) if parts else "Done.")
        initial_superpose = bool(getattr(self, "_pending_conformer_initial_superpose", False))
        self._pending_conformer_initial_superpose = False
        n_ok = self._auto_open_first_conformer_results(
            results,
            title="View Conformers",
            confs_column=confs_col,
            initial_superpose=initial_superpose,
        )
        self._pending_strain_params = None
        if n_ok > 1:
            self.status_label.setText(
                (self.status_label.text() + " " if self.status_label.text() else "")
                + f"Opened energy results for the first of {n_ok} ensembles; "
                "use View Conformers on other rows."
            )

    def _append_generated_conformers_as_rows(self, results: list) -> int:
        """Append one table row per generated conformer; keep 3D coordinates in ``self.mols``."""
        records: list[tuple[str, dict[str, str], Chem.Mol]] = []
        for item in results:
            if len(item) < 2:
                continue
            parent_oid, mol = int(item[0]), item[1]
            if mol is None:
                continue
            for conf_i, cm in enumerate(iter_single_conformer_mols(mol)):
                smi = mol_to_canonical_smiles(cm)
                if not smi:
                    continue
                records.append(
                    (
                        smi,
                        {
                            COLUMN_PARENT_OID: str(parent_oid),
                            "Conformer": str(conf_i + 1),
                        },
                        cm,
                    )
                )
        if not records:
            return 0
        field_names: set[str] = set()
        for _smi, fields, _mol in records:
            field_names.update(fields.keys())
        self._ensure_columns(["SMILES"] + sorted(field_names))
        batch_rows: list[tuple[int, dict[str, str]]] = []
        new_mols: list[tuple[int, Chem.Mol]] = []
        for smiles, fields, mol in records:
            oid = self.next_oid
            self.next_oid += 1
            row_cells: dict[str, str] = {}
            for h in self.headers[2:]:
                if h == "SMILES":
                    row_cells[h] = smiles
                else:
                    row_cells[h] = str(fields.get(h, "") or "")
            batch_rows.append((oid, row_cells))
            new_mols.append((oid, mol))
        self._table_model.append_rows_batch(batch_rows)
        for oid, mol in new_mols:
            self.mols[oid] = mol
            self.start_render_worker(oid, mol)
        self._sync_global_bounds_for_headers(sorted(field_names), refresh_filters=False)
        return len(batch_rows)

    def export_conformer_viewer_to_table(
        self,
        *,
        blocks_json_b64: str,
        conf_indices: list[int] | None = None,
        strain_overlay: dict | None = None,
        parent_oid: int | None = None,
        confs_column: str = "confs",
    ) -> int:
        """
        Append viewer conformer(s) as table rows.

        Structure gets a 2D depiction; 3D coordinates are packed into *confs_column*
        (created if missing) so View Conformers works again. When *strain_overlay*
        is present, also writes ``E_kcal``, ``(delta)E_kcal``, and ``RMSD``.
        """
        import base64
        import json

        from ..mol_viewer_3d import prepare_mol_2d

        raw = (blocks_json_b64 or "").strip()
        if not raw:
            return 0
        try:
            blocks = json.loads(base64.b64decode(raw.encode("ascii")))
        except Exception:
            return 0
        if not isinstance(blocks, list) or not blocks:
            return 0

        n_blocks = len(blocks)
        if conf_indices is None:
            indices = list(range(n_blocks))
        else:
            indices = [i for i in conf_indices if isinstance(i, int) and 0 <= i < n_blocks]
        if not indices:
            return 0

        confs_col = (confs_column or "confs").strip() or "confs"
        overlay = strain_overlay if isinstance(strain_overlay, dict) else None
        energies = (overlay or {}).get("energies") if overlay else None
        deltas = (overlay or {}).get("deltas") if overlay else None
        rmsds = (overlay or {}).get("rmsds") if overlay else None
        has_e = isinstance(energies, list) and len(energies) == n_blocks
        has_de = isinstance(deltas, list) and len(deltas) == n_blocks
        has_rms = isinstance(rmsds, list) and len(rmsds) == n_blocks

        ensure_cols = ["SMILES", COLUMN_PARENT_OID, "Conformer", confs_col]
        if has_e:
            ensure_cols.append("E_kcal")
        if has_de:
            ensure_cols.append("(delta)E_kcal")
        if has_rms:
            ensure_cols.append("RMSD")
        self._ensure_columns(ensure_cols)

        sc = getattr(self, "_confs_blocks_sidecar", None)
        if sc is None:
            self._confs_blocks_sidecar = {}
            sc = self._confs_blocks_sidecar

        def _fmt_num(val) -> str:
            try:
                return f"{float(val):.6g}"
            except Exception:
                return ""

        batch_rows: list[tuple[int, dict[str, str]]] = []
        new_mols: list[tuple[int, Chem.Mol]] = []
        confs_pairs: list[tuple[int, str]] = []
        field_names: set[str] = set()

        for conf_i in indices:
            enc = blocks[conf_i]
            if not isinstance(enc, str) or not enc.strip():
                continue
            try:
                mol_block = base64.b64decode(enc.encode("ascii")).decode("utf-8")
            except Exception:
                continue
            mol3d = Chem.MolFromMolBlock(mol_block, sanitize=True, removeHs=False)
            if mol3d is None:
                mol3d = Chem.MolFromMolBlock(mol_block, sanitize=False, removeHs=False)
            if mol3d is None:
                continue
            # Structure column keeps a 2D depiction; packed confs holds the 3D coordinates.
            depict = prepare_mol_2d(mol3d)
            if depict is None:
                depict = Chem.Mol(mol3d)

            smi = mol_to_canonical_smiles(depict) or mol_to_canonical_smiles(mol3d) or ""
            meta = {
                "ok": True,
                "op": "viewer_export",
                "n_kept": 1,
                "n_packed": 1,
            }
            packed = pack_confs_cell(meta, mol3d)
            light, b64 = demote_v1_cell_to_sidecar(packed, confs_col)

            oid = self.next_oid
            self.next_oid += 1
            if b64 is not None:
                sc[(oid, confs_col)] = b64

            row_cells: dict[str, str] = {}
            for h in self.headers[2:]:
                if h == "SMILES":
                    row_cells[h] = smi
                elif h == COLUMN_PARENT_OID:
                    row_cells[h] = "" if parent_oid is None else str(int(parent_oid))
                elif h == "Conformer":
                    row_cells[h] = str(int(conf_i) + 1)
                elif h == confs_col:
                    row_cells[h] = light
                elif h == "E_kcal" and has_e:
                    row_cells[h] = _fmt_num(energies[conf_i])
                elif h == "(delta)E_kcal" and has_de:
                    row_cells[h] = _fmt_num(deltas[conf_i])
                elif h == "RMSD" and has_rms:
                    row_cells[h] = _fmt_num(rmsds[conf_i])
                else:
                    row_cells[h] = ""
            batch_rows.append((oid, row_cells))
            new_mols.append((oid, depict))
            confs_pairs.append((oid, light))
            field_names.update(row_cells.keys())

        if not batch_rows:
            return 0

        self.table.setSortingEnabled(False)
        try:
            self.table.setUpdatesEnabled(False)
        except Exception:
            pass
        try:
            self._table_model.append_rows_batch(batch_rows)
            for oid, mol in new_mols:
                self.mols[oid] = mol
                self.start_render_worker(oid, mol)
            if confs_pairs:
                self._table_model.set_column_text_by_oids(confs_col, confs_pairs)
            self._sync_global_bounds_for_headers(sorted(field_names), refresh_filters=False)
            self.schedule_calculate_global_bounds()
        finally:
            try:
                self.table.setUpdatesEnabled(True)
            except Exception:
                pass
        self.status_label.setText(
            f"Exported {len(batch_rows)} conformer row(s) from the 3D viewer."
        )
        return len(batch_rows)

    def open_superpose(self, default_target: str | None = None):
        if not self.headers or self._table_model.rowCount() == 0:
            QMessageBox.information(
                self,
                "Superpose",
                "Open a file or add rows so the table has data to process.",
            )
            return
        from ..dialogs import SuperposeDialog

        has_confs = "confs" in self.headers
        target = (default_target or "").strip().lower()
        if target not in {"conformers", "structures"}:
            target = "conformers" if has_confs else "structures"
        sources = ["Structure"] + [c for c in ("confs", "superpose") if c in self.headers]
        d = SuperposeDialog(
            len(self._selected_logical_rows()),
            source_columns=sources,
            has_confs=has_confs,
            default_target=target,
            parent=self,
        )
        self._prepare_tool_dialog(d)
        if d.exec_() != QDialog.Accepted:
            return
        if d.target() == "conformers":
            self._run_superpose_conformers(d)
        else:
            self._run_superpose_structures(d)

    def open_superpose_conformers(self):
        self.open_superpose(default_target="conformers")

    def open_superpose_structures(self):
        self.open_superpose(default_target="structures")

    def _run_superpose_conformers(self, d) -> None:
        if "confs" not in self.headers:
            QMessageBox.information(
                self,
                "Superpose",
                'Add a "confs" column first by running Generate Conformations (packed multi-conformer cells).',
            )
            return
        only_selected = d.only_selected_rows()
        allowed = self._selected_oids_set() if only_selected else None
        if self._abort_if_only_selected_but_empty(only_selected, allowed, "Superpose"):
            return
        oids_list = self._all_oids_in_table_order()
        if allowed is not None:
            oids_list = [o for o in oids_list if o in allowed]
        data: list[tuple[int, str]] = []
        for o in oids_list:
            r = self.logical_row_for_oid(o)
            if r < 0:
                continue
            raw = self._table_model.backing_value_for_row_header(r, "confs")
            sc = getattr(self, "_confs_blocks_sidecar", {}) or {}
            full = rehydrate_v1_confs_cell(raw, "confs", int(o), sc)
            if unpack_confs_blocks_json_b64(full) is None:
                continue
            data.append((o, full))
        if not data:
            QMessageBox.information(
                self,
                "Superpose",
                'No rows in scope have a packed multi-conformer "confs" cell. Run Generate Conformations first.',
            )
            return
        params = d.conformer_params()
        from ...workers import StrainEnergyParams

        if str(getattr(params, "geometry", "3d") or "3d").lower().startswith("2"):
            self._pending_strain_params = None
        else:
            self._pending_strain_params = StrainEnergyParams(
                reference_conformer_index=int(params.reference_conformer_index or 0)
            )
        n = len(data)
        ps = self._tool_progress_state
        self._begin_tool_progress("Superpose", n)
        self.process_queue.enqueue(
            f"Superpose ({n} rows)",
            lambda ev, d=data, p=params, sigs=self.signals, prog=ps: SuperposeConformersWorker(
                d, p, sigs, cancel_event=ev, progress_state=prog
            ),
        )

    def on_superpose_finished(self, results: list) -> None:
        self._finish_tool_progress("Superpose")
        superpose_col = "superpose"
        self.table.setSortingEnabled(False)
        try:
            self.table.setUpdatesEnabled(False)
        except Exception:
            pass
        try:
            superpose_col = self._next_packed_ensemble_column("superpose")
            pairs: list[tuple[int, str]] = []
            for item in results:
                if len(item) < 3:
                    continue
                pairs.append((int(item[0]), str(item[2] or "")))
            self._write_packed_ensemble_cells(superpose_col, pairs)
            self.schedule_calculate_global_bounds()
            self.table.setSortingEnabled(False)
        finally:
            try:
                self.table.setUpdatesEnabled(True)
            except Exception:
                pass
        notice = self._consume_partial_results_notice()
        parts = []
        if notice:
            parts.append(notice)
        if superpose_col != "superpose":
            parts.append(f"Wrote overlays to “{superpose_col}”.")
        self.status_label.setText(" ".join(parts) if parts else "Done.")
        n_ok = self._auto_open_first_conformer_results(
            results,
            title="Superpose",
            confs_column=superpose_col,
            initial_superpose=True,
        )
        self._pending_strain_params = None
        if n_ok > 1:
            self.status_label.setText(
                (self.status_label.text() + " " if self.status_label.text() else "")
                + f"Opened energy results for the first of {n_ok} overlays; "
                "use View Conformers on other rows."
            )

    def _mol_3d_for_structure_superpose(self, oid: int, src: str) -> Chem.Mol | None:
        """Best-effort 3D mol for structure superposition from *src* (Structure / confs / …)."""
        from ...confs_codec import mol_from_packed_confs_cell, mol_has_3d_coordinates
        from ..mol_viewer_3d import prepare_mol_3d

        r = self.logical_row_for_oid(oid)
        if r < 0:
            return None
        src_h = (src or "Structure").strip() or "Structure"
        if src_h != "Structure" and src_h in self.headers:
            raw = self._table_model.backing_value_for_row_header(r, src_h)
            sc = getattr(self, "_confs_blocks_sidecar", {}) or {}
            full = rehydrate_v1_confs_cell(raw, src_h, int(oid), sc)
            packed = mol_from_packed_confs_cell(full, min_conformers=1)
            if packed is not None and mol_has_3d_coordinates(packed):
                return packed
        m = self.mols.get(oid)
        if m is None:
            m = self._mol_for_structure_row(r)
        if m is None:
            return None
        if mol_has_3d_coordinates(m):
            return Chem.Mol(m)
        # Prefer packed confs even when source is Structure.
        for col in ("confs", "superpose"):
            if col not in self.headers:
                continue
            raw = self._table_model.backing_value_for_row_header(r, col)
            sc = getattr(self, "_confs_blocks_sidecar", {}) or {}
            full = rehydrate_v1_confs_cell(raw, col, int(oid), sc)
            packed = mol_from_packed_confs_cell(full, min_conformers=1)
            if packed is not None and mol_has_3d_coordinates(packed):
                return packed
        return prepare_mol_3d(m)

    def _mol_for_structure_superpose(
        self, oid: int, src: str, *, geometry: str = "3d"
    ) -> Chem.Mol | None:
        """Molecule for structure superposition; 2D does not require 3D coordinates."""
        geom = str(geometry or "3d").strip().lower()
        if not geom.startswith("2"):
            return self._mol_3d_for_structure_superpose(oid, src)
        from ...confs_codec import mol_from_packed_confs_cell

        r = self.logical_row_for_oid(oid)
        if r < 0:
            return None
        src_h = (src or "Structure").strip() or "Structure"
        if src_h != "Structure" and src_h in self.headers:
            raw = self._table_model.backing_value_for_row_header(r, src_h)
            sc = getattr(self, "_confs_blocks_sidecar", {}) or {}
            full = rehydrate_v1_confs_cell(raw, src_h, int(oid), sc)
            packed = mol_from_packed_confs_cell(full, min_conformers=1)
            if packed is not None:
                return packed
        m = self.mols.get(oid)
        if m is None:
            m = self._mol_for_structure_row(r)
        if m is None:
            return None
        return Chem.Mol(m)

    def _run_superpose_structures(self, d) -> None:
        only_selected = d.only_selected_rows()
        allowed = self._selected_oids_set() if only_selected else None
        if self._abort_if_only_selected_but_empty(only_selected, allowed, "Superpose"):
            return
        oids_list = self._all_oids_in_table_order()
        if allowed is not None:
            oids_list = [o for o in oids_list if o in allowed]
        if len(oids_list) < 2:
            QMessageBox.information(
                self,
                "Superpose",
                "Select at least two rows (Selected Rows Only) to superpose structures.",
            )
            return
        src = d.source_column()
        params = d.structure_params()
        geom = str(getattr(params, "geometry", "3d") or "3d")
        probes: list[tuple[int, Chem.Mol]] = []
        for o in oids_list:
            m = self._mol_for_structure_superpose(int(o), src, geometry=geom)
            if m is None:
                continue
            probes.append((int(o), m))
        if len(probes) < 2:
            need = "2D structures" if str(geom).lower().startswith("2") else "3D structures"
            QMessageBox.information(
                self,
                "Superpose",
                f"Need at least two rows with usable {need} in scope.",
            )
            return
        ref_oid, ref_mol = probes[0]
        n = len(probes)
        ps = self._tool_progress_state
        self._begin_tool_progress("Superpose", n)
        self.process_queue.enqueue(
            f"Superpose ({n} structures)",
            lambda ev, rid=ref_oid, rm=ref_mol, pr=probes, p=params, sigs=self.signals, prog=ps: (
                SuperposeStructuresWorker(
                    rid, rm, pr, p, sigs, cancel_event=ev, progress_state=prog
                )
            ),
        )

    def on_superpose_structures_finished(self, payload) -> None:
        self._finish_tool_progress("Superpose")
        from ...confs_codec import conformer_mol_blocks_b64_json, pack_mols_as_confs_cell

        data = payload if isinstance(payload, dict) else {}
        results = list(data.get("results") or [])
        try:
            ref_oid = int(data.get("ref_oid"))
        except (TypeError, ValueError):
            ref_oid = int(results[0][0]) if results else -1
        geometry = str(data.get("geometry") or "3d")
        self.table.setSortingEnabled(False)
        try:
            self.table.setUpdatesEnabled(False)
        except Exception:
            pass
        ok_n = 0
        viewer_mols: list[Chem.Mol] = []
        superpose_col = "superpose"
        try:
            superpose_col = self._next_packed_ensemble_column("superpose")
            for _oid, mol, meta in results:
                if mol is None or not (meta or {}).get("ok"):
                    continue
                viewer_mols.append(mol)
                ok_n += 1
            if viewer_mols and ref_oid >= 0:
                ensemble_meta = {
                    "ok": True,
                    "op": "superpose_structures",
                    "geometry": geometry,
                    "n_kept": len(viewer_mols),
                    "n_packed": len(viewer_mols),
                    "n_conf": len(viewer_mols),
                    "ref_oid": int(ref_oid),
                }
                cell = pack_mols_as_confs_cell(ensemble_meta, viewer_mols)
                self._write_packed_ensemble_cells(superpose_col, [(int(ref_oid), cell)])
            self.schedule_calculate_global_bounds()
            self.table.setSortingEnabled(False)
        finally:
            try:
                self.table.setUpdatesEnabled(True)
            except Exception:
                pass
        if viewer_mols and ref_oid >= 0:
            import base64
            import json

            blocks: list[str] = []
            for m in viewer_mols:
                try:
                    block = Chem.MolToMolBlock(m)
                    blocks.append(base64.b64encode(block.encode("utf-8")).decode("ascii"))
                except Exception:
                    continue
            skip_strain = str(geometry).lower().startswith("2")
            strain = None if skip_strain else getattr(self, "_pending_strain_params", None)
            if len(blocks) >= 2:
                payload_b64 = base64.b64encode(json.dumps(blocks).encode("utf-8")).decode("ascii")
                self._open_conformer_results_viewer(
                    payload_b64,
                    title="Superpose",
                    confs_column=superpose_col,
                    oid=int(ref_oid),
                    initial_superpose=True,
                    mols=viewer_mols,
                    strain_params=strain,
                )
            elif len(blocks) == 1:
                payload_b64 = conformer_mol_blocks_b64_json(viewer_mols[0])
                self._open_conformer_results_viewer(
                    payload_b64,
                    title="Superpose",
                    confs_column=superpose_col,
                    oid=int(ref_oid),
                    initial_superpose=False,
                    mols=viewer_mols[:1],
                    strain_params=strain,
                )
        failed = len(results) - ok_n
        status = f"Superpose: packed {ok_n} onto reference OID {ref_oid}"
        if failed:
            status += f" ({failed} failed)"
        if superpose_col != "superpose":
            status += f"; wrote overlays to “{superpose_col}”"
        self.status_label.setText(status + ".")

    def _open_conformer_results_viewer(
        self,
        blocks_b64: str,
        *,
        title: str,
        confs_column: str,
        oid: int | None,
        initial_superpose: bool = False,
        mol: Chem.Mol | None = None,
        mols: list[Chem.Mol] | None = None,
        strain_params: object | None = None,
    ) -> None:
        from ...workers import (
            StrainEnergyParams,
            strain_overlay_for_blocks_b64,
            strain_overlay_for_mol,
            strain_overlay_for_mols,
        )
        from ..mol_viewer_3d import open_conformation_viewer_from_blocks_payload

        params = strain_params if strain_params is not None else StrainEnergyParams()
        overlay = None
        try:
            if mols:
                overlay = strain_overlay_for_mols(mols, params)
            elif mol is not None:
                overlay = strain_overlay_for_mol(mol, params)
            else:
                overlay = strain_overlay_for_blocks_b64(blocks_b64, params)
        except Exception:
            logger.debug("strain overlay failed", exc_info=True)
        ref_idx = 0
        if overlay:
            try:
                ref_idx = int(overlay.get("ref_idx", params.reference_conformer_index) or 0)
            except (TypeError, ValueError):
                ref_idx = 0
        open_conformation_viewer_from_blocks_payload(
            self,
            blocks_b64,
            title=title,
            initial_superpose=initial_superpose,
            strain_overlay=overlay,
            initial_conf_index=ref_idx,
            export_parent_oid=oid,
            export_confs_column=confs_column,
            source_oid=oid,
        )

    def open_packed_conformer_viewer(
        self,
        blocks_json_b64: str,
        *,
        title: str = "View Conformers",
        export_parent_oid: int | None = None,
        export_confs_column: str = "confs",
        source_oid: int | None = None,
        initial_superpose: bool = False,
    ) -> None:
        oid = source_oid if source_oid is not None else export_parent_oid
        self._open_conformer_results_viewer(
            blocks_json_b64,
            title=title,
            confs_column=export_confs_column,
            oid=oid,
            initial_superpose=initial_superpose,
        )

    def _auto_open_first_conformer_results(
        self,
        results: list,
        *,
        title: str,
        confs_column: str,
        initial_superpose: bool,
    ) -> int:
        from ...confs_codec import conformer_mol_blocks_b64_json, unpack_confs_blocks_json_b64

        n_ok = 0
        opened = False
        for item in results:
            if len(item) < 3:
                continue
            oid, mol, cell = int(item[0]), item[1], str(item[2] or "")
            b64 = unpack_confs_blocks_json_b64(cell)
            if not b64 and mol is not None:
                try:
                    if mol.GetNumConformers() >= 1:
                        b64 = conformer_mol_blocks_b64_json(mol)
                except Exception:
                    b64 = None
            if not b64:
                continue
            n_ok += 1
            if opened:
                continue
            self._open_conformer_results_viewer(
                b64,
                title=title,
                confs_column=confs_column,
                oid=oid,
                initial_superpose=initial_superpose,
                mol=mol if isinstance(mol, Chem.Mol) else None,
                strain_params=getattr(self, "_pending_strain_params", None),
            )
            opened = True
        return n_ok

    def _next_packed_ensemble_column(self, base: str) -> str:
        """Return a unique packed-ensemble header, inserting it when it is not already in the table."""
        col = self._unique_table_column_names([base])[0]
        if col not in self.headers:
            col_at = len(self.headers)
            self.headers.append(col)
            self._table_model.insert_column_at(col_at, col, None)
        return col

    def _write_packed_ensemble_cells(self, column: str, pairs: list[tuple[int, str]]) -> None:
        """Store packed ensembles under *column*, demoting payloads into the sidecar keyed by that header."""
        sc = getattr(self, "_confs_blocks_sidecar", None)
        if sc is None:
            self._confs_blocks_sidecar = {}
            sc = self._confs_blocks_sidecar
        out: list[tuple[int, str]] = []
        for oid, cell in pairs:
            light, b64 = demote_v1_cell_to_sidecar(str(cell or ""), column)
            if b64 is not None:
                sc[(int(oid), column)] = b64
            out.append((int(oid), light))
        if out:
            self._table_model.set_column_text_by_oids(column, out)
