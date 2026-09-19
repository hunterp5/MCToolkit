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

"""Selection rotate / flip transforms."""

from __future__ import annotations

from PySide6.QtCore import QPoint

from molmanager.ui.sketcher.bonds import _bond_make
from molmanager.ui.sketcher.widget import SketchWidget


def _ethane_widget() -> SketchWidget:
    w = SketchWidget()
    w.select_mode = True
    w.nodes = [
        {"id": 0, "pos": QPoint(100, 100), "element": "C"},
        {"id": 1, "pos": QPoint(160, 100), "element": "C"},
        {"id": 2, "pos": QPoint(190, 140), "element": "O"},
    ]
    w.bonds = [_bond_make(0, 1, 1, 0), _bond_make(1, 2, 1, 0)]
    w.next_id = 3
    w.selected_nodes = [0, 1, 2]
    w.selected_bond_indices = {0, 1}
    return w


def test_flip_horizontal_selection(qapp) -> None:  # noqa: ARG001
    w = _ethane_widget()
    x_before = [n["pos"].x() for n in w.nodes]
    assert w.flip_selection_horizontal()
    xs = [n["pos"].x() for n in w.nodes]
    # Relative order of x should reverse about centroid.
    assert xs[0] > xs[2]
    assert xs != x_before
    w.undo()
    assert [n["pos"].x() for n in w.nodes] == x_before


def test_flip_vertical_selection(qapp) -> None:  # noqa: ARG001
    w = _ethane_widget()
    assert w.flip_selection_vertical()
    # Atom 2 was below the C–C axis; after vertical flip it should be above.
    assert w.nodes[2]["pos"].y() < w.nodes[0]["pos"].y()


def test_rotate_selection_90(qapp) -> None:  # noqa: ARG001
    w = _ethane_widget()
    assert w.rotate_selection(90.0)
    # Horizontal C–C becomes roughly vertical.
    dx = abs(w.nodes[0]["pos"].x() - w.nodes[1]["pos"].x())
    dy = abs(w.nodes[0]["pos"].y() - w.nodes[1]["pos"].y())
    assert dy > dx
