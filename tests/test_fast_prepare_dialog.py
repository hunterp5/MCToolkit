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

"""Fast Prepare dialog configuration."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6.QtWidgets")

from mctoolkit.ui.dialogs.mol_tools import FastPrepareDialog
from mctoolkit.ui.dialogs.fast_prepare import FastPrepareDialogConfig


def test_fast_prepare_dialog_config(qapp):  # noqa: ARG001
    dlg = FastPrepareDialog(["Structure", "SMILES"], ["Structure", "SMILES"], 2)
    cfg = dlg.config()
    assert cfg == FastPrepareDialogConfig(
        source_column="Structure",
        update_target=True,
        largest_column=None,
        fragments_column="Fragments",
        only_selected=False,
        neutralize=False,
    )
    assert dlg.neutralize_cb.isChecked() is False


def test_fast_prepare_dialog_new_column_mode(qapp):  # noqa: ARG001
    dlg = FastPrepareDialog(["Structure", "SMILES"], ["Structure", "SMILES"], 0)
    dlg.radio_new_columns.setChecked(True)
    dlg.largest_edit.setText("Largest")
    dlg.fragments_edit.setText("Rest")
    dlg.neutralize_cb.setChecked(True)
    cfg = dlg.config()
    assert cfg.source_column == "Structure"
    assert cfg.update_target is False
    assert cfg.largest_column == "Largest"
    assert cfg.fragments_column == "Rest"
    assert cfg.only_selected is False
    assert cfg.neutralize is True
