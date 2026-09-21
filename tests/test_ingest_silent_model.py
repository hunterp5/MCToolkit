# This file is part of MCToolkit.
# Copyright (C) 2026 Hunter Picard
#
# MCToolkit is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# MCToolkit is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with MCToolkit.  If not, see <https://www.gnu.org/licenses/>.

"""Tests for silent bulk row append on CompoundTableModel."""

from __future__ import annotations

import pytest

from mctoolkit.ui.compound_table_model import CompoundTableModel


@pytest.fixture()
def model(qapp):  # noqa: ARG001
    m = CompoundTableModel(["ID_HIDDEN", "Structure", "SMILES", "MW"])
    return m


def test_silent_append_emits_once(model: CompoundTableModel):
    model.begin_silent_appends()
    model.append_rows_batch([(1, {"SMILES": "C", "MW": "16"})], defer_color_cache=True)
    model.append_rows_batch([(2, {"SMILES": "CC", "MW": "30"})], defer_color_cache=True)
    assert model.rowCount() == 2
    model.end_silent_appends()
    assert model.rowCount() == 2
    assert model.value_for_header(0, "SMILES") == "C"
    assert model.value_for_header(1, "SMILES") == "CC"
