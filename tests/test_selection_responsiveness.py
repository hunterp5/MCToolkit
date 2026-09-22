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

"""Guards for large selection / plot sync responsiveness contracts."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from mctoolkit.platform_support.config import load_config
from mctoolkit.ui.plot_table_sync import (
    mark_plot_origin_selection,
    record_selection_perf,
    selection_visual_push_key,
)
from mctoolkit.ui.plotly_shell import interactive_plot_shell_html


def test_oid_override_threshold_is_sub_thousand() -> None:
    """Large selections must leave Qt's selection model early (not at 2500)."""
    assert load_config().table_selection_oid_override_min <= 500


def test_plot_origin_mark_blocks_identical_visual_push() -> None:
    """After a lasso, table→plot sync must see the same push key and skip restyle."""
    view = SimpleNamespace(
        _last_pushed_selection_key=None,
        _selection_origin=None,
        _selected_point_indices={2, 4, 6},
        _web_ready=True,
        _pending_table_selection_sync=False,
        web=MagicMock(),
    )
    mark_plot_origin_selection(view, view._selected_point_indices)
    key = selection_visual_push_key(view._selected_point_indices)
    assert view._last_pushed_selection_key == key

    # Mimic PlotShellMixin._sync_plot_selection_visual early-out.
    assert selection_visual_push_key(view._selected_point_indices) == view._last_pushed_selection_key


def test_record_selection_perf_noop_without_tracker() -> None:
    record_selection_perf(SimpleNamespace(), "plot_lasso_select_ms", 12.0)
    perf = MagicMock()
    record_selection_perf(SimpleNamespace(_perf=perf), "plot_lasso_select_ms", 12.0)
    perf.record.assert_called_once_with("plot_lasso_select_ms", 12.0)


def test_shell_selection_suppress_is_short() -> None:
    html = interactive_plot_shell_html()
    assert "beginSuppressPlotBridge(80)" in html
    assert "beginSuppressPlotBridge(500)" not in html
    assert "keepViewLight" in html
    assert "Plotly.redraw(gd)" not in html


def test_shell_uses_quiet_settle_resize_policy() -> None:
    html = interactive_plot_shell_html()
    assert "HOST_RESIZE_SETTLE_MS = 50" in html
    assert "HOST_RESIZE_THROTTLE_MS" not in html
    assert "kickCompositor" not in html
    assert "stretchPlotToHost" not in html
    assert "new ResizeObserver(onHostResize)" not in html


def test_plot_web_surface_has_no_freeze_cover_apis() -> None:
    import mctoolkit.ui.plot_web_surface as pws

    assert not hasattr(pws, "_freeze_one_web_view")
    assert not hasattr(pws, "freeze_webengine_for_splitter_drag")
    assert hasattr(pws, "_PlotWebHostFilter")
