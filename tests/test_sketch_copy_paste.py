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

"""Sketcher selection copy / paste and context-menu wiring."""

from __future__ import annotations

from PyQt5.QtCore import QPoint
from PyQt5.QtWidgets import QApplication, QMenu, QWidget

from molmanager.ui.sketcher.bonds import _bond_make
from molmanager.ui.sketcher.customize_elements import default_toolbar_element_symbols
from molmanager.ui.sketcher.dialog import SketcherDialog
from molmanager.ui.sketcher.widget import SketchWidget


def _ethane_widget() -> SketchWidget:
    w = SketchWidget()
    w.select_mode = True
    w.nodes = [
        {"id": 0, "pos": QPoint(100, 100), "element": "C"},
        {"id": 1, "pos": QPoint(160, 100), "element": "C"},
    ]
    w.bonds = [_bond_make(0, 1, 1, 0)]
    w.next_id = 2
    w.selected_nodes = [0, 1]
    w.selected_bond_indices = {0}
    return w


def test_copy_paste_selection_roundtrip(qapp) -> None:  # noqa: ARG001
    w = _ethane_widget()
    QApplication.clipboard().setText("")
    assert w.copy_selection_to_clipboard()
    assert w.clipboard_has_sketch_fragment()
    n_before = len(w.nodes)
    assert w.paste_from_clipboard(QPoint(300, 300))
    assert len(w.nodes) == n_before + 2


def test_copy_paste_menu_leads_with_copy_paste_and_divider(qapp) -> None:  # noqa: ARG001
    w = _ethane_widget()
    QApplication.clipboard().setText("")
    menu = QMenu(w)
    w._add_copy_paste_menu_actions(menu, paste_anchor=QPoint(10, 10))
    acts = menu.actions()
    assert acts[0].text() == "Copy"
    assert acts[0].isEnabled()
    assert acts[1].text() == "Paste"
    assert not acts[1].isEnabled()
    assert acts[2].isSeparator()


def test_empty_canvas_menu_starts_with_copy_paste(qapp, monkeypatch) -> None:  # noqa: ARG001
    dlg = SketcherDialog(QWidget(), element_symbols=default_toolbar_element_symbols())
    captured: dict[str, object] = {}

    def _fake_exec(self, pos):  # noqa: ARG001
        captured["texts"] = [a.text() for a in self.actions()[:3]]
        captured["sep"] = bool(self.actions()[2].isSeparator())
        return None

    monkeypatch.setattr(QMenu, "exec_", _fake_exec)
    dlg.show_sketch_canvas_menu(QPoint(0, 0))
    assert captured["texts"][:2] == ["Copy", "Paste"]
    assert captured["sep"] is True
    dlg.close()
