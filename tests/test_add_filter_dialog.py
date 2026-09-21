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

"""Add-filter dialog and substructure structure-source option."""

from __future__ import annotations

from PySide6.QtWidgets import QDialog
from rdkit import Chem

from mctoolkit.ui.dialogs.add_filter import FILTER_TYPE_CHOICES, AddFilterDialog
from mctoolkit.ui.main_window import ChemistryWorkspaceWindow
from mctoolkit.ui.widgets import SubstructureFilterCard


def _src_row_visible(w: ChemistryWorkspaceWindow, source_row: int) -> bool:
    return w._is_source_row_visible(source_row)


def test_add_filter_dialog_choices():
    kinds = [k for k, _label, _tip in FILTER_TYPE_CHOICES]
    assert kinds == ["substructure", "slider", "text", "category"]


def test_add_filter_dialog_selects_kind(qapp):  # noqa: ARG001
    dlg = AddFilterDialog()
    dlg._list.setCurrentRow(1)
    dlg._accept_current()
    assert dlg.result() == QDialog.Accepted
    assert dlg.selected_kind() == "slider"


def test_substructure_card_structure_source_roundtrip(qapp):  # noqa: ARG001
    card = SubstructureFilterCard(structure_sources=["Structure", "SMILES", "InChI"])
    assert card.structure_source() == "Structure"
    card.set_structure_source("SMILES")
    assert card.structure_source() == "SMILES"
    cfg = card.get_cfg()
    assert cfg["structure_source"] == "SMILES"
    card.set_structure_sources(["Structure", "Canon_SMILES"])
    assert card.structure_source() == "Structure"


def test_substructure_filter_uses_selected_structure_source(qapp):  # noqa: ARG001
    w = ChemistryWorkspaceWindow()
    w.headers = ["ID_HIDDEN", "Structure", "AltSMILES"]
    w._table_model.set_headers(list(w.headers))
    # Structure mols are ethane; AltSMILES holds benzene for row 0.
    w._table_model.append_row(0, {"AltSMILES": "c1ccccc1"})
    w._table_model.append_row(1, {"AltSMILES": "CC"})
    w.mols[0] = Chem.MolFromSmiles("CC")
    w.mols[1] = Chem.MolFromSmiles("CC")
    w.next_oid = 2
    w.calculate_global_bounds()
    card = SubstructureFilterCard(structure_sources=["Structure", "AltSMILES"])
    card.set_structure_source("AltSMILES")
    card.set_smarts("c1ccccc1")
    w.filters = [card]
    w._apply_filters_impl_sync(None)
    assert _src_row_visible(w, 0) is True
    assert _src_row_visible(w, 1) is False
    # Same SMARTS against Structure should hide both (both are ethane).
    card.set_structure_source("Structure")
    w._apply_filters_impl_sync(None)
    assert _src_row_visible(w, 0) is False
    assert _src_row_visible(w, 1) is False
