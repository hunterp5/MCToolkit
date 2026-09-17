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
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with MolManager. If not, see <https://www.gnu.org/licenses/>.

"""Calculate Descriptors Name tab includes PubChem lookups."""

from __future__ import annotations

from molmanager.ui.dialogs.properties import PropertyDialog


def test_property_dialog_name_tab_includes_common_name_and_synonyms(qapp) -> None:  # noqa: ARG001
    dlg = PropertyDialog(["Structure", "SMILES"], selected_row_count=0)
    assert "Common Name" in dlg.cbs
    assert "Synonyms" in dlg.cbs
    assert dlg.cbs["Common Name"][1] == "COMMON_NAME"
    assert dlg.cbs["Synonyms"][1] == "SYNONYMS"
    assert "PubChem" in dlg.cbs["Common Name"][0].toolTip()
    dlg.cbs["Common Name"][0].setChecked(True)
    dlg.cbs["Synonyms"][0].setChecked(True)
    disp, fns = dlg.get_selected()
    assert disp == ["Common Name", "Synonyms"]
    assert fns == ["COMMON_NAME", "SYNONYMS"]
    dlg.close()
