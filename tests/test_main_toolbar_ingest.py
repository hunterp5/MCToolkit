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

"""Main menubar stays disabled while the table is loading."""

from __future__ import annotations

from PyQt5.QtCore import Qt

from molmanager.ui.main_window import ChemicalTableApp


def test_main_toolbar_disabled_while_ingest_loading(qapp):  # noqa: ARG001
    w = ChemicalTableApp()
    mb = w.menuBar()
    file_menu = next(a.menu() for a in mb.actions() if a.menu() is not None)

    assert file_menu.isEnabled()
    assert w._btn_workspace_layout.isEnabled()
    assert w._btn_processes.isEnabled()
    assert w._btn_help.isEnabled()

    w._set_ingest_loading(True)
    assert not file_menu.isEnabled()
    assert not w._btn_workspace_layout.isEnabled()
    assert w._btn_processes.isEnabled()
    assert w._btn_help.isEnabled()
    assert w._act_user_guide.isEnabled()

    w._set_ingest_loading(False)
    assert file_menu.isEnabled()
    assert w._btn_workspace_layout.isEnabled()
    assert w._btn_processes.isEnabled()
    assert w._btn_help.isEnabled()
    w.close()


def test_help_is_corner_glyph_right_of_processes(qapp):  # noqa: ARG001
    w = ChemicalTableApp()
    mb = w.menuBar()
    labels = [a.text().replace("&", "") for a in mb.actions() if a.text()]
    assert "Help" not in labels
    btn = w._btn_help
    assert btn.toolButtonStyle() == Qt.ToolButtonIconOnly
    assert not btn.icon().isNull()
    assert btn.iconSize().width() >= 16
    corner = mb.cornerWidget(Qt.TopRightCorner)
    ly = corner.layout()
    widgets = [ly.itemAt(i).widget() for i in range(ly.count())]
    assert widgets[-2] is w._btn_processes
    assert widgets[-1] is btn
    assert btn.menu() is None
    w.close()


def test_help_glyph_is_filled_question_badge(qapp):  # noqa: ARG001
    from PyQt5.QtGui import QColor, QImage

    from molmanager.ui.main_window.app_menu_mixin import _help_glyph_icon

    ink = QColor(20, 20, 20)
    paper = QColor(240, 240, 240)
    icon = _help_glyph_icon(size=24, ink=ink, paper=paper)
    pm = icon.pixmap(24, 24)
    img = pm.toImage().convertToFormat(QImage.Format_ARGB32)
    dark = 0
    light = 0
    for y in range(img.height()):
        for x in range(img.width()):
            c = QColor(img.pixel(x, y))
            if c.alpha() < 40:
                continue
            if c.lightness() < 80:
                dark += 1
            elif c.lightness() > 180:
                light += 1
    assert dark > 80
    assert light > 20


def test_main_window_table_sits_flush_under_menubar(qapp):  # noqa: ARG001
    w = ChemicalTableApp()
    ly = w.centralWidget().layout()
    m = ly.contentsMargins()
    assert (m.left(), m.top(), m.right(), m.bottom()) == (0, 0, 0, 0)
    assert ly.spacing() == 0
    w.close()
