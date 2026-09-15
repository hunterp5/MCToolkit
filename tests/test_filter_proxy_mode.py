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

from __future__ import annotations

from molmanager.ui.compound_table_model import CompoundTableModel
from molmanager.ui.filter_proxy_model import FilterProxyModel
from molmanager.ui.filters.cards import TextFilterCard
from molmanager.ui.main_window import ChemicalTableApp


def test_proxy_filter_mode_reduces_visible_rows(qapp):  # noqa: ARG001
    w = ChemicalTableApp()
    w.headers = ["ID_HIDDEN", "Structure", "SMILES", "Note"]
    w._table_model.set_headers(list(w.headers))
    w._table_model.append_rows_batch(
        [
            (0, {"SMILES": "CCO", "Note": "alpha"}),
            (1, {"SMILES": "CCN", "Note": "beta"}),
            (2, {"SMILES": "CCC", "Note": "alpha"}),
        ]
    )
    card = TextFilterCard(["SMILES", "Note"], w)
    card.set_column("Note")
    card.text_edit.setText("alpha")
    w.filters = [card]
    w._apply_filters_impl_sync(None)
    proxy = w._filter_proxy_model
    assert proxy is not None
    assert proxy.rowCount() == 2
    w.close()


def test_filter_proxy_row_accept_bitmap(qapp):  # noqa: ARG001
    model = CompoundTableModel(["ID_HIDDEN", "Structure", "SMILES"])
    model.append_rows_batch(
        [
            (10, {"SMILES": "C"}),
            (20, {"SMILES": "CC"}),
            (30, {"SMILES": "CCC"}),
        ]
    )
    proxy = FilterProxyModel()
    proxy.setSourceModel(model)
    assert proxy.set_visible_oids(frozenset({20})) is True
    assert proxy._row_accept is not None
    assert list(proxy._row_accept) == [0, 1, 0]
    assert proxy.rowCount() == 1
    assert proxy.mapToSource(proxy.index(0, 0)).row() == 1
    assert proxy.set_visible_oids(frozenset({20})) is False
    assert proxy.set_visible_oids(None) is True
    assert proxy._row_accept is None
    assert proxy.rowCount() == 3
