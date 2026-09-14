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

"""Tests for CompoundTableModel (no full window required)."""

from __future__ import annotations

import pytest
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QPixmap

from molmanager.ui.compound_table_model import CompoundTableModel


@pytest.fixture()
def model(qapp):  # noqa: ARG001 — ensures QApplication exists for Qt types
    headers = ["ID_HIDDEN", "Structure", "SMILES", "MW"]
    m = CompoundTableModel(headers)
    return m


def test_append_row_and_oid_index(model: CompoundTableModel):
    model.append_row(10, {"SMILES": "CC", "MW": "30.07"})
    assert model.rowCount() == 1
    assert model.row_oid(0) == 10
    assert model.logical_row_for_oid(10) == 0
    assert (model.cell_text(0, model._headers.index("SMILES")) or "") == "CC"


def test_oid_and_row_header_centered(model: CompoundTableModel):
    model.append_row(42, {"SMILES": "C", "MW": "16"})
    oid_idx = model.index(0, 0)
    assert model.data(oid_idx, Qt.DisplayRole) == "42"
    assert model.data(oid_idx, Qt.TextAlignmentRole) == int(Qt.AlignCenter)
    assert model.headerData(0, Qt.Vertical, Qt.TextAlignmentRole) == int(Qt.AlignCenter)
    assert model.headerData(0, Qt.Vertical, Qt.DisplayRole) == "1"


def test_set_cell_text_updates_value(model: CompoundTableModel):
    model.append_row(1, {"SMILES": "C", "MW": "16"})
    model.set_cell_text(1, "MW", "16.043")
    sci = model._headers.index("SMILES")
    mwi = model._headers.index("MW")
    assert model.cell_text(0, mwi) == "16.043"
    assert model.cell_text(0, sci) == "C"


def test_set_cell_text_batch_updates_row(model: CompoundTableModel):
    model.append_row(7, {"SMILES": "CC", "MW": "30"})
    model.set_cell_text_batch(7, {"SMILES": "CCC", "MW": "44.1"})
    sci = model._headers.index("SMILES")
    mwi = model._headers.index("MW")
    assert model.cell_text(0, sci) == "CCC"
    assert model.cell_text(0, mwi) == "44.1"


def test_set_backing_text_updates_pixmap_column(qapp):  # noqa: ARG001
    model = CompoundTableModel(["ID_HIDDEN", "Structure", "Protonated"])
    model.append_row(1, {"Protonated": "CC(=O)O"})
    model.register_pixmap_column("Protonated")
    prot = model._headers.index("Protonated")
    assert model.cell_text(0, prot) == ""
    assert model.backing_value_for_row_header(0, "Protonated") == "CC(=O)O"
    model.set_cell_text(1, "Protonated", "CCO")
    assert model.backing_value_for_row_header(0, "Protonated") == "CC(=O)O"
    model.set_backing_text(1, "Protonated", "CCO")
    assert model.backing_value_for_row_header(0, "Protonated") == "CCO"
    assert model.cell_text(0, prot) == ""
    idx = model.index(0, prot)
    assert model.data(idx, Qt.DisplayRole) == "CCO"
    assert model.data(idx, Qt.DecorationRole) is None
    pix = QPixmap(16, 16)
    pix.fill(QColor(255, 255, 255))
    model.set_column_pixmap(1, "Protonated", pix)
    assert model.data(idx, Qt.DisplayRole) == ""
    assert model.data(idx, Qt.DecorationRole) is not None
    assert model.backing_value_for_row_header(0, "Protonated") == "CCO"


def test_numeric_bounds_by_column(model: CompoundTableModel):
    model.append_row(0, {"SMILES": "C", "MW": "10"})
    model.append_row(1, {"SMILES": "CC", "MW": "20"})
    bounds = model.numeric_bounds_by_column()
    assert "MW" in bounds
    assert bounds["MW"]["min"] == 10.0
    assert bounds["MW"]["max"] == 20.0
    assert bounds["MW"]["is_int"] is True


def test_numeric_bounds_mixed_int_and_float_not_integer_column(model: CompoundTableModel):
    model.append_row(0, {"SMILES": "C", "MW": "10"})
    model.append_row(1, {"SMILES": "CC", "MW": "20.5"})
    bounds = model.numeric_bounds_by_column()
    assert bounds["MW"]["min"] == 10.0
    assert bounds["MW"]["max"] == 20.5
    assert bounds["MW"]["is_int"] is False


def test_numeric_bounds_incremental_edit_matches_full_rescan(model: CompoundTableModel):
    model.append_row(0, {"SMILES": "C", "MW": "10", "LogP": "1"})
    model.append_row(1, {"SMILES": "CC", "MW": "20", "LogP": "2"})
    model.numeric_bounds_by_column()
    model.set_cell_text(0, "MW", "15")
    b1 = model.numeric_bounds_by_column()
    model._invalidate_numeric_bounds_all()
    b2 = model.numeric_bounds_by_column()
    assert b1 == b2
    assert b1["MW"] == {"min": 15.0, "max": 20.0, "is_int": True}


def test_column_text_by_oid(model: CompoundTableModel):
    model.append_row(1, {"SMILES": "C", "MW": "12"})
    model.append_row(2, {"SMILES": "CC", "MW": "30"})
    snap = model.column_text_by_oid("MW")
    assert snap == {1: "12", 2: "30"}


def test_duplicate_column_at_bulk_copy(model: CompoundTableModel):
    model.append_row(1, {"SMILES": "C", "MW": "10", "LogP": "1"})
    model.append_row(2, {"SMILES": "CC", "MW": "20", "LogP": "2"})
    model.duplicate_column_at(model.columnCount(), "MW (Copy)", model._headers.index("MW"))
    mwi = model._headers.index("MW (Copy)")
    assert model.cell_text(0, mwi) == "10"
    assert model.cell_text(1, mwi) == "20"


def test_duplicate_column_at_copies_pixmap_column(qapp):  # noqa: ARG001
    model = CompoundTableModel(["ID_HIDDEN", "Structure", "Protonated"])
    model.append_row(1, {"Protonated": "CCO"})
    model.register_pixmap_column("Protonated")
    pix = QPixmap(8, 8)
    pix.fill(QColor(255, 255, 255))
    model.set_column_pixmap(1, "Protonated", pix)
    dest = model.columnCount()
    model.duplicate_column_at(dest, "Protonated (Copy)", model._headers.index("Protonated"))
    assert model.is_pixmap_data_column("Protonated (Copy)")
    assert model.backing_value_for_row_header(0, "Protonated (Copy)") == "CCO"
    copied = model.column_pixmap_copy(1, "Protonated (Copy)")
    assert copied is not None and not copied.isNull()


def test_remove_column_at_keeps_other_bounds_cache(model: CompoundTableModel):
    for i in range(50):
        model.append_row(i, {"SMILES": "C", "MW": str(10 + i)})
    model.insert_column_at(model.columnCount(), "Extra", None)
    for i in range(50):
        model.set_cell_text(i, model._headers.index("Extra"), str(float(i)))
    cache = model.numeric_bounds_by_column()
    mw_meta = cache["MW"]
    extra_col = model._headers.index("Extra")
    model.remove_column_at(extra_col)
    assert model._numeric_bounds_cache is not None
    assert "Extra" not in model._numeric_bounds_cache
    assert model._numeric_bounds_cache["MW"] == mw_meta


def test_insert_column_at_marks_only_new_bounds_dirty(model: CompoundTableModel):
    for i in range(50):
        model.append_row(i, {"SMILES": "C", "MW": str(10 + i)})
    model.numeric_bounds_by_column()
    model.insert_column_at(model.columnCount(), "LogP", None)
    assert model._numeric_bounds_cache is not None
    assert "LogP" in (model._numeric_bounds_dirty_cols or set())


def test_refresh_numeric_bounds_for_headers_scans_only_target(model: CompoundTableModel) -> None:
    for i in range(40):
        model.append_row(i, {"SMILES": "C", "MW": str(10 + i)})
    model.insert_column_at(model.columnCount(), "Extra", None)
    for i in range(40):
        model.set_cell_text(i, "Extra", str(float(i)))
    full = model.numeric_bounds_by_column()
    mw_before = full["MW"]
    model.refresh_numeric_bounds_for_headers(["Extra"])
    assert model._numeric_bounds_cache is not None
    assert model._numeric_bounds_cache["MW"] == mw_before
    assert model._numeric_bounds_cache["Extra"]["min"] == 0.0


def test_fill_column_from_oid_map_sets_default(model: CompoundTableModel) -> None:
    model.append_row(1, {"SMILES": "C", "MW": "1"})
    model.append_row(2, {"SMILES": "CC", "MW": "2"})
    model.insert_column_at(model.columnCount(), "Score", None)
    model.fill_column_from_oid_map("Score", {2: "0.9"}, default="N/A")
    assert model.cell_text(0, model._headers.index("Score")) == "N/A"
    assert model.cell_text(1, model._headers.index("Score")) == "0.9"


def test_apply_columns_values_bulk(model: CompoundTableModel):
    model.append_row(1, {"SMILES": "C", "MW": "10"})
    model.append_row(2, {"SMILES": "CC", "MW": "20"})
    model.insert_column_at(model.columnCount(), "LogP", None)
    model.apply_columns_values_bulk(
        ["MW", "LogP"],
        [(1, {"MW": "11", "LogP": "1.1"}), (2, {"MW": "22", "LogP": "2.2"})],
    )
    mwi = model._headers.index("MW")
    lpi = model._headers.index("LogP")
    assert model.cell_text(0, mwi) == "11"
    assert model.cell_text(1, mwi) == "22"
    assert model.cell_text(0, lpi) == "1.1"


def test_set_column_text_by_oids(model: CompoundTableModel):
    model.append_row(10, {"SMILES": "C", "MW": "1"})
    model.append_row(11, {"SMILES": "CC", "MW": "2"})
    model.set_column_text_by_oids("MW", [(10, "3"), (11, "4")])
    mwi = model._headers.index("MW")
    assert model.cell_text(0, mwi) == "3"
    assert model.cell_text(1, mwi) == "4"


def test_numeric_gradient_column_coloring(model: CompoundTableModel):
    model.append_row(10, {"SMILES": "C", "MW": "10"})
    model.append_row(11, {"SMILES": "CC", "MW": "20"})
    model.set_column_color_numeric_gradient(
        "MW",
        min_value=10.0,
        max_value=20.0,
        low_color=QColor(0, 0, 255),
        high_color=QColor(255, 0, 0),
        alpha=120,
    )
    idx_low = model.index(0, model._headers.index("MW"))
    idx_high = model.index(1, model._headers.index("MW"))
    c_low = model.data(idx_low, Qt.BackgroundRole)
    c_high = model.data(idx_high, Qt.BackgroundRole)
    assert isinstance(c_low, QColor)
    assert isinstance(c_high, QColor)
    assert c_low.alpha() == 120
    assert c_high.alpha() == 120
    assert c_low != c_high


def test_categorical_column_coloring_is_deterministic(model: CompoundTableModel):
    model.append_row(10, {"SMILES": "A", "MW": "1"})
    model.append_row(11, {"SMILES": "B", "MW": "2"})
    model.append_row(12, {"SMILES": "A", "MW": "3"})
    model.set_column_color_categorical("SMILES", alpha=100)
    sci = model._headers.index("SMILES")
    c1 = model.data(model.index(0, sci), Qt.BackgroundRole)
    c2 = model.data(model.index(1, sci), Qt.BackgroundRole)
    c3 = model.data(model.index(2, sci), Qt.BackgroundRole)
    assert isinstance(c1, QColor)
    assert isinstance(c2, QColor)
    assert isinstance(c3, QColor)
    assert c1.alpha() == 100 and c2.alpha() == 100 and c3.alpha() == 100
    assert c1 == c3
    assert c1 != c2


def test_three_point_gradient_column_coloring(model: CompoundTableModel):
    model.append_row(10, {"SMILES": "A", "MW": "0"})
    model.append_row(11, {"SMILES": "B", "MW": "50"})
    model.append_row(12, {"SMILES": "C", "MW": "100"})
    model.set_column_color_three_point_gradient(
        "MW",
        min_value=0.0,
        mid_value=50.0,
        max_value=100.0,
        low_color=QColor(0, 0, 255),
        mid_color=QColor(255, 255, 255),
        high_color=QColor(255, 0, 0),
        alpha=110,
    )
    mwi = model._headers.index("MW")
    low = model.data(model.index(0, mwi), Qt.BackgroundRole)
    mid = model.data(model.index(1, mwi), Qt.BackgroundRole)
    high = model.data(model.index(2, mwi), Qt.BackgroundRole)
    assert isinstance(low, QColor) and isinstance(mid, QColor) and isinstance(high, QColor)
    assert low.alpha() == 110 and mid.alpha() == 110 and high.alpha() == 110
    assert low != mid and mid != high


def test_export_restore_column_color_rules(model: CompoundTableModel):
    model.append_row(1, {"SMILES": "A", "MW": "1"})
    model.append_row(2, {"SMILES": "B", "MW": "9"})
    model.set_column_color_three_point_gradient(
        "MW",
        min_value=1.0,
        mid_value=5.0,
        max_value=9.0,
        low_color=QColor(0, 0, 255),
        mid_color=QColor(255, 255, 255),
        high_color=QColor(255, 0, 0),
        alpha=101,
    )
    saved = model.export_column_color_rules()
    model.clear_column_coloring("MW")
    model.restore_column_color_rules(saved)
    restored = model.column_color_rule_spec("MW")
    assert restored is not None
    assert restored.get("mode") == "numeric3"
    assert int(restored.get("alpha", 0)) == 101


def test_remove_rows_by_oids_bulk(model: CompoundTableModel):
    for oid, mw in ((1, "10"), (2, "20"), (3, "30")):
        model.append_row(oid, {"SMILES": "C", "MW": mw})
    removed = model.remove_rows_by_oids(frozenset({1, 3}))
    assert removed == 2
    assert model.rowCount() == 1
    assert model.row_oid(0) == 2
    assert model.logical_row_for_oid(1) < 0
    assert model.logical_row_for_oid(3) < 0


def test_remove_row_clears_structure_png_store(model: CompoundTableModel):
    from molmanager.structure_render_store import StructureRenderStore

    model.append_row(5, {"SMILES": "CC", "MW": "30"})
    store = StructureRenderStore(max_decoded_pixmaps=8)
    store.ingest_png(5, b"png-5")
    model.set_structure_png_store(store)
    assert store.has_png(5)
    model.remove_row_at(0)
    assert not store.has_png(5)


def test_insert_rows_batch_restores_order(model: CompoundTableModel):
    model.append_row(10, {"SMILES": "A", "MW": "1"})
    model.append_row(30, {"SMILES": "C", "MW": "3"})
    model.remove_rows_by_oids(frozenset({10}))
    model.insert_rows_batch([(0, 10, {"SMILES": "A", "MW": "1"})])
    assert model.rowCount() == 2
    assert model.row_oid(0) == 10
    assert model.row_oid(1) == 30
    assert model.cell_text(0, model._headers.index("SMILES")) == "A"
