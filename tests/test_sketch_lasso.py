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
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with mctoolkit.  If not, see <https://www.gnu.org/licenses/>.

"""Lasso selection hit-testing."""

from __future__ import annotations

from PySide6.QtCore import QPoint

from mctoolkit.ui.sketcher.bonds import _bond_make
from mctoolkit.ui.sketcher.widget import SketchWidget


def test_lasso_selects_atoms_inside_path(qapp) -> None:  # noqa: ARG001
    w = SketchWidget()
    w.select_mode = True
    w.select_tool = "lasso"
    w.nodes = [
        {"id": 0, "pos": QPoint(100, 100), "element": "C"},
        {"id": 1, "pos": QPoint(160, 100), "element": "C"},
        {"id": 2, "pos": QPoint(300, 300), "element": "O"},
    ]
    w.bonds = [_bond_make(0, 1, 1, 0)]
    w.next_id = 3
    # Closed diamond around the C–C bond (widget == model with scale 1).
    w._view_scale = 1.0
    w._lasso_points = [
        QPoint(80, 80),
        QPoint(180, 80),
        QPoint(180, 140),
        QPoint(80, 140),
    ]
    w._apply_lasso_selection_from_points()
    assert set(w.selected_nodes) == {0, 1}
    assert 0 in w.selected_bond_indices
    assert 2 not in w.selected_nodes
