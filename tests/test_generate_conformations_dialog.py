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

"""Generate Conformations dialog configuration."""

from __future__ import annotations

import pytest

pytest.importorskip("PyQt5.QtWidgets")

from molmanager.ui.dialogs.mol_tools import GenerateConformationsDialog


def test_generate_conformations_dialog_align_params(qapp):  # noqa: ARG001
    dlg = GenerateConformationsDialog(0)
    p = dlg.params()
    assert p.align_pattern == ""
    assert p.align_pattern_is_smarts is False
    dlg.align_pat_edit.setText(" c1ccccc1 ")
    dlg.align_smarts_cb.setChecked(True)
    p = dlg.params()
    assert p.align_pattern == "c1ccccc1"
    assert p.align_pattern_is_smarts is True
