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

"""Mol writeback helpers for structure-prep tools (``WorkspaceTools.structure_prep``)."""

from __future__ import annotations

from ..table.structure_depiction_layout import structure_depict_height, structure_depict_width
from ..chem.molecule_conversion import mol_to_canonical_smiles


class StructureWritebackTools:
    def _write_mol_to_source_column(
        self,
        oid: int,
        mol,
        src: str,
        *,
        smiles_h: str | None,
        update_smiles_col: bool,
    ) -> None:
        """Write one molecule into Structure, a depiction column, or a SMILES column."""
        if src == "Structure":
            self._app.mols[oid] = mol
            self._app._table_model.set_structure_pixmap(oid, None)
        elif src in self._app.headers:
            if self._app._table_model.is_pixmap_data_column(src):
                try:
                    smi = mol_to_canonical_smiles(mol)
                except Exception:
                    smi = ""
                if smi:
                    self._app._table_model.set_backing_text(oid, src, smi)
                self._app._table_model.set_column_pixmap(oid, src, None)
            else:
                self._app._table_model.set_cell_text(oid, src, mol_to_canonical_smiles(mol))
        if update_smiles_col and smiles_h:
            self._app._table_model.set_cell_text(oid, smiles_h, mol_to_canonical_smiles(mol))

    def _start_mol_tool_render2d(self, results, src: str) -> bool:
        """Queue 2D redraws for ``(oid, mol)`` pairs. Return True when a batch started."""
        base_w, base_h = structure_depict_width(), structure_depict_height()
        renders = []
        row_by_oid: dict[int, int] = {}
        for oid, mol in results:
            if mol is None:
                continue
            row = self._app.logical_row_for_oid(oid)
            if row < 0:
                continue
            rw, rh = (
                (structure_depict_width() * 2, structure_depict_height() * 2)
                if oid in self._app.zoomed_ids
                else (base_w, base_h)
            )
            renders.append((oid, mol, rw, rh))
            row_by_oid[oid] = row
        if not renders:
            return False
        self._app._start_render_2d_batch(
            renders, row_by_oid, src, column_pixmap_mode=src != "Structure"
        )
        return True

    def _apply_mol_tool_results(
        self,
        results,
        *,
        src: str,
        no_render_2d: bool,
        done_label: str = "Done.",
    ) -> None:
        """Write mol-tool results into the source column, then optionally render 2D."""
        render_target = src == "Structure" or (
            src in self._app.headers and self._app._table_model.is_pixmap_data_column(src)
        )
        smiles_h = self._app._canonical_smiles_header_for_updates()
        update_smiles_col = smiles_h is not None and src == smiles_h

        for oid, mol in results:
            if mol is None:
                continue
            self._write_mol_to_source_column(
                oid, mol, src, smiles_h=smiles_h, update_smiles_col=update_smiles_col
            )

        self._app.schedule_calculate_global_bounds()
        self._app._clear_tool_progress()
        if (
            results
            and render_target
            and not no_render_2d
            and not getattr(self._app, "_render2d_batch_active", False)
        ):
            if self._start_mol_tool_render2d(results, src):
                return
        self._app.status_label.setText(self._app._consume_partial_results_notice() or done_label)

    def _mol_for_structure_tool_oid(self, oid: int, src: str) -> object | None:
        """Molecule for a prepare-structures tool row and source column."""
        row = self._app.logical_row_for_oid(oid)
        if row < 0:
            return None
        if src == "Structure":
            mol = self._app.mols.get(oid)
            if mol is not None:
                return mol
            return self._app._mol_for_structure_row(row)
        if src not in self._app.headers:
            return None
        col = self._app.headers.index(src)
        raw = ""
        if self._app._table_model.is_pixmap_data_column(src):
            raw = (self._app._table_model.backing_value_for_row_header(row, src) or "").strip()
        else:
            raw = (self._app._table_cell_text(row, col) or "").strip()
            if not raw:
                raw = (self._app._table_model.backing_value_for_row_header(row, src) or "").strip()
        if not raw:
            return None
        return self._app._mol_from_structure_text(raw)

    def _disconnect_source_text_for_oid(self, oid: int, src: str) -> str | None:
        """Original cell text for the disconnect target column (for multi-component SMILES)."""
        row = self._app.logical_row_for_oid(oid)
        if row < 0:
            return None
        if src == "Structure":
            raw = (
                self._app._table_model.backing_value_for_row_header(row, "Structure") or ""
            ).strip()
            if raw:
                return raw
            smiles_h = self._app._canonical_smiles_header_for_updates()
            if smiles_h is not None:
                return (
                    self._app._table_cell_text(row, self._app.headers.index(smiles_h)) or ""
                ).strip() or None
            return None
        if src in self._app.headers and self._app._table_model.is_pixmap_data_column(src):
            raw = (self._app._table_model.backing_value_for_row_header(row, src) or "").strip()
            return raw or None
        col = self._app.headers.index(src)
        raw = (self._app._table_cell_text(row, col) or "").strip()
        if not raw:
            raw = (self._app._table_model.backing_value_for_row_header(row, src) or "").strip()
        return raw or None

    def _ensure_disconnect_output_column(self, header_name: str) -> None:
        """Insert a data column if the disconnect dialog named one that is not present yet."""
        if not header_name or header_name in self._app.headers:
            return
        if header_name == "Fragments" and "Salt" in self._app.headers:
            idx_old = self._app.headers.index("Salt")
            self._app.headers[idx_old] = "Fragments"
            self._app._table_model.rename_header_at(idx_old, "Fragments")
            return
        nc = self._app._table_model.columnCount()
        self._app.headers.append(header_name)
        self._app._table_model.insert_column_at(nc, header_name, None)
