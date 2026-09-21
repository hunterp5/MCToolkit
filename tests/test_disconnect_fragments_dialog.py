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

"""Disconnect Largest Fragments dialog configuration."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6.QtWidgets")

from mctoolkit.ui.dialogs.mol_tools import DisconnectFragmentsDialog


def test_disconnect_dialog_defaults_to_update_target(qapp):  # noqa: ARG001
    dlg = DisconnectFragmentsDialog(["Structure", "SMILES"], ["Structure", "SMILES"], 0)
    src, update_target, largest, fragments, only_sel, no_render = dlg.config()
    assert src == "Structure"
    assert update_target is True
    assert largest is None
    assert fragments == "Fragments"
    assert only_sel is False
    assert no_render is False


def test_disconnect_dialog_new_columns_mode(qapp):  # noqa: ARG001
    dlg = DisconnectFragmentsDialog(["Structure", "SMILES"], ["Structure", "SMILES"], 0)
    dlg.radio_new_columns.setChecked(True)
    dlg.largest_edit.setText("Largest")
    dlg.fragments_edit.setText("Rest")
    src, update_target, largest, fragments, only_sel, no_render = dlg.config()
    assert src == "Structure"
    assert update_target is False
    assert largest == "Largest"
    assert fragments == "Rest"
    assert only_sel is False
    assert no_render is False


def test_disconnect_dialog_no_render_2d(qapp):  # noqa: ARG001
    dlg = DisconnectFragmentsDialog(["Structure"], ["Structure"], 0)
    dlg.no_render_2d_cb.setChecked(True)
    *_, no_render = dlg.config()
    assert no_render is True
