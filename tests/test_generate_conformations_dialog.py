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


def test_generate_conformations_dialog_fine_tune_params(qapp):  # noqa: ARG001
    dlg = GenerateConformationsDialog(0)
    p = dlg.params()
    assert p.force_field == "MMFF"
    assert p.post_min_rms_threshold == 0.0
    assert p.max_keep == 0
    assert p.use_random_coords is False
    assert p.keep_hydrogens is False
    dlg.ff_combo.setCurrentText("MMFF94s")
    dlg.post_min_rms_sb.setValue(0.5)
    dlg.max_keep_sb.setValue(5)
    dlg.advanced_panel.random_coords_cb.setChecked(True)
    dlg.advanced_panel.keep_hs_cb.setChecked(True)
    dlg.advanced_panel.setChecked(False)
    p = dlg.params()
    assert p.force_field == "MMFF94s"
    assert p.post_min_rms_threshold == pytest.approx(0.5)
    assert p.max_keep == 5
    assert p.use_random_coords is False
    assert p.keep_hydrogens is False
    dlg.advanced_panel.setChecked(True)
    p = dlg.params()
    assert p.use_random_coords is True
    assert p.keep_hydrogens is True
    assert p.enforce_chirality is True


def test_generate_conformations_dialog_advanced_box_hidden_until_checked(qapp):  # noqa: ARG001
    dlg = GenerateConformationsDialog(0)
    assert dlg.advanced_panel.advanced_cb.text() == "Advanced"
    assert dlg.advanced_panel.isChecked() is False
    assert dlg.advanced_panel._box.isHidden() is True
    dlg.advanced_panel.setChecked(True)
    assert dlg.advanced_panel._box.isHidden() is False
    assert dlg.output_panel.add_to_table_cb.text() == "Add as Entries"
