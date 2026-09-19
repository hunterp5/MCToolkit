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

from molmanager.ui.compound_table_model import CompoundTableModel


def test_append_rows_batch_inserts_all_rows():
    model = CompoundTableModel(["ID_HIDDEN", "Structure", "SMILES", "MW"])
    model.append_rows_batch(
        [
            (10, {"SMILES": "CCO", "MW": "46.1"}),
            (11, {"SMILES": "CCN", "MW": "45.0"}),
            (12, {"SMILES": "CCC", "MW": "44.0"}),
        ]
    )
    assert model.rowCount() == 3
    assert model.row_oid(0) == 10
    assert model.cell_text(2, 2) == "CCC"
    bounds = model.numeric_bounds_by_column()
    assert "MW" in bounds
    assert bounds["MW"]["max"] >= bounds["MW"]["min"]


def test_apply_columns_values_bulk_emits_sparse_row_ranges(qapp):  # noqa: ARG001
    """Bulk column writes should not repaint the entire table when few rows change."""
    model = CompoundTableModel(["ID_HIDDEN", "Structure", "SMILES", "pKa"])
    for oid in range(20):
        model.append_row(oid, {"SMILES": "C", "pKa": ""})
    emitted: list[tuple[int, int]] = []

    def _capture(_tl, br, _roles=None):
        emitted.append((_tl.row(), br.row()))

    model.dataChanged.connect(_capture)
    model.apply_columns_values_bulk(
        ["pKa"],
        [(2, {"pKa": "9.1"}), (5, {"pKa": "4.2"}), (17, {"pKa": "11.0"})],
    )
    assert emitted == [(2, 2), (5, 5), (17, 17)]
