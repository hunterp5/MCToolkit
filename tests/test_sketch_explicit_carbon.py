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

"""Explicit carbon label and Save Sketch naming."""

from __future__ import annotations

from qt_helpers import qt_submenu

from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QMenuBar, QWidget

from mctoolkit.ui.sketcher.bonds import _bond_make
from mctoolkit.ui.sketcher.dialog import SketcherDialog
from mctoolkit.ui.sketcher.widget import SketchWidget


def test_file_menu_save_sketch_label(qapp) -> None:  # noqa: ARG001
    dlg = SketcherDialog(QWidget())
    mb = dlg.findChild(QMenuBar)
    assert mb is not None
    file_menu = qt_submenu(mb, "File")
    texts = [a.text().replace("&", "") for a in file_menu.actions()]
    assert any(t.startswith("Save Sketch") for t in texts)
    assert not any("Export sketch" in t for t in texts)
    dlg.close()


def test_explicit_carbon_toggle(qapp) -> None:  # noqa: ARG001
    w = SketchWidget()
    w.nodes = [
        {"id": 1, "pos": QPoint(40, 40), "element": "C"},
        {"id": 2, "pos": QPoint(100, 40), "element": "C"},
    ]
    w.bonds = [_bond_make(1, 2, 1, 0)]
    w.next_id = 3
    assert not w.nodes[0].get("explicit_carbon")
    w._set_explicit_carbon_visible(1, True)
    assert w.nodes[0].get("explicit_carbon") is True
    # Terminal methyl-like carbon (one single bond) → CH3
    assert w._explicit_carbon_display_label(w.nodes[0]) == "CH3"
    w.nodes[0]["charge"] = 1
    # Charge-aware valence: C+ with one bond still has room for H's
    assert w._explicit_carbon_display_label(w.nodes[0]).startswith("CH")
    w.undo()
    assert not w.nodes[0].get("explicit_carbon")
    w.redo()
    assert w.nodes[0].get("explicit_carbon") is True
