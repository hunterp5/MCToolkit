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

"""Fast Prepare dialog configuration."""

from __future__ import annotations

import pytest

pytest.importorskip("PyQt5.QtWidgets")

from molmanager.ui.dialogs.mol_tools import FastPrepareDialog


def test_fast_prepare_dialog_config(qapp):  # noqa: ARG001
    dlg = FastPrepareDialog(["Structure", "SMILES"], ["Structure", "SMILES"], 2)
    src, update_target, largest, fragments, only_sel, neutralize = dlg.config()
    assert src == "Structure"
    assert update_target is True
    assert largest is None
    assert fragments == "Fragments"
    assert only_sel is False
    assert neutralize is False
    assert dlg.neutralize_cb.isChecked() is False


def test_fast_prepare_dialog_new_column_mode(qapp):  # noqa: ARG001
    dlg = FastPrepareDialog(["Structure", "SMILES"], ["Structure", "SMILES"], 0)
    dlg.radio_new_columns.setChecked(True)
    dlg.largest_edit.setText("Largest")
    dlg.fragments_edit.setText("Rest")
    dlg.neutralize_cb.setChecked(True)
    src, update_target, largest, fragments, only_sel, neutralize = dlg.config()
    assert src == "Structure"
    assert update_target is False
    assert largest == "Largest"
    assert fragments == "Rest"
    assert only_sel is False
    assert neutralize is True
