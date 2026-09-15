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

"""Tests for table structure rendering."""

from __future__ import annotations

from molmanager.display_constants import (
    STRUCTURE_DEPICT_BOND_LINE_WIDTH,
    STRUCTURE_DEPICT_HEIGHT,
    STRUCTURE_DEPICT_WIDTH,
)
from molmanager.structure_draw import render_molecule_png, structure_cairo_dimensions


def test_structure_cairo_dimensions_match_target() -> None:
    cw, ch = structure_cairo_dimensions(STRUCTURE_DEPICT_WIDTH, STRUCTURE_DEPICT_HEIGHT)
    assert cw == STRUCTURE_DEPICT_WIDTH
    assert ch == STRUCTURE_DEPICT_HEIGHT


def test_structure_cairo_dimensions_zoomed() -> None:
    cw, ch = structure_cairo_dimensions(STRUCTURE_DEPICT_WIDTH * 2, STRUCTURE_DEPICT_HEIGHT * 2)
    assert cw == STRUCTURE_DEPICT_WIDTH * 2
    assert ch == STRUCTURE_DEPICT_HEIGHT * 2


def test_render_molecule_png_returns_bytes() -> None:
    from rdkit import Chem

    mol = Chem.MolFromSmiles("c1ccccc1")
    png = render_molecule_png(mol, STRUCTURE_DEPICT_WIDTH, STRUCTURE_DEPICT_HEIGHT)
    assert isinstance(png, (bytes, bytearray))
    assert len(png) > 100


def test_render_molecule_png_native_resolution() -> None:
    """Table renders are 1× (no supersample) for Render2D throughput."""
    from rdkit import Chem

    mol = Chem.MolFromSmiles("c1ccccc1")
    png = render_molecule_png(mol, STRUCTURE_DEPICT_WIDTH, STRUCTURE_DEPICT_HEIGHT)
    # PNG IHDR width/height are big-endian at bytes 16:24.
    assert int.from_bytes(png[16:20], "big") == STRUCTURE_DEPICT_WIDTH
    assert int.from_bytes(png[20:24], "big") == STRUCTURE_DEPICT_HEIGHT


def test_table_bond_line_width_constant() -> None:
    assert STRUCTURE_DEPICT_BOND_LINE_WIDTH < 2.0


def test_structure_column_minimum_width() -> None:
    from molmanager.display_constants import (
        DEFAULT_STRUCTURE_DEPICT_HEIGHT,
        DEFAULT_STRUCTURE_DEPICT_WIDTH,
        STRUCTURE_COLUMN_HORIZONTAL_PADDING,
        set_structure_depict_size,
        structure_column_minimum_width,
    )

    set_structure_depict_size(
        DEFAULT_STRUCTURE_DEPICT_WIDTH,
        DEFAULT_STRUCTURE_DEPICT_HEIGHT,
        persist=False,
    )
    assert (
        structure_column_minimum_width()
        == DEFAULT_STRUCTURE_DEPICT_WIDTH + STRUCTURE_COLUMN_HORIZONTAL_PADDING
    )
    assert (
        structure_column_minimum_width(zoomed=True)
        == DEFAULT_STRUCTURE_DEPICT_WIDTH * 2 + STRUCTURE_COLUMN_HORIZONTAL_PADDING
    )


def test_compound_table_view_clamps_structure_column_width(qapp) -> None:  # noqa: ARG001
    from molmanager.ui.compound_table_model import CompoundTableModel, CompoundTableView

    model = CompoundTableModel(["ID", "Structure", "SMILES"])
    view = CompoundTableView()
    view.set_compound_model(model)
    col = CompoundTableModel.STRUCTURE_COL
    min_w = view.structure_column_minimum_width()
    view.setColumnWidth(col, min_w - 40)
    assert view.columnWidth(col) == min_w
