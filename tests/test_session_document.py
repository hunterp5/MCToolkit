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
    from molmanager.session_codec import (
        dumps_session_document,
        expand_session_document,
        loads_session_bytes,
    )

    w = ChemicalTableApp()
    w.headers = ["ID_HIDDEN", "Structure", "SMILES", "Note"]
    w._table_model.set_headers(list(w.headers))
    w._table_model.append_row(0, {"SMILES": "CC", "Note": "ethane"})
    w.mols[0] = Chem.MolFromSmiles("CC")
    w.next_oid = 1

    doc = w._build_session_document()
    assert doc["version"] == 2
    assert doc["ids"] == [0]
    assert doc["data_headers"] == ["SMILES", "Note"]
    assert "rows" not in doc

    wire = dumps_session_document(doc)
    assert wire.startswith(b"\x1f\x8b")
    doc2 = expand_session_document(loads_session_bytes(wire))

    assert doc2["format"] == doc["format"]
    assert doc2["version"] == 2
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


def test_session_roundtrip_keeps_structure_independent_of_protonated(qapp):  # noqa: ARG001
    """Structure mols stay parent even when a Protonated column holds the ionized form."""
    from molmanager.utils import mol_to_canonical_smiles

    parent = Chem.MolFromSmiles("CCN")
    ionized = "CC[NH3+]"
    w = ChemicalTableApp()
    w.headers = ["ID_HIDDEN", "Structure", "Protonated"]
    w._table_model.set_headers(list(w.headers))
    w._table_model.append_row(0, {"Protonated": ionized})
    w.mols[0] = parent
    w._table_model.register_pixmap_column("Protonated")
    w.next_oid = 1

    doc = w._build_session_document()
    assert doc["structure_smiles"][0] == mol_to_canonical_smiles(parent)
    assert ionized in (doc["values"][0][0] if doc.get("values") else "")
    layout = doc.get("table_layout") or {}
    assert "Protonated" in (layout.get("pixmap_columns") or [])

    w2 = ChemicalTableApp()
    w2._apply_session_document(doc)
    assert 0 in w2.mols
    restored = mol_to_canonical_smiles(w2.mols[0])
    assert restored == mol_to_canonical_smiles(parent)
    assert "+" not in restored
    backing = w2._table_model.backing_value_for_row_header(0, "Protonated")
    assert ionized in backing
    assert w2._table_model.is_pixmap_data_column("Protonated")
    prot_col = w2.headers.index("Protonated")
    prot_idx = w2._table_model.index(0, prot_col)
    assert ionized in (w2._table_model.data(prot_idx, Qt.DisplayRole) or "")
    assert w2._mol_for_structure_row(0) is not None
    assert mol_to_canonical_smiles(w2._mol_for_structure_row(0)) == restored


def test_mol_for_structure_row_ignores_protonated_without_cached_mol(qapp):  # noqa: ARG001
    w = ChemicalTableApp()
    w.headers = ["ID_HIDDEN", "Structure", "Protonated"]
    w._table_model.set_headers(list(w.headers))
    w._table_model.append_row(0, {"Protonated": "CC[NH3+]"})
    w.mols = {}
    assert w._mol_for_structure_row(0) is None


def test_legacy_session_without_structure_smiles_does_not_use_protonated(qapp):  # noqa: ARG001
    """Older compact sessions omitted Structure identity; do not rebuild it from Protonated."""
    compact = {
        "format": "molmanager_session",
        "version": 2,
        "headers": ["ID_HIDDEN", "Structure", "Protonated"],
        "data_headers": ["Protonated"],
        "ids": [0],
        "values": [["CC[NH3+]"]],
        "next_oid": 1,
    }
    w = ChemicalTableApp()
    w._apply_session_document(compact)
    assert w._table_model.rowCount() == 1
    assert 0 not in w.mols or w.mols.get(0) is None
    assert w._mol_for_structure_row(0) is None
    renders, _ = w._build_render2d_tasks_in_table_order("Structure", 80, 80, None)
    assert renders == []
    backing = w._table_model.backing_value_for_row_header(0, "Protonated")
    assert "CC[NH3+]" in backing


def test_session_restore_render_tasks_keep_neutral_structure(qapp):  # noqa: ARG001
    from molmanager.utils import mol_to_canonical_smiles

    parent = Chem.MolFromSmiles("CCN")
    w = ChemicalTableApp()
    w.headers = ["ID_HIDDEN", "Structure", "Protonated"]
    w._table_model.set_headers(list(w.headers))
    w._table_model.append_row(0, {"Protonated": "CC[NH3+]"})
    w.mols[0] = parent
    w.next_oid = 1
    doc = w._build_session_document()

    w2 = ChemicalTableApp()
    w2._apply_session_document(doc)
    renders, _ = w2._build_render2d_tasks_in_table_order("Structure", 80, 80, None)
    assert renders
    restored = mol_to_canonical_smiles(renders[0][1])
    assert restored == mol_to_canonical_smiles(parent)
    assert "+" not in restored


def test_apply_legacy_v1_session_document(qapp):  # noqa: ARG001
    """Plain uncompressed version-1 documents still open."""
    w = ChemicalTableApp()
    v1 = {
        "format": "molmanager_session",
        "version": 1,
        "headers": ["ID_HIDDEN", "Structure", "SMILES", "Note"],
        "rows": [{"id": 3, "cells": {"SMILES": "CCO", "Note": "ethanol"}}],
        "next_oid": 4,
    }
    w._apply_session_document(v1)
    assert w._table_model.rowCount() == 1
    assert 3 in w.mols
    note_col = w.headers.index("Note")
    assert "ethanol" in (w._table_model.cell_text(0, note_col) or "")


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
    from molmanager.session_codec import expand_session_document

    expanded = expand_session_document(doc)
    assert expanded["rows"][0]["cells"][SOM_MAP_COLUMN] == "CCO"
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


def test_session_roundtrip_restores_mmp_ledger(qapp):  # noqa: ARG001
    from molmanager.mmp_analysis import MmpPair

    pair = MmpPair(
        oid_a=1,
        oid_b=2,
        smiles_a="Clc1ccccc1",
        smiles_b="Fc1ccccc1",
        activity_a=1.0,
        activity_b=0.5,
        delta_activity=-0.5,
        transform="Cl[*:1]>>F[*:1]",
        core="c1ccccc1",
        sidechain_a="Cl[*:1]",
        sidechain_b="F[*:1]",
    )
    w = ChemicalTableApp()
    w.headers = ["ID_HIDDEN", "Structure", "SMILES", "MMP_Partners"]
    w._table_model.set_headers(list(w.headers))
    w._table_model.append_row(1, {"SMILES": "Clc1ccccc1", "MMP_Partners": "2"})
    w.mols[1] = Chem.MolFromSmiles("Clc1ccccc1")
    w.next_oid = 3
    w._mmp_last_pairs = [pair]
    w._mmp_last_activity_column = "IC50"

    doc = w._build_session_document()
    assert doc["mmp_ledger"]["activity_column"] == "IC50"
    assert doc["mmp_ledger"]["pairs"][0]["oid_a"] == 1

    w2 = ChemicalTableApp()
    w2._apply_session_document(doc)
    restored = list(getattr(w2, "_mmp_last_pairs", None) or [])
    assert len(restored) == 1
    assert restored[0] == pair
    assert w2._mmp_last_activity_column == "IC50"


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
    assert int(w2.table.verticalHeader().defaultSectionSize()) == 88
    assert w2.table.isColumnHidden(0)
    # Deferred finish must not clobber the restored chrome.
    w2._finish_deferred_session_workspace_restore()
    qapp.processEvents()
    assert w2.table.isColumnHidden(mwi2)
    assert int(w2.table.verticalHeader().defaultSectionSize()) == 88
    w2.table.setColumnHidden(mwi2, False)
    assert int(w2.table.columnWidth(mwi2)) == 142
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


def test_session_roundtrip_keeps_side_by_side_layout(qapp, monkeypatch) -> None:  # noqa: ARG001
    from PyQt5.QtWidgets import QWidget

    from molmanager.ui.main_window.workspace_layout import LAYOUT_TABLE_SIDE, LAYOUT_TABLE_STACK

    class FakePlot(QWidget):
        def __init__(self, label: str = "a") -> None:
            super().__init__(None)
            self._label = label

        def collect_session_state(self) -> dict:
            return {"kind": "plotter", "x": "MW", "plot_title": self._label}

        def _sync_footer_chrome(self) -> None:
            return None

    restored: list[FakePlot] = []

    def fake_restore(self, spec):  # noqa: ARG001
        state = spec.get("state") if isinstance(spec, dict) else {}
        title = state.get("plot_title", "x") if isinstance(state, dict) else "x"
        w = FakePlot(str(title))
        restored.append(w)
        return w

    monkeypatch.setattr(ChemicalTableApp, "_restore_docked_plot_widget", fake_restore)
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
    w.apply_workspace_layout(LAYOUT_TABLE_SIDE)
    p0, p1 = w._workspace_layout.plot_panes()
    w._workspace_layout.dock_into_pane(p0, FakePlot("left"))
    w._workspace_layout.dock_into_pane(p1, FakePlot("right"))
    doc = w._build_session_document()
    assert doc["workspace_layout"]["layout_id"] == LAYOUT_TABLE_SIDE
    assert doc["docked_plots"]["layout_id"] == LAYOUT_TABLE_SIDE
    assert len(doc["docked_plots"]["panes"]) == 2

    # Simulate an older session missing workspace layout_id but keeping docked layout_id.
    doc_fallback = json.loads(json.dumps(doc))
    doc_fallback["workspace_layout"] = {
        "sizes": doc["workspace_layout"]["sizes"],
        "ratios": doc["workspace_layout"]["ratios"],
    }

    w2 = ChemicalTableApp()
    w2.apply_workspace_layout(LAYOUT_TABLE_STACK)  # wrong layout before open
    w2._apply_session_document(doc)
    assert w2._workspace_layout.layout_id == LAYOUT_TABLE_SIDE
    assert len(w2._workspace_layout.plot_panes()) == 2

    w3 = ChemicalTableApp()
    w3.apply_workspace_layout(LAYOUT_TABLE_STACK)
    w3._apply_session_document(doc_fallback)
    assert w3._workspace_layout.layout_id == LAYOUT_TABLE_SIDE
    assert len(w3._workspace_layout.plot_panes()) == 2


def test_session_roundtrip_restores_workspace_splitter(qapp, monkeypatch) -> None:  # noqa: ARG001
    from molmanager.ui.main_window.workspace_layout import LAYOUT_TABLE_SINGLE

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
    w.resize(1000, 600)
    w.show()
    qapp.processEvents()
    w.apply_workspace_layout(LAYOUT_TABLE_SINGLE)
    qapp.processEvents()
    mgr = w._workspace_layout
    outer = mgr._splitters[0]
    outer.setSizes([620, 380])
    qapp.processEvents()
    saved_sizes = [int(s) for s in outer.sizes()]
    assert len(saved_sizes) == 2 and sum(saved_sizes) > 0
    doc = w._build_session_document()
    ws = doc["workspace_layout"]
    assert ws["layout_id"] == LAYOUT_TABLE_SINGLE
    assert "ratios" in ws
    assert ws["sizes"]["splitter_0"] == saved_sizes
    saved_total = float(sum(saved_sizes))
    want_table = saved_sizes[0] / saved_total
    want_plot = saved_sizes[1] / saved_total

    w2 = ChemicalTableApp()
    w2.resize(1000, 600)
    w2.show()
    qapp.processEvents()
    w2._apply_session_document(doc)
    qapp.processEvents()
    w2._finish_deferred_session_workspace_restore()
    qapp.processEvents()
    restored = w2._workspace_layout.collect_splitter_sizes()
    assert restored["layout_id"] == LAYOUT_TABLE_SINGLE
    sizes = restored["sizes"]["splitter_0"]
    assert len(sizes) == 2
    total = sum(sizes) or 1
    assert abs(sizes[0] / total - want_table) < 0.08
    assert abs(sizes[1] / total - want_plot) < 0.08


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


def test_session_roundtrip_preserves_pane_title_and_active_page(qapp, monkeypatch) -> None:  # noqa: ARG001
    from PyQt5.QtWidgets import QWidget

    from molmanager.ui.main_window.workspace_layout import LAYOUT_TABLE_SINGLE

    class FakePlot(QWidget):
        def __init__(self, label: str) -> None:
            super().__init__(None)
            self._label = label

        def collect_session_state(self) -> dict:
            return {"kind": "plotter", "x": "MW", "plot_title": self._label}

        def _sync_footer_chrome(self) -> None:
            return None

    restored: list[FakePlot] = []

    def fake_restore(self, spec):  # noqa: ARG001
        state = spec.get("state") if isinstance(spec, dict) else {}
        title = state.get("plot_title", "x") if isinstance(state, dict) else "x"
        w = FakePlot(str(title))
        dt = spec.get("display_title") if isinstance(spec, dict) else None
        if isinstance(dt, str) and dt.strip():
            w._pane_display_title = dt.strip()
        restored.append(w)
        return w

    monkeypatch.setattr(ChemicalTableApp, "_restore_docked_plot_widget", fake_restore)
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
    w.apply_workspace_layout(LAYOUT_TABLE_SINGLE)
    pane = w._workspace_layout.plot_panes()[0]
    first = FakePlot("first")
    first._pane_display_title = "Custom pane"
    second = FakePlot("second")
    w._workspace_layout.dock_into_pane(pane, first)
    w._workspace_layout.dock_into_pane(pane, second)
    pane.set_plot_widgets(pane.plot_widgets(), current=1)
    doc = w._build_session_document()
    pane_spec = doc["docked_plots"]["panes"][0]
    assert pane_spec["current"] == 1
    assert pane_spec["plots"][0]["display_title"] == "Custom pane"
    assert len(pane_spec["plots"]) == 2

    w2 = ChemicalTableApp()
    w2._apply_session_document(doc)
    panes = w2._workspace_layout.plot_panes()
    assert panes[0].page_index() == 1
    docked = list(w2.iter_docked_plot_widgets())
    assert len(docked) == 2
    assert getattr(docked[0], "_pane_display_title", None) == "Custom pane"


def test_session_roundtrip_restores_floating_plots(qapp, monkeypatch) -> None:  # noqa: ARG001
    from PyQt5.QtWidgets import QDialog, QWidget

    from molmanager.ui.main_window.workspace_layout import LAYOUT_TABLE_SIDE, LAYOUT_TABLE_STACK

    class FakePlot(QWidget):
        def __init__(self, label: str = "a") -> None:
            super().__init__(None)
            self._label = label

        def collect_session_state(self) -> dict:
            return {"kind": "plotter", "x": "MW", "plot_title": self._label}

        def _sync_footer_chrome(self) -> None:
            return None

        def create_floating_dialog(self, parent_app):
            dlg = QDialog(parent_app)
            dlg._plot_widget = self
            dlg._force_close = False
            return dlg

    restored: list[FakePlot] = []

    def fake_restore(self, spec):  # noqa: ARG001
        state = spec.get("state") if isinstance(spec, dict) else {}
        title = state.get("plot_title", "x") if isinstance(state, dict) else "x"
        w = FakePlot(str(title))
        dt = spec.get("display_title") if isinstance(spec, dict) else None
        if isinstance(dt, str) and dt.strip():
            w._pane_display_title = dt.strip()
        restored.append(w)
        return w

    monkeypatch.setattr(ChemicalTableApp, "_restore_docked_plot_widget", fake_restore)
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
    w.apply_workspace_layout(LAYOUT_TABLE_SIDE)
    floater = FakePlot("float")
    floater._pane_display_title = "Floating A"
    dlg = floater.create_floating_dialog(w)
    w._register_floating_result_dialog(dlg)
    doc = w._build_session_document()
    assert doc["workspace_layout"]["layout_id"] == LAYOUT_TABLE_SIDE
    assert len(doc["floating_plots"]) == 1
    assert doc["floating_plots"][0]["display_title"] == "Floating A"

    w2 = ChemicalTableApp()
    w2.apply_workspace_layout(LAYOUT_TABLE_STACK)
    w2._apply_session_document(doc)
    assert w2._workspace_layout.layout_id == LAYOUT_TABLE_SIDE
    hosts = list(w2._iter_floating_plot_hosts())
    assert len(hosts) == 1
    panel = w2._floating_plot_panel(hosts[0])
    assert getattr(panel, "_pane_display_title", None) == "Floating A"


def test_session_restore_dispatches_analysis_plot_kind(qapp, monkeypatch) -> None:  # noqa: ARG001
    from PyQt5.QtWidgets import QWidget

    from molmanager.ui.main_window.workspace_layout import LAYOUT_TABLE_SINGLE

    class FakeSali(QWidget):
        def collect_session_state(self) -> dict:
            return {
                "kind": "sali_map",
                "activity_column": "pIC50",
                "fp_choice": "Morgan",
                "metric": "Tanimoto",
                "points": [],
                "color": "(none)",
            }

        def _sync_footer_chrome(self) -> None:
            return None

    created: list[dict] = []

    def fake_sali_from_session(cls, parent_app, state):  # noqa: ARG001,N805
        created.append(dict(state or {}))
        w = FakeSali()
        w._restored_state = state
        return w

    from molmanager.ui import sali_map

    monkeypatch.setattr(
        sali_map.SaliMapPanel, "from_session_state", classmethod(fake_sali_from_session)
    )
    monkeypatch.setattr(
        ChemicalTableApp,
        "_try_auto_render_all_structures_after_ingest",
        lambda self: False,
    )

    w = ChemicalTableApp()
    w.headers = ["ID_HIDDEN", "Structure", "SMILES", "pIC50"]
    w._table_model.set_headers(list(w.headers))
    w._table_model.append_row(0, {"SMILES": "CC", "pIC50": "7"})
    w.mols[0] = Chem.MolFromSmiles("CC")
    w.next_oid = 1
    w.apply_workspace_layout(LAYOUT_TABLE_SINGLE)
    w._workspace_layout.dock_into_pane(w._workspace_layout.plot_panes()[0], FakeSali())
    doc = w._build_session_document()
    assert doc["docked_plots"]["panes"][0]["plots"][0]["kind"] == "sali_map"

    w2 = ChemicalTableApp()
    w2._apply_session_document(doc)
    assert created
    assert created[0].get("activity_column") == "pIC50"
    assert list(w2.iter_docked_plot_widgets())
