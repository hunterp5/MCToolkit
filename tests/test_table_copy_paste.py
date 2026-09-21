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
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with mctoolkit. If not, see <https://www.gnu.org/licenses/>.

"""Excel-style rectangular table copy/paste."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6.QtWidgets")

from PySide6.QtCore import QItemSelectionModel
from PySide6.QtWidgets import QApplication

from mctoolkit.ui.main_window import ChemistryWorkspaceWindow
from mctoolkit.ui.table_clipboard import format_tsv_grid, parse_tsv_grid, tsv_grid_is_block


def test_parse_and_format_tsv_grid_roundtrip() -> None:
    grid = [["a", "b"], ["c", "d"]]
    text = format_tsv_grid(grid)
    assert text == "a\tb\nc\td"
    assert parse_tsv_grid(text) == grid
    assert parse_tsv_grid("a\tb\nc\td\n") == grid
    assert tsv_grid_is_block(grid) is True
    assert tsv_grid_is_block([["only"]]) is False


def test_parse_tsv_grid_pads_ragged_rows() -> None:
    assert parse_tsv_grid("a\tb\nc") == [["a", "b"], ["c", ""]]


def _seed_grid(w: ChemistryWorkspaceWindow) -> None:
    w.headers = ["ID_HIDDEN", "Structure", "A", "B", "C"]
    w._table_model.set_headers(list(w.headers))
    w._table_model.append_row(0, {"A": "a1", "B": "b1", "C": ""})
    w._table_model.append_row(1, {"A": "a2", "B": "b2", "C": ""})
    w._table_model.append_row(2, {"A": "", "B": "", "C": ""})
    w.next_oid = 3


def _select_source_cells(w: ChemistryWorkspaceWindow, cells: list[tuple[int, int]]) -> None:
    sm = w.table.selectionModel()
    proxy = getattr(w, "_filter_proxy_model", None)
    use_proxy = proxy is not None and w.table.model() is proxy
    first = True
    for row, col in cells:
        src = w._table_model.index(row, col)
        view_ix = proxy.mapFromSource(src) if use_proxy else src
        flags = QItemSelectionModel.Select
        if first:
            flags = QItemSelectionModel.ClearAndSelect
            w.table.setCurrentIndex(view_ix)
            first = False
        sm.select(view_ix, flags)


def test_copy_rectangular_block_to_clipboard(qapp) -> None:  # noqa: ARG001
    w = ChemistryWorkspaceWindow()
    _seed_grid(w)
    _select_source_cells(w, [(0, 2), (0, 3), (1, 2), (1, 3)])
    w.edit_copy()
    assert QApplication.clipboard().text() == "a1\tb1\na2\tb2"


def test_paste_block_from_top_left_into_empty_cells(qapp) -> None:  # noqa: ARG001
    w = ChemistryWorkspaceWindow()
    _seed_grid(w)
    QApplication.clipboard().setText("x\ty\nxx\tyy")
    w.edit_paste(origin=(2, 2), block_mode="multi", overwrite=True)
    assert w._table_model.cell_text(2, 2) == "x"
    assert w._table_model.cell_text(2, 3) == "y"
    # Only one empty row; extra clipboard row is clipped.
    assert w._table_model.cell_text(1, 2) == "a2"
    assert "filled 2" in (w.status_label.text() or "")


def test_paste_block_overwrite_can_be_cancelled(qapp) -> None:  # noqa: ARG001
    w = ChemistryWorkspaceWindow()
    _seed_grid(w)
    QApplication.clipboard().setText("z\tw")
    w.edit_paste(origin=(0, 2), block_mode="multi", overwrite=False)
    assert w._table_model.cell_text(0, 2) == "a1"
    assert w._table_model.cell_text(0, 3) == "b1"
    assert "cancelled" in (w.status_label.text() or "")


def test_paste_block_overwrite_proceeds_when_confirmed(qapp) -> None:  # noqa: ARG001
    w = ChemistryWorkspaceWindow()
    _seed_grid(w)
    QApplication.clipboard().setText("z\tw")
    w.edit_paste(origin=(0, 2), block_mode="multi", overwrite=True)
    assert w._table_model.cell_text(0, 2) == "z"
    assert w._table_model.cell_text(0, 3) == "w"


def test_paste_block_single_cell_keeps_tsv(qapp) -> None:  # noqa: ARG001
    w = ChemistryWorkspaceWindow()
    _seed_grid(w)
    QApplication.clipboard().setText("x\ty\nxx\tyy")
    w.edit_paste(origin=(2, 2), block_mode="single")
    assert w._table_model.cell_text(2, 2) == "x\ty\nxx\tyy"
    assert w._table_model.cell_text(2, 3) == ""


def test_paste_block_undo_restores_cells(qapp) -> None:  # noqa: ARG001
    w = ChemistryWorkspaceWindow()
    _seed_grid(w)
    QApplication.clipboard().setText("p\tq")
    w.edit_paste(origin=(2, 2), block_mode="multi", overwrite=True)
    assert w._table_model.cell_text(2, 2) == "p"
    w._undo_stack.undo()
    assert w._table_model.cell_text(2, 2) == ""
    assert w._table_model.cell_text(2, 3) == ""


def test_paste_block_skips_invalid_structure_cells(qapp) -> None:  # noqa: ARG001
    from rdkit import Chem

    w = ChemistryWorkspaceWindow()
    _seed_grid(w)
    w.mols[0] = Chem.MolFromSmiles("CC")
    QApplication.clipboard().setText("not-a-mol\tnew")
    w.edit_paste(origin=(0, 1), block_mode="multi", overwrite=True)
    assert Chem.MolToSmiles(w.mols[0]) == "CC"
    assert w._table_model.cell_text(0, 2) == "new"


def test_structure_copy_submenu_formats(qapp) -> None:  # noqa: ARG001
    from PySide6.QtWidgets import QMenu
    from rdkit import Chem

    from mctoolkit.ui.main_window.table_menu_mixin import TableMenuMixin

    class _Host(TableMenuMixin):
        pass

    menu = QMenu()
    by_act = _Host()._add_structure_copy_submenu(menu, Chem.MolFromSmiles("CCO"))
    labels = [act.text() for act in by_act]
    assert labels == ["SMILES", "InChI", "InChIKey", "Molfile", "SMARTS"]
    assert all(act.isEnabled() for act in by_act)
    copy_menu = next(a for a in menu.actions() if a.menu() is not None)
    assert copy_menu.text() == "Copy"
