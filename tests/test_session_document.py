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

"""Session document build/apply round-trip (requires Qt + main window)."""

from __future__ import annotations

import json

import pytest
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor
from rdkit import Chem

from molmanager.ui.main_window import ChemicalTableApp


@pytest.fixture(autouse=True)
def _skip_session_auto_render(monkeypatch) -> None:
    """Session tests restore table chrome; skip the async 2D render that hangs teardown."""
    monkeypatch.setattr(
        ChemicalTableApp,
        "_try_auto_render_all_structures_after_ingest",
        lambda self: False,
    )


def test_session_document_json_roundtrip_preserves_keys(qapp):  # noqa: ARG001
    w = ChemicalTableApp()
    w.headers = ["ID_HIDDEN", "Structure", "SMILES", "Note"]
    w._table_model.set_headers(list(w.headers))
    w._table_model.append_row(0, {"SMILES": "CC", "Note": "ethane"})
    w.mols[0] = Chem.MolFromSmiles("CC")
    w.next_oid = 1

    doc = w._build_session_document()
    wire = json.dumps(doc)
    doc2 = json.loads(wire)

    assert doc2["format"] == doc["format"]
    assert doc2["version"] == doc["version"]
    assert doc2["headers"] == w.headers
    assert len(doc2["rows"]) == 1
    assert doc2["rows"][0]["id"] == 0
    assert "CC" in (doc2["rows"][0]["cells"].get("SMILES") or "")
    assert "table_layout" in doc2
    assert "docked_plots" in doc2
    assert "column_widths" in doc2["table_layout"]
    assert "hidden_columns" in doc2["table_layout"]


def test_apply_session_document_restores_row(qapp):  # noqa: ARG001
    w = ChemicalTableApp()
    w.headers = ["ID_HIDDEN", "Structure", "SMILES", "Note"]
    w._table_model.set_headers(list(w.headers))
    w._table_model.append_row(0, {"SMILES": "CC", "Note": "ethane"})
    w.mols[0] = Chem.MolFromSmiles("CC")
    w.next_oid = 1

    doc = w._build_session_document()

    w2 = ChemicalTableApp()
    w2._apply_session_document(doc)

    assert w2.headers[:4] == ["ID_HIDDEN", "Structure", "SMILES", "Note"]
    assert w2._table_model.rowCount() == 1
    smi_col = w2.headers.index("SMILES")
    assert "CC" in (w2._table_model.cell_text(0, smi_col) or "")
    assert 0 in w2.mols


def test_session_document_roundtrip_restores_column_coloring(qapp):  # noqa: ARG001
    w = ChemicalTableApp()
    w.headers = ["ID_HIDDEN", "Structure", "SMILES", "MW"]
    w._table_model.set_headers(list(w.headers))
    w._table_model.append_row(0, {"SMILES": "CC", "MW": "10"})
    w._table_model.append_row(1, {"SMILES": "CCC", "MW": "20"})
    w._table_model.set_column_color_three_point_gradient(
        "MW",
        min_value=10.0,
        mid_value=15.0,
        max_value=20.0,
        low_color=QColor(0, 0, 255),
        mid_color=QColor(255, 255, 255),
        high_color=QColor(255, 0, 0),
        alpha=111,
    )
    doc = w._build_session_document()

    w2 = ChemicalTableApp()
    w2._apply_session_document(doc)
    mwi = w2.headers.index("MW")
    c0 = w2._table_model.data(w2._table_model.index(0, mwi), Qt.BackgroundRole)
    c1 = w2._table_model.data(w2._table_model.index(1, mwi), Qt.BackgroundRole)
    assert c0 is not None and c1 is not None
    assert c0.alpha() == 111 and c1.alpha() == 111
    spec = w2._table_model.column_color_rule_spec("MW")
    assert isinstance(spec, dict)
    assert spec.get("mode") == "numeric3"


def test_session_document_roundtrip_restores_logarithmic_columns(qapp):  # noqa: ARG001
    w = ChemicalTableApp()
    w.headers = ["ID_HIDDEN", "Structure", "SMILES", "MW"]
    w._table_model.set_headers(list(w.headers))
    w._table_model.append_row(0, {"SMILES": "CC", "MW": "2"})
    w._logarithmic_columns = {"MW"}
    doc = w._build_session_document()
    assert doc["logarithmic_columns"] == ["MW"]

    w2 = ChemicalTableApp()
    w2._apply_session_document(doc)
    assert "MW" in w2._logarithmic_columns


def test_session_roundtrip_restores_som_maps(qapp) -> None:  # noqa: ARG001
    from molmanager.som_prediction import (
        SOM_MAP_COLUMN,
        SOM_PROB_COLUMN,
        SOM_SITES_COLUMN,
        SomAtomHit,
    )
    from molmanager.ui.som_browser import SomBrowseRecord, records_from_table

    w = ChemicalTableApp()
    w.headers = [
        "ID_HIDDEN",
        "Structure",
        "SMILES",
        SOM_MAP_COLUMN,
        SOM_SITES_COLUMN,
        SOM_PROB_COLUMN,
    ]
    w._table_model.set_headers(list(w.headers))
    w._table_model.append_row(
        7,
        {
            "SMILES": "CCO",
            SOM_MAP_COLUMN: "CCO",
            SOM_SITES_COLUMN: "0",
            SOM_PROB_COLUMN: "0:0.91; 1:0.12",
        },
    )
    w.mols[7] = Chem.MolFromSmiles("CCO")
    w.next_oid = 8
    w._table_model.register_pixmap_column(SOM_MAP_COLUMN)
    w._som_browse_records = [
        SomBrowseRecord(
            oid=7,
            smiles="CCO",
            atoms=(SomAtomHit(0, 0.91, True), SomAtomHit(1, 0.12, False)),
        )
    ]
    assert w._table_model.cell_text(0, w.headers.index(SOM_MAP_COLUMN)) == ""
    assert w._table_model.backing_value_for_row_header(0, SOM_MAP_COLUMN) == "CCO"

    doc = w._build_session_document()
    assert doc["rows"][0]["cells"][SOM_MAP_COLUMN] == "CCO"
    assert doc["som_browse"][0]["oid"] == 7
    assert doc["som_browse"][0]["smiles"] == "CCO"
    assert doc["som_browse"][0]["atoms"][0]["atom_id"] == 0

    w2 = ChemicalTableApp()
    w2._apply_session_document(doc)
    assert w2._table_model.is_pixmap_data_column(SOM_MAP_COLUMN)
    pm = w2._table_model.column_pixmap_copy(7, SOM_MAP_COLUMN)
    assert pm is not None and not pm.isNull()
    assert w2._table_model.backing_value_for_row_header(0, SOM_MAP_COLUMN) == "CCO"
    recs = list(getattr(w2, "_som_browse_records", None) or ())
    assert recs and recs[0].oid == 7 and recs[0].atoms[0].is_som
    table_recs = records_from_table(w2)
    assert table_recs and table_recs[0].smiles == "CCO"


def test_session_roundtrip_restores_ionization_cache(qapp, monkeypatch) -> None:  # noqa: ARG001
    from molmanager import microstate_cache as mc
    from molmanager.ionization import (
        PicklableIonizationEnsemble,
        PicklableIonizationMicrostate,
        microstates_for_mol,
    )
    from molmanager.workers.structure_grouping import structure_key

    mc.clear()
    try:
        mol = Chem.MolFromSmiles("CCO")
        assert mol is not None
        key = structure_key(mol)
        fake = PicklableIonizationEnsemble(
            microstates=(PicklableIonizationMicrostate("CCO", 0, 0.0, mol.ToBinary()),),
            macro_pkas=(15.9,),
        )
        w = ChemicalTableApp()
        w.headers = ["ID_HIDDEN", "Structure", "SMILES"]
        w._table_model.set_headers(list(w.headers))
        w._table_model.append_row(0, {"SMILES": "CCO"})
        w.mols[0] = mol
        w.next_oid = 1
        mc.store(key, fake)

        doc = w._build_session_document()
        assert doc["ionization_sidecar"]["entries"][key]["macro_pkas"] == [15.9]
        wire = json.dumps(doc)
        doc2 = json.loads(wire)

        w2 = ChemicalTableApp()
        w2._apply_session_document(doc2)
        hit, cached = mc.lookup(key)
        assert hit is True
        assert cached.macro_pkas == (15.9,)

        def boom(_m):
            raise AssertionError("Uni-pKa should not run after session restore")

        monkeypatch.setattr("molmanager.ionization.predict_ionization_ensemble", boom)
        out = microstates_for_mol(Chem.MolFromSmiles("CCO"))
        assert out.macro_pkas == (15.9,)
    finally:
        mc.clear()


def test_apply_session_document_auto_renders_like_file_ingest(qapp, monkeypatch):  # noqa: ARG001
    """Opening a session queues the same auto 2D render used after file ingest."""
    calls: list[int] = []

    w = ChemicalTableApp()
    w.headers = ["ID_HIDDEN", "Structure", "SMILES"]
    w._table_model.set_headers(list(w.headers))
    w._table_model.append_row(0, {"SMILES": "CCO"})
    w.mols[0] = Chem.MolFromSmiles("CCO")
    w.next_oid = 1
    doc = w._build_session_document()

    w2 = ChemicalTableApp()

    def fake_auto_render(self) -> bool:
        if self is w2:
            calls.append(self._table_model.rowCount())
        return False

    monkeypatch.setattr(
        ChemicalTableApp,
        "_try_auto_render_all_structures_after_ingest",
        fake_auto_render,
    )
    w2._apply_session_document(doc)
    qapp.processEvents()

    assert calls == [1]


def test_session_roundtrip_restores_table_layout(qapp, monkeypatch) -> None:  # noqa: ARG001
    monkeypatch.setattr(
        ChemicalTableApp,
        "_try_auto_render_all_structures_after_ingest",
        lambda self: False,
    )
    w = ChemicalTableApp()
    w.headers = ["ID_HIDDEN", "Structure", "SMILES", "MW"]
    w._table_model.set_headers(list(w.headers))
    w._table_model.append_row(0, {"SMILES": "CC", "MW": "30"})
    w.mols[0] = Chem.MolFromSmiles("CC")
    w.next_oid = 1
    w.resize(900, 400)
    w.show()
    qapp.processEvents()
    mwi = w.headers.index("MW")
    w.table.setColumnWidth(mwi, 142)
    w.table.setColumnHidden(mwi, True)
    w.table.verticalHeader().setDefaultSectionSize(88)
    doc = w._build_session_document()
    layout = doc["table_layout"]
    assert layout["column_widths"]["MW"] == 142
    assert layout["default_row_height"] == 88
    assert "MW" in layout["hidden_columns"]
    assert "ID_HIDDEN" not in layout["hidden_columns"]

    w2 = ChemicalTableApp()
    w2.resize(900, 400)
    w2.show()
    qapp.processEvents()
    w2._apply_session_document(doc)
    qapp.processEvents()
    mwi2 = w2.headers.index("MW")
    assert w2.table.isColumnHidden(mwi2)
    w2.table.setColumnHidden(mwi2, False)
    assert int(w2.table.columnWidth(mwi2)) == 142
    assert int(w2.table.verticalHeader().defaultSectionSize()) == 88
    assert w2.table.isColumnHidden(0)


def test_session_roundtrip_restores_docked_plotter(qapp, monkeypatch) -> None:  # noqa: ARG001
    from PyQt5.QtWidgets import QWidget

    from molmanager.ui.main_window.workspace_layout import LAYOUT_TABLE_SINGLE

    class FakePlot(QWidget):
        def __init__(self, state: dict | None = None) -> None:
            super().__init__(None)
            self._state = state or {
                "kind": "plotter",
                "x": "MW",
                "y": "LogP",
                "plot_title": "MW vs LogP",
                "color": "MW",
            }

        def collect_session_state(self) -> dict:
            return dict(self._state)

        def _sync_footer_chrome(self) -> None:
            return None

    restored: list[FakePlot] = []

    def fake_restore(self, spec):  # noqa: ARG001
        state = spec.get("state") if isinstance(spec, dict) else None
        w = FakePlot(state if isinstance(state, dict) else None)
        restored.append(w)
        return w

    monkeypatch.setattr(ChemicalTableApp, "_restore_docked_plot_widget", fake_restore)
    monkeypatch.setattr(
        ChemicalTableApp,
        "_try_auto_render_all_structures_after_ingest",
        lambda self: False,
    )

    w = ChemicalTableApp()
    w.headers = ["ID_HIDDEN", "Structure", "SMILES", "MW", "LogP"]
    w._table_model.set_headers(list(w.headers))
    w._table_model.append_row(0, {"SMILES": "CC", "MW": "30", "LogP": "1.2"})
    w.mols[0] = Chem.MolFromSmiles("CC")
    w.next_oid = 1
    w.apply_workspace_layout(LAYOUT_TABLE_SINGLE)
    pane = w._workspace_layout.plot_panes()[0]
    w._workspace_layout.dock_into_pane(pane, FakePlot())
    doc = w._build_session_document()
    panes = doc["docked_plots"]["panes"]
    assert panes
    assert panes[0]["plots"][0]["state"]["x"] == "MW"
    assert panes[0]["plots"][0]["state"]["y"] == "LogP"
    assert panes[0]["plots"][0]["state"]["plot_title"] == "MW vs LogP"
    wire = json.dumps(doc)
    doc2 = json.loads(wire)

    w2 = ChemicalTableApp()
    w2._apply_session_document(doc2)
    assert restored
    docked = list(w2.iter_docked_plot_widgets())
    assert docked
    assert docked[0] is restored[0]
    assert restored[0]._state["x"] == "MW"
    assert restored[0]._state["plot_title"] == "MW vs LogP"


def test_session_open_clears_previous_docked_plots(qapp, monkeypatch) -> None:  # noqa: ARG001
    from PyQt5.QtWidgets import QWidget

    from molmanager.ui.main_window.workspace_layout import LAYOUT_TABLE_SINGLE

    class FakePlot(QWidget):
        def collect_session_state(self) -> dict:
            return {"kind": "plotter", "x": "MW"}

        def _sync_footer_chrome(self) -> None:
            return None

    monkeypatch.setattr(
        ChemicalTableApp,
        "_restore_docked_plot_widget",
        lambda self, spec: FakePlot(),  # noqa: ARG005
    )
    monkeypatch.setattr(
        ChemicalTableApp,
        "_try_auto_render_all_structures_after_ingest",
        lambda self: False,
    )

    leftover_host = ChemicalTableApp()
    leftover_host.headers = ["ID_HIDDEN", "Structure", "SMILES", "MW"]
    leftover_host._table_model.set_headers(list(leftover_host.headers))
    leftover_host._table_model.append_row(0, {"SMILES": "CC", "MW": "30"})
    leftover_host.mols[0] = Chem.MolFromSmiles("CC")
    leftover_host.next_oid = 1
    leftover_host.apply_workspace_layout(LAYOUT_TABLE_SINGLE)
    leftover_host._workspace_layout.dock_into_pane(
        leftover_host._workspace_layout.plot_panes()[0], FakePlot()
    )
    assert list(leftover_host.iter_docked_plot_widgets())

    source = ChemicalTableApp()
    source.headers = ["ID_HIDDEN", "Structure", "SMILES"]
    source._table_model.set_headers(list(source.headers))
    source._table_model.append_row(0, {"SMILES": "CCO"})
    source.mols[0] = Chem.MolFromSmiles("CCO")
    source.next_oid = 1
    doc = source._build_session_document()
    assert not doc["docked_plots"]["panes"]

    leftover_host._apply_session_document(doc)
    qapp.processEvents()
    assert list(leftover_host.iter_docked_plot_widgets()) == []
