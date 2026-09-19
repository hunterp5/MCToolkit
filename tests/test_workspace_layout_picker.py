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

"""Tests for the graphic workspace layout picker."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6.QtWidgets")

from PySide6.QtWidgets import QApplication

from molmanager.ui.dialogs.workspace_layout_picker import (
    LayoutPreviewTile,
    WorkspaceLayoutPickerDialog,
)
from molmanager.ui.main_window.workspace_layout import LAYOUT_PRESETS, LAYOUT_TABLE_STACK


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
