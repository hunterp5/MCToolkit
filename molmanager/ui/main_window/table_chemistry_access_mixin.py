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

"""Chemistry column / molecule lookup helpers for the main table."""

from __future__ import annotations

from rdkit import Chem

from ...chem.structure_source_headers import (
    header_looks_like_structure_text,
    is_tool_generated_structure_header,
)
from ...services.chemistry_columns import (
    canonical_smiles_header_for_updates,
    cell_texts_have_parseable_molecule,
    data_headers_confirmed_for_chemistry_tools,
    is_smiles_named_header,
    ordered_headers_for_molecule_lookup,
    skip_chemistry_tool_column_dropdown,
    should_skip_chemical_scan_column,
)
from ...services.table_scope import collect_scoped_pairs, resolve_structure_row_for_oid
from ...chem.molecule_conversion import (
    looks_like_mol_block,
    mol_to_canonical_smiles,
    parse_molecule_from_cell_text,
    row_cells_from_mol,
    safe_mol_prop_string,
)
from ..compound_table_model import CompoundTableModel


class TableChemistryAccessMixin:
    """Resolve molecules from table cells and chemistry-tool source columns."""

    @staticmethod
    def _header_looks_structural(name: str) -> bool:
        return header_looks_like_structure_text(name)

    def _skip_chemistry_tool_column_dropdown(self, h: str) -> bool:
        """Exclude non-molecular columns from chemistry-tool source dropdowns."""
        return skip_chemistry_tool_column_dropdown(h)

    def _column_has_parseable_molecule_sample(
        self,
        header_name: str,
        *,
        max_rows_scan: int = 500,
        max_nonempty_samples: int = 80,
    ) -> bool:
        """True if a sample of cells in this column parses as a molecule (SMILES, InChI, MolBlock, SMARTS, …)."""
        if header_name not in self.headers:
            return False

        def _iter_texts():
            n = min(self._table_model.rowCount(), max_rows_scan)
            for r in range(n):
                raw = self._table_model.backing_value_for_row_header(r, header_name)
                if not raw:
                    try:
                        ci = self.headers.index(header_name)
                    except ValueError:
                        continue
                    raw = (self._table_cell_text(r, ci) or "").strip()
                yield raw

        return cell_texts_have_parseable_molecule(
            _iter_texts(),
            max_nonempty_samples=max_nonempty_samples,
        )

    def _data_headers_confirmed_for_chemistry_tools(self) -> list[str]:
        """
        Data columns suitable as chemistry-tool sources: structural-looking names,
        optional ``_structure_field_override``, or at least one parseable cell in a bounded scan.
        """
        ov = getattr(self, "_structure_field_override", None)
        return data_headers_confirmed_for_chemistry_tools(
            self.headers,
            structure_field_override=ov if isinstance(ov, str) else None,
            column_has_parseable_sample=self._column_has_parseable_molecule_sample,
        )

    def _should_skip_chemical_scan_column(self, h: str) -> bool:
        return should_skip_chemical_scan_column(
            h,
            is_pixmap_column=self._table_model.is_pixmap_data_column,
        )

    def _ordered_headers_for_molecule_lookup(self) -> list[str]:
        """Column names to probe for parseable chemistry (likely names first, then all other data columns)."""
        ov = getattr(self, "_structure_field_override", None)
        return ordered_headers_for_molecule_lookup(
            self.headers,
            structure_field_override=ov if isinstance(ov, str) else None,
            is_pixmap_column=self._table_model.is_pixmap_data_column,
        )

    def _canonical_smiles_header_for_updates(self) -> str | None:
        """Column to store canonical SMILES after chemistry tools (prefer ``SMILES``)."""
        return canonical_smiles_header_for_updates(self.headers)

    def _is_smiles_named_header(self, h: str) -> bool:
        return is_smiles_named_header(h)

    def _fill_row_data_columns_from_mol(self, row_idx: int, mol: Chem.Mol | None) -> None:
        """Populate data columns (from col 2 onward) from RDKit mol properties — same source as RenderWorker props."""
        if not self.headers or row_idx < 0 or row_idx >= self._table_model.rowCount():
            return
        oid = self._table_model.row_oid(row_idx)
        values = self._row_cells_from_mol(mol)
        self._table_model.set_cell_text_batch(oid, values)

    def _row_cells_from_mol(self, mol: Chem.Mol | None) -> dict[str, str]:
        """Build row cell values for all data columns from one molecule."""
        return row_cells_from_mol(mol, self.headers[2:])

    def _mol_for_structure_row(self, row: int) -> Chem.Mol | None:
        """Best-effort RDKit mol: in-memory store, then any parseable chemistry in table columns."""
        if row < 0 or row >= self._table_model.rowCount():
            return None
        t0 = self._table_model.cell_text(row, 0)
        oid = int(t0) if t0.isdigit() else None
        if oid is not None:
            m = self.mols.get(oid)
            if m is not None:
                return self._apply_structure_field_override(m)
        ov = getattr(self, "_structure_field_override", None)
        ov_s = str(ov).strip() if isinstance(ov, str) else ""
        for h in self._ordered_headers_for_molecule_lookup():
            if is_tool_generated_structure_header(h) and h != ov_s:
                continue
            ci = self.headers.index(h)
            raw = (self._table_model.cell_text(row, ci) or "").strip()
            if not raw:
                raw = (self._table_model.backing_value_for_row_header(row, h) or "").strip()
            if not raw:
                continue
            priority = (
                (ov_s and h == ov_s)
                or self._is_smiles_named_header(h)
                or self._header_looks_structural(h)
            )
            if not priority and len(raw) > 20000 and not looks_like_mol_block(raw):
                continue
            m = self._mol_from_structure_text(raw)
            if m is not None:
                return self._apply_structure_field_override(m)
        return None

    def _column_eligible_for_table_chemistry_menu(self, row: int, col: int) -> bool:
        """Whether the table cell's column should offer structure tools / Copy formats."""
        if col == CompoundTableModel.STRUCTURE_COL:
            return True
        if col <= 0 or col >= len(self.headers):
            return False
        h = self.headers[col]
        from ...predictions.som_prediction import is_som_map_header

        if is_som_map_header(h):
            return False
        if self._skip_chemistry_tool_column_dropdown(h):
            return False
        if self._header_looks_structural(h) or self._is_smiles_named_header(h):
            return True
        raw = self._structure_text_for_table_cell(row, col)
        if not raw or (len(raw) > 20000 and not looks_like_mol_block(raw)):
            return False
        return parse_molecule_from_cell_text(raw) is not None

    def _column_accepts_cell_paste(self, row: int, col: int) -> bool:
        """Whether Paste is allowed on this cell (text data, Structure, or pixmap chemistry)."""
        if col == CompoundTableModel.STRUCTURE_COL:
            return True
        if self._table_model.column_accepts_text_edit(col):
            return True
        if 0 <= col < len(self.headers) and self._table_model.is_pixmap_data_column(
            self.headers[col]
        ):
            return self._column_eligible_for_table_chemistry_menu(row, col)
        return False

    def _structure_text_for_table_cell(self, row: int, col: int) -> str:
        """Stored SMILES/molblock for a cell, including pixmap-only structure columns."""
        if col == CompoundTableModel.STRUCTURE_COL or col <= 0 or col >= len(self.headers):
            return ""
        h = self.headers[col]
        raw = (self._table_model.backing_value_for_row_header(row, h) or "").strip()
        if raw:
            return raw
        return (self._table_model.cell_text(row, col) or "").strip()

    def _mol_for_table_context_menu(self, row: int, col: int) -> Chem.Mol | None:
        """Molecule for context-menu actions from the clicked column (not a different field)."""
        if not self._column_eligible_for_table_chemistry_menu(row, col):
            return None
        if col == CompoundTableModel.STRUCTURE_COL:
            return self._mol_for_structure_row(row)
        raw = self._structure_text_for_table_cell(row, col)
        if not raw or (len(raw) > 20000 and not looks_like_mol_block(raw)):
            return None
        m = self._mol_from_structure_text(raw)
        return self._apply_structure_field_override(m) if m is not None else None

    def _mol_from_structure_text(self, raw: str) -> Chem.Mol | None:
        return parse_molecule_from_cell_text(raw)

    def chemistry_tool_structure_sources(self) -> list[str]:
        """Candidate values for a tool dialog's structure-source dropdown."""
        return ["Structure"] + self._data_headers_confirmed_for_chemistry_tools()

    def collect_scoped_table_mols(
        self,
        src: str,
        *,
        only_selected: bool = False,
        only_visible: bool = False,
    ) -> list[tuple[int, Chem.Mol]]:
        """
        Iterate the table and return ``(oid, mol)`` pairs in scope for a chemistry tool.

        ``src`` is ``"Structure"`` (use the row's structure column / cached mol) or a
        data-column header name (parse that column's cell or pixmap backing SMILES).
        Data-column parses are not written into ``self.mols``. Used by the pKa, protomer,
        cluster, and dimensionality-reduction dialogs.
        """
        allowed = self._selected_oids_set() if only_selected else None
        col = None if src == "Structure" else self.headers.index(src)
        visible_rows: set[int] | None = None
        if only_visible:
            vis = self._visible_source_row_indices()
            visible_rows = None if vis is None else set(vis)
        is_pixmap_src = src != "Structure" and self._table_model.is_pixmap_data_column(src)

        def _resolve(r: int, oid: int) -> Chem.Mol | None:
            if src == "Structure":
                return self.mols.get(oid) or self._mol_for_structure_row(r)
            if is_pixmap_src:
                raw = self._table_model.backing_value_for_row_header(r, src)
                mol = self._mol_from_structure_text(raw) if raw else None
                return mol
            raw = self._table_cell_text(r, col)
            if not raw:
                raw = self._table_model.backing_value_for_row_header(r, src)
            return self._mol_from_structure_text(raw) if raw else None

        return collect_scoped_pairs(
            self._table_model.rowCount(),
            row_oid=self._table_model.row_oid,
            resolve=_resolve,
            allowed_oids=allowed,
            visible_rows=visible_rows,
        )

    def collect_scoped_table_smiles(
        self,
        src: str,
        *,
        only_selected: bool = False,
        only_visible: bool = False,
        process_ui_every: int = 64,
    ) -> list[tuple[int, str]]:
        """
        Like :meth:`collect_scoped_table_mols` but returns ``(oid, SMILES text)`` without RDKit parsing.

        Periodically pumps the event loop so large tables stay responsive while gathering inputs.
        """
        from PySide6.QtWidgets import QApplication

        allowed = self._selected_oids_set() if only_selected else None
        col = None if src == "Structure" else self.headers.index(src)
        visible_rows: set[int] | None = None
        if only_visible:
            vis = self._visible_source_row_indices()
            visible_rows = None if vis is None else set(vis)
        is_pixmap_src = src != "Structure" and self._table_model.is_pixmap_data_column(src)
        smiles_h = self._canonical_smiles_header_for_updates()
        every = int(process_ui_every)

        def _on_row(r: int) -> None:
            if every > 0 and r > 0 and r % every == 0:
                QApplication.processEvents()

        def _resolve(r: int, oid: int) -> str | None:
            raw = ""
            if src == "Structure":
                if smiles_h:
                    raw = (
                        self._table_model.backing_value_for_row_header(r, smiles_h) or ""
                    ).strip()
                    if not raw:
                        raw = (self._table_cell_text(r, self.headers.index(smiles_h)) or "").strip()
                if not raw:
                    mol = self.mols.get(oid)
                    if mol is None:
                        mol = self._mol_for_structure_row(r)
                    if mol is not None:
                        try:
                            raw = mol_to_canonical_smiles(mol)
                        except Exception:
                            raw = ""
            elif is_pixmap_src:
                raw = (self._table_model.backing_value_for_row_header(r, src) or "").strip()
            else:
                raw = (self._table_cell_text(r, col) or "").strip()
                if not raw:
                    raw = (self._table_model.backing_value_for_row_header(r, src) or "").strip()
            smi = raw.strip()
            return smi or None

        return collect_scoped_pairs(
            self._table_model.rowCount(),
            row_oid=self._table_model.row_oid,
            resolve=_resolve,
            allowed_oids=allowed,
            visible_rows=visible_rows,
            on_row=_on_row,
        )

    def _apply_structure_field_override(self, mol: Chem.Mol | None) -> Chem.Mol | None:
        field = getattr(self, "_structure_field_override", None)
        if not field or mol is None:
            return mol
        if is_tool_generated_structure_header(str(field)):
            return mol
        if not mol.HasProp(field):
            return mol
        raw = (safe_mol_prop_string(mol, field) or "").strip()
        nm = self._mol_from_structure_text(raw)
        return nm if nm is not None else mol

    def logical_row_for_oid(self, oid: int) -> int:
        """Return the logical table row for a compound OID, or -1 if missing."""
        return self._table_model.logical_row_for_oid(int(oid))

    def _resolve_structure_row_for_oid(self, oid: int) -> int:
        """Table row index for this molecule id (stable during a Render 2D batch)."""
        return resolve_structure_row_for_oid(
            oid,
            row_count=self._table_model.rowCount(),
            cell_text_col0=lambda r: self._table_model.cell_text(r, 0),
            logical_row_for_oid=self.logical_row_for_oid,
            render2d_row_by_oid=getattr(self, "_render2d_row_by_oid", None),
        )
