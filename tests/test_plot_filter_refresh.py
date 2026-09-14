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

"""Open plots follow the table filter's visible row set."""

from __future__ import annotations

from rdkit import Chem

from PyQt5.QtWidgets import QWidget

from molmanager.dimensionality_reduction import (
    DimensionReductionResult,
    subset_dimension_reduction_result,
)
from molmanager.ui.main_window import ChemicalTableApp
from molmanager.ui.plot_table_sync import visible_oids_for_plot
from molmanager.ui.widgets import FilterCard


def _setup_two_row_mw_table(w: ChemicalTableApp) -> None:
    w.headers = ["ID_HIDDEN", "Structure", "SMILES", "MW"]
    w._table_model.set_headers(list(w.headers))
    w._table_model.append_row(0, {"SMILES": "C", "MW": "10"})
    w._table_model.append_row(1, {"SMILES": "CC", "MW": "50"})
    w.mols[0] = Chem.MolFromSmiles("C")
    w.mols[1] = Chem.MolFromSmiles("CC")
    w.next_oid = 2
    w.calculate_global_bounds()
    card = FilterCard(list(w.global_bounds.keys()), w, initial_property="MW")
    card.restore_state("MW", 5.0, 25.0)
    w.filters = [card]


class _FakePlotDialog(QWidget):
    def __init__(self, widget) -> None:
        super().__init__()
        self._plot_widget = widget


class _CountingPlotHost(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    def _schedule_plot(self) -> None:
        self.calls += 1


def test_visible_oids_follow_numeric_filter(qapp):  # noqa: ARG001
    w = ChemicalTableApp()
    _setup_two_row_mw_table(w)
    assert w._visible_oids_set() is None
    w._apply_filters_impl_sync(None)
    assert w._visible_oids_set() == frozenset({0})
    assert visible_oids_for_plot(w) == frozenset({0})
    w.close()


def test_visible_source_rows_follow_filter(qapp):  # noqa: ARG001
    w = ChemicalTableApp()
    _setup_two_row_mw_table(w)
    assert w._visible_source_row_indices() is None
    w._apply_filters_impl_sync(None)
    assert w._visible_source_row_indices() == [0]
    w.close()


def test_replot_walks_plot_hosts_not_just_selection_views(qapp):  # noqa: ARG001
    w = ChemicalTableApp()
    host = _CountingPlotHost()
    w._plot_dialogs = [_FakePlotDialog(host)]
    w._replot_active_plots()
    assert host.calls == 1
    w.close()


def test_structure_paint_data_change_does_not_schedule_replot(qapp):  # noqa: ARG001
    w = ChemicalTableApp()
    w.headers = ["ID_HIDDEN", "Structure", "SMILES", "MW"]
    w._table_model.set_headers(list(w.headers))
    w._table_model.append_row(0, {"SMILES": "C", "MW": "10"})
    w._plot_replot_timer.stop()
    w._table_model.notify_structure_column_changed()
    assert not w._plot_replot_timer.isActive()
    w._table_model.set_cell_text(0, "MW", "12")
    assert w._plot_replot_timer.isActive()
    w.close()


def test_filter_apply_replots_even_during_background_job(qapp):  # noqa: ARG001
    w = ChemicalTableApp()
    _setup_two_row_mw_table(w)
    w._background_job_ui_depth = 1
    w._plot_replot_timer.stop()
    w._schedule_active_plots_replot()
    assert not w._plot_replot_timer.isActive()
    w._apply_filters_impl_sync(None)
    assert w._plot_replot_timer.isActive()
    w.close()


def test_subset_dimension_reduction_result_keeps_visible_oids() -> None:
    result = DimensionReductionResult(
        method="pca",
        x=[0.0, 1.0, 2.0],
        y=[3.0, 4.0, 5.0],
        oids=[10, 20, 30],
        hover=["a", "b", "c"],
        title="PCA",
        summary="",
        color_values=[1, 2, 3],
        color_label="MW",
    )
    subset = subset_dimension_reduction_result(result, frozenset({20, 30}))
    assert subset.oids == [20, 30]
    assert subset.x == [1.0, 2.0]
    assert subset.y == [4.0, 5.0]
    assert subset.color_values == [2, 3]
    assert subset_dimension_reduction_result(result, None) is result


def test_embedding_collect_ignores_table_filter(qapp):  # noqa: ARG001
    from molmanager.ui.data_analysis import table_to_dataframe

    w = ChemicalTableApp()
    _setup_two_row_mw_table(w)
    w._apply_filters_impl_sync(None)
    assert w._visible_oids_set() == frozenset({0})

    _df, rows = table_to_dataframe(w, visible_only=False, only_selected=False)
    assert set(rows) == {0, 1}
    _vis_df, vis_rows = table_to_dataframe(w, visible_only=True, only_selected=False)
    assert vis_rows == [0]

    mols = w.collect_scoped_table_mols("Structure", only_selected=False, only_visible=False)
    assert {oid for oid, _mol in mols} == {0, 1}
    vis_mols = w.collect_scoped_table_mols("Structure", only_selected=False, only_visible=True)
    assert {oid for oid, _mol in vis_mols} == {0}
    w.close()
