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

"""Tests for 2D structure depiction size settings."""

from __future__ import annotations

import pytest

pytest.importorskip("PyQt5.QtWidgets")

from molmanager.table.structure_depiction_layout import (
    DEFAULT_STRUCTURE_DEPICT_HEIGHT,
    DEFAULT_STRUCTURE_DEPICT_WIDTH,
    DEFAULT_STRUCTURE_ROW_DEFAULT_HEIGHT,
    MAX_STRUCTURE_DEPICT_HEIGHT,
    MAX_STRUCTURE_DEPICT_WIDTH,
    MIN_STRUCTURE_DEPICT_HEIGHT,
    MIN_STRUCTURE_DEPICT_WIDTH,
    set_structure_depict_size,
    structure_column_minimum_width,
    structure_depict_height,
    structure_depict_width,
    structure_row_default_height,
)


@pytest.fixture(autouse=True)
def _reset_structure_size():
    set_structure_depict_size(
        DEFAULT_STRUCTURE_DEPICT_WIDTH,
        DEFAULT_STRUCTURE_DEPICT_HEIGHT,
        persist=False,
    )
    yield
    set_structure_depict_size(
        DEFAULT_STRUCTURE_DEPICT_WIDTH,
        DEFAULT_STRUCTURE_DEPICT_HEIGHT,
        persist=False,
    )


def test_set_structure_depict_size_clamps_and_updates_runtime() -> None:
    w, h = set_structure_depict_size(9999, 10, persist=False)
    assert w == MAX_STRUCTURE_DEPICT_WIDTH
    assert h == MIN_STRUCTURE_DEPICT_HEIGHT
    assert structure_depict_width() == MAX_STRUCTURE_DEPICT_WIDTH
    assert structure_depict_height() == MIN_STRUCTURE_DEPICT_HEIGHT


def test_structure_row_default_height_tracks_depiction_height() -> None:
    set_structure_depict_size(180, 150, persist=False)
    assert structure_row_default_height() == 150 + (
        DEFAULT_STRUCTURE_ROW_DEFAULT_HEIGHT - DEFAULT_STRUCTURE_DEPICT_HEIGHT
    )


def test_structure_column_minimum_width_uses_runtime_size() -> None:
    set_structure_depict_size(300, 250, persist=False)
    assert structure_column_minimum_width() == 300 + 28
    assert structure_column_minimum_width(zoomed=True) == 600 + 28


def test_structure_column_minimum_width_tracks_runtime_size() -> None:
    set_structure_depict_size(300, 250, persist=False)
    assert structure_column_minimum_width() == 300 + 28


def test_reaction_depict_size_is_wider_same_height() -> None:
    from molmanager.table.structure_depiction_layout import (
        REACTION_DEPICT_WIDTH_MULTIPLIER,
        reaction_depict_size,
    )

    set_structure_depict_size(200, 160, persist=False)
    w, h = reaction_depict_size()
    assert w == 200 * REACTION_DEPICT_WIDTH_MULTIPLIER
    assert h == 160
    zw, zh = reaction_depict_size(zoomed=True)
    assert zw == 400 * REACTION_DEPICT_WIDTH_MULTIPLIER
    assert zh == 320
    assert structure_depict_width() == 200
    assert structure_depict_height() == 160
