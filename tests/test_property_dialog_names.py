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
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with mctoolkit. If not, see <https://www.gnu.org/licenses/>.

"""Calculate Descriptors Name tab lists local identifiers only."""

from __future__ import annotations

from mctoolkit.descriptors.catalog import DESCRIPTOR_TAB_ORDER, iter_descriptor_tab_items
from mctoolkit.ui.dialogs.properties import PropertyDialog


def test_property_dialog_name_tab_omits_common_name_and_synonyms(qapp) -> None:  # noqa: ARG001
    dlg = PropertyDialog(["Structure", "SMILES"], selected_row_count=0)
    assert "Common Name" not in dlg.cbs
    assert "Synonyms" not in dlg.cbs
    name_items = dict(dlg.cbs)
    assert name_items["SMILES String"][1] == "SMILES"
    assert name_items["InChI Key"][1] == "INCHIKEY"
    assert name_items["Molecular formula"][1] == "MOLFORMULA"
    dlg.close()


def test_property_dialog_checkboxes_match_catalog(qapp) -> None:  # noqa: ARG001
    dlg = PropertyDialog(["Structure"], selected_row_count=0)
    tabs = [dlg.tabs.tabText(i) for i in range(dlg.tabs.count())]
    catalog = iter_descriptor_tab_items()
    assert tabs == [name for name, _items in catalog]
    assert tabs == list(DESCRIPTOR_TAB_ORDER)
    expected = {disp: key for _tab, items in catalog for disp, key in items}
    assert {disp: internal for disp, (_cb, internal) in dlg.cbs.items()} == expected
    dlg.close()
