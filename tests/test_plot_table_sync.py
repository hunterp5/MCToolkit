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
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with mctoolkit.  If not, see <https://www.gnu.org/licenses/>.

"""plot_table_sync helpers."""

from __future__ import annotations

from mctoolkit.ui.plot_table_sync import (
    apply_table_selection_for_source_rows,
    clear_table_selection_from_plot,
    point_indices_for_oids,
    selected_oids_for_plot,
    selection_visual_push_key,
)


def test_point_indices_for_oids() -> None:
    plotted = [10, 20, 30]
    assert point_indices_for_oids(plotted, {20, 99}) == {1}
    assert point_indices_for_oids(plotted, frozenset()) == set()
    assert point_indices_for_oids([], {10}) == set()


def test_selection_visual_push_key_stable_for_same_set() -> None:
    assert selection_visual_push_key(set()) == (0, 0)
    a = selection_visual_push_key({1, 2, 3})
    b = selection_visual_push_key({3, 2, 1})
    assert a == b
    assert a[0] == 3
    assert selection_visual_push_key({1, 2, 3, 4}) != a


def test_point_indices_for_oids_uses_index_and_partners() -> None:
    from mctoolkit.ui.plot_table_sync import build_oid_point_index

    plotted = [10, 20, 30]
    partners = [11, 21, 31]
    index = build_oid_point_index(plotted, partners)
    assert point_indices_for_oids(plotted, {21}, oid_index=index) == {1}
    assert point_indices_for_oids(plotted, {10, 31}, oid_index=index) == {0, 2}


class _FakeModel:
    def __init__(
        self, oids_by_row: dict[int, int], highlighted: frozenset[int] | None = None
    ) -> None:
        self._oids_by_row = oids_by_row
        self._highlighted = highlighted

    def row_oid(self, row: int) -> int:
        return self._oids_by_row[row]

    def highlighted_oids(self) -> frozenset[int] | None:
        return self._highlighted


class _FakeApp:
    def __init__(self) -> None:
        self._selected_oids_override = None
        self._logical_rows: list[int] = []
        self._table_model = _FakeModel({0: 10, 1: 20, 2: 30})

    def _selected_logical_rows(self) -> list[int]:
        return list(self._logical_rows)


def test_selected_oids_for_plot_qt_selection() -> None:
    app = _FakeApp()
    app._logical_rows = [0, 2]
    assert selected_oids_for_plot(app) == {10, 30}


def test_selected_oids_for_plot_override() -> None:
    app = _FakeApp()
    app._selected_oids_override = frozenset({99})
    app._logical_rows = [0]
    assert selected_oids_for_plot(app) == {99}


def test_selected_oids_for_plot_highlighted_fallback() -> None:
    app = _FakeApp()
    app._table_model = _FakeModel({0: 10, 1: 20}, highlighted=frozenset({20}))
    assert selected_oids_for_plot(app) == {20}


def test_apply_table_selection_skips_identical_selection() -> None:
    """Re-applying the same plot selection must not scroll / re-select (snap-back loop)."""
    from unittest.mock import MagicMock

    sm = MagicMock()
    row0 = MagicMock()
    row0.row.return_value = 0
    row2 = MagicMock()
    row2.row.return_value = 2
    sm.selectedRows.return_value = [row0, row2]

    table = MagicMock()
    table.selectionModel.return_value = sm
    view_model = MagicMock()
    view_model.columnCount.return_value = 3
    table.model.return_value = view_model

    app = MagicMock()
    app.table = table
    app._source_rows_to_view_rows.return_value = [0, 2]
    app._in_programmatic_table_selection = False
    app._selected_oids_override = None

    apply_table_selection_for_source_rows(app, [0, 2], scroll=True)

    sm.select.assert_not_called()
    table.scrollTo.assert_not_called()
    app.select_table_rows.assert_not_called()


def test_apply_table_selection_uses_select_table_rows() -> None:
    """Plot→table should use the app chunked/OID path when available."""
    from unittest.mock import MagicMock

    sm = MagicMock()
    sm.selectedRows.return_value = []
    table = MagicMock()
    table.selectionModel.return_value = sm
    table.model.return_value = MagicMock()

    app = MagicMock()
    app.table = table
    app._source_rows_to_view_rows.return_value = [0, 1]
    app._selected_oids_override = None

    apply_table_selection_for_source_rows(app, [0, 1], scroll=False)

    app.select_table_rows.assert_called_once_with([0, 1], force_oid_override=True)
    sm.select.assert_not_called()


def test_apply_table_selection_single_row_skips_force_oid() -> None:
    from unittest.mock import MagicMock

    sm = MagicMock()
    sm.selectedRows.return_value = []
    table = MagicMock()
    table.selectionModel.return_value = sm
    table.model.return_value = MagicMock()

    app = MagicMock()
    app.table = table
    app._source_rows_to_view_rows.return_value = [0]
    app._selected_oids_override = None

    apply_table_selection_for_source_rows(app, [0], scroll=False)

    app.select_table_rows.assert_called_once_with([0])
    sm.select.assert_not_called()


def test_mark_plot_origin_selection_sets_push_key() -> None:
    from types import SimpleNamespace

    from mctoolkit.ui.plot_table_sync import mark_plot_origin_selection, selection_visual_push_key

    view = SimpleNamespace(_last_pushed_selection_key=None, _selection_origin=None)
    idxs = {1, 5, 9}
    mark_plot_origin_selection(view, idxs)
    assert view._selection_origin == "plot"
    assert view._last_pushed_selection_key == selection_visual_push_key(idxs)


def test_clear_table_selection_from_plot_uses_app_clear() -> None:
    from unittest.mock import MagicMock

    app = MagicMock()
    app._plot_table_select_timer = None
    clear_table_selection_from_plot(app)
    app.clear_table_selection.assert_called_once()
    app.table.clearSelection.assert_not_called()
