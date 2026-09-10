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

"""Main-window mixin smoke tests (clear_all, selection, chemistry sources)."""

from __future__ import annotations

from rdkit import Chem

from molmanager.ui.main_window import ChemicalTableApp


def _seed_two_rows(w: ChemicalTableApp) -> None:
    w.headers = ["ID_HIDDEN", "Structure", "SMILES", "MW"]
    w._table_model.set_headers(list(w.headers))
    w._table_model.append_row(0, {"SMILES": "CCO", "MW": "46.07"})
    w._table_model.append_row(1, {"SMILES": "CC", "MW": "30.07"})
    w.mols[0] = Chem.MolFromSmiles("CCO")
    w.mols[1] = Chem.MolFromSmiles("CC")
    w.next_oid = 2


def test_clear_all_resets_table_and_ingest_flags(qapp):  # noqa: ARG001
    w = ChemicalTableApp()
    _seed_two_rows(w)
    w._selected_oids_override = frozenset({0})
    w._set_ingest_loading(True)

    w.clear_all()

    assert w._table_model.rowCount() == 0
    assert w.mols == {}
    assert w.headers == []
    assert w.next_oid == 0
    assert w._selected_oids_override is None
    assert w._ingest_loading is False


def test_select_table_oids_updates_selection_set(qapp):  # noqa: ARG001
    w = ChemicalTableApp()
    _seed_two_rows(w)

    n = w.select_table_oids({1})
    qapp.processEvents()

    assert n == 1
    assert w._selected_oids_set() == {1}
    assert w._selected_logical_rows() == [1]


def test_selected_oids_override_preferred(qapp):  # noqa: ARG001
    w = ChemicalTableApp()
    _seed_two_rows(w)
    w.select_table_oids({0})
    qapp.processEvents()
    w._selected_oids_override = frozenset({1})

    assert w._selected_oids_set() == {1}


def test_chemistry_tool_structure_sources_smoke(qapp):  # noqa: ARG001
    w = ChemicalTableApp()
    _seed_two_rows(w)

    sources = w.chemistry_tool_structure_sources()
    assert sources[0] == "Structure"
    assert "SMILES" in sources
    assert "MW" not in sources
    assert w._canonical_smiles_header_for_updates() == "SMILES"


def test_new_window_and_file_load_use_table_only_layout(qapp):  # noqa: ARG001
    from molmanager.ui.main_window.workspace_layout import LAYOUT_TABLE_ONLY, LAYOUT_TABLE_STACK

    w = ChemicalTableApp()
    assert w._workspace_layout.layout_id == LAYOUT_TABLE_ONLY
    w.apply_workspace_layout(LAYOUT_TABLE_STACK)
    assert w._workspace_layout.layout_id == LAYOUT_TABLE_STACK
    w._apply_table_only_layout_for_file_load()
    assert w._workspace_layout.layout_id == LAYOUT_TABLE_ONLY


def test_clear_all_re_enables_menubar_after_ingest(qapp):  # noqa: ARG001
    w = ChemicalTableApp()
    _seed_two_rows(w)
    mb = w.menuBar()
    file_menu = next(a.menu() for a in mb.actions() if a.menu() is not None)
    w._set_ingest_loading(True)
    assert not file_menu.isEnabled()

    w.clear_all()

    assert file_menu.isEnabled()
    assert w._btn_workspace_layout.isEnabled()
