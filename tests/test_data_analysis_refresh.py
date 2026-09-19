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

"""Statistics stays in sync with main-table edits."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6.QtWidgets")

import pandas as pd

from molmanager.ui.data_analysis import (
    DataAnalysisDialog,
    selected_table_column_headers,
    table_to_dataframe,
)


class _FakeTableModel:
    def __init__(self, rows: list[dict[str, str]], headers: list[str]) -> None:
        self._rows = rows
        self._headers = headers

    def columnCount(self) -> int:
        return len(self._headers)

    def rowCount(self) -> int:
        return len(self._rows)

    def cell_text(self, row: int, col: int) -> str:
        if col == 0:
            return str(row + 1)
        h = self._headers[col]
        return self._rows[row].get(h, "")

    def backing_value_for_row_header(self, row: int, header_name: str) -> str:
        return self._rows[row].get(header_name, "")


class _FakeApp:
    def __init__(self, rows: list[dict[str, str]], *, headers: list[str] | None = None) -> None:
        self.headers = headers or ["ID_HIDDEN", "MW"]
        self._table_model = _FakeTableModel(rows, self.headers)
        self.table = type("T", (), {"selectionModel": lambda _self: None})()

    def _selected_oids_set(self) -> set[int]:
        return set()

    def _selected_logical_rows(self) -> list[int]:
        return []

    def _visible_source_row_indices(self) -> list[int]:
        return list(range(self._table_model.rowCount()))


class _Idx:
    def __init__(self, col: int) -> None:
        self._col = col

    def column(self) -> int:
        return self._col

    def isValid(self) -> bool:
        return True


class _SelectionModel:
    def __init__(self, cols: list[int]) -> None:
        self._cols = cols

    def selectedIndexes(self) -> list[_Idx]:
        return [_Idx(c) for c in self._cols]


def test_table_to_dataframe_reflects_cell_edits() -> None:
    app = _FakeApp([{"ID_HIDDEN": "10", "MW": "1.0"}, {"ID_HIDDEN": "11", "MW": "2.0"}])
    df, _rows = table_to_dataframe(app, visible_only=False, only_selected=False)
    assert float(df.loc[0, "MW"]) == 1.0

    app._table_model._rows[0]["MW"] = "99.0"
    df2, _rows2 = table_to_dataframe(app, visible_only=False, only_selected=False)
    assert float(df2.loc[0, "MW"]) == 99.0


def test_selected_table_column_headers() -> None:
    app = _FakeApp([], headers=["ID_HIDDEN", "MW", "LogP"])
    app.table.selectionModel = lambda: _SelectionModel([1])
    assert selected_table_column_headers(app) == ["MW"]


def test_selected_columns_only_filters_numeric_frame(qapp):  # noqa: ARG001
    app = _FakeApp(
        [
            {"ID_HIDDEN": "1", "MW": "1", "LogP": "2"},
            {"ID_HIDDEN": "2", "MW": "3", "LogP": "4"},
        ],
        headers=["ID_HIDDEN", "MW", "LogP"],
    )
    app.table.selectionModel = lambda: _SelectionModel([1])
    dlg = DataAnalysisDialog(None)
    dlg.parent_app = app
    dlg.chk_visible.setChecked(False)
    dlg.refresh_table_data()
    dlg.chk_selected_columns.setChecked(True)
    dlg.chk_selected_columns.setEnabled(True)
    num = dlg._numeric_for_correlation_percentiles()
    assert list(num.columns) == ["MW"]


def test_run_outliers_uses_refreshed_values(qapp):  # noqa: ARG001
    """Find outliers must read live table cells, not a stale cached frame."""
    app = _FakeApp(
        [
            {"ID_HIDDEN": "1", "MW": "1"},
            {"ID_HIDDEN": "2", "MW": "2"},
            {"ID_HIDDEN": "3", "MW": "3"},
            {"ID_HIDDEN": "4", "MW": "100"},
        ]
    )
    dlg = DataAnalysisDialog(None)
    dlg.parent_app = app
    dlg.chk_visible.setChecked(False)
    dlg.refresh_table_data()

    app._table_model._rows[3]["MW"] = "4"
    dlg._df_num = pd.DataFrame({"MW": [1.0, 2.0, 3.0, 100.0]})
    dlg._scoped_source_rows = [0, 1, 2, 3]

    dlg.outlier_col.setCurrentText("MW")
    dlg.outlier_method.setCurrentIndex(0)
    dlg._run_outliers()

    assert "Outliers flagged: 0" in dlg.outlier_text.toPlainText()


def test_reload_preserves_outlier_log_and_column(qapp):  # noqa: ARG001
    app = _FakeApp(
        [
            {"ID_HIDDEN": "1", "MW": "1"},
            {"ID_HIDDEN": "2", "MW": "2"},
            {"ID_HIDDEN": "3", "MW": "3"},
            {"ID_HIDDEN": "4", "MW": "100"},
        ]
    )
    dlg = DataAnalysisDialog(None)
    dlg.parent_app = app
    dlg.chk_visible.setChecked(False)
    dlg.refresh_table_data()
    dlg.outlier_col.setCurrentText("MW")
    dlg._run_outliers()
    log = dlg.outlier_text.toPlainText()
    assert log
    dlg._last_outlier_table_rows = [3]
    dlg.refresh_table_data()
    assert dlg.outlier_text.toPlainText() == log
    assert dlg.outlier_col.currentText() == "MW"
    assert dlg._last_outlier_table_rows == [3]


def test_select_in_table_preserves_column_choice(qapp):  # noqa: ARG001
    selected: list[list[int]] = []

    class _SelectApp(_FakeApp):
        def select_table_rows(self, rows: list[int]) -> None:
            selected.append(list(rows))

    app = _SelectApp(
        [
            {"ID_HIDDEN": "1", "MW": "1"},
            {"ID_HIDDEN": "2", "MW": "2"},
            {"ID_HIDDEN": "3", "MW": "3"},
            {"ID_HIDDEN": "4", "MW": "100"},
        ]
    )
    dlg = DataAnalysisDialog(None)
    dlg.parent_app = app
    dlg.chk_visible.setChecked(False)
    dlg.refresh_table_data()
    dlg.outlier_col.setCurrentText("MW")
    dlg._last_outlier_table_rows = [3]
    dlg._select_last_outliers_in_main_table()
    assert selected == [[3]]
    assert dlg.outlier_col.currentText() == "MW"


def test_table_dataframe_source_does_not_import_statistics_ui() -> None:
    """QSAR / MMP / dimred / medchem-space must not construct the Statistics dialog to get a DataFrame."""
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "molmanager" / "ui" / "table_dataframe.py"
    text = path.read_text(encoding="utf-8")
    assert "PyQt5" not in text
    assert "PySide6" not in text
    assert "QDialog" not in text
    assert "DataAnalysisDialog" not in text
    for rel in (
        "molmanager/ui/dialogs/qsar.py",
        "molmanager/ui/dialogs/mmp.py",
        "molmanager/ui/dialogs/dimred_panel.py",
        "molmanager/ui/dialogs/medchem_space.py",
    ):
        src = (Path(__file__).resolve().parents[1] / rel).read_text(encoding="utf-8")
        assert "from .data_analysis import" not in src
        assert "table_dataframe" in src
