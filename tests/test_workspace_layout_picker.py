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

"""Tests for the graphic workspace layout picker."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6.QtWidgets")

from PySide6.QtWidgets import QApplication

from mctoolkit.ui.dialogs.workspace_layout_picker import (
    LayoutPreviewTile,
    WorkspaceLayoutPickerDialog,
)
from mctoolkit.ui.main_window.workspace_layout import LAYOUT_PRESETS, LAYOUT_TABLE_STACK


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_layout_picker_lists_all_presets(qapp):
    dlg = WorkspaceLayoutPickerDialog(None, current_layout_id=LAYOUT_TABLE_STACK)
    assert len(dlg._tiles) == len(LAYOUT_PRESETS)
    ids = {t.layout_id for t in dlg._tiles}
    assert ids == {lid for lid, _ in LAYOUT_PRESETS}
    selected = [t for t in dlg._tiles if t._selected]
    assert len(selected) == 1
    assert selected[0].layout_id == LAYOUT_TABLE_STACK


def test_layout_tile_emits_chosen(qapp):
    chosen: list[str] = []
    tile = LayoutPreviewTile("table_only", "Table Only")
    tile.chosen.connect(chosen.append)
    tile.chosen.emit("table_only")
    assert chosen == ["table_only"]


def test_layout_tile_paint_uses_qpalette_color_roles(qapp):  # noqa: ARG001
    """PySide6 palettes have no instance attributes like ``Mid``; painting must use QPalette roles."""
    from PySide6.QtCore import QSize

    tile = LayoutPreviewTile("table_stack", "Table + stacked plots", selected=True)
    tile.resize(QSize(220, 180))
    pix = tile.grab()
    assert not pix.isNull()
    assert pix.width() > 0
    dlg = WorkspaceLayoutPickerDialog(None, current_layout_id=LAYOUT_TABLE_STACK)
    dlg.resize(680, 420)
    shot = dlg.grab()
    assert not shot.isNull()
    dlg.close()
