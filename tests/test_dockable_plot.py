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

"""Tests for docked-plot panel width helpers."""

from molmanager.ui.dockable_plot import (
    PLOT_PANEL_BASE_MINIMUM_WIDTH,
    PLOT_PANEL_DEFAULT_WIDTH,
    is_dockable_plot_widget,
    is_dockable_workspace_widget,
    plot_embedded_minimum_width,
    plot_embedded_preferred_width,
)


class _WidePlot:
    def embedded_minimum_width(self) -> int:
        return 700

    def embedded_preferred_width(self) -> int:
        return 900


class _ViewerLike:
    dockable_in_workspace = True


def test_plot_embedded_widths_use_custom_hooks():
    w = _WidePlot()
    assert plot_embedded_minimum_width(w) == 700
    assert plot_embedded_preferred_width(w) == 900


def test_plot_embedded_widths_fallback_without_widget():
    assert plot_embedded_minimum_width(None) == PLOT_PANEL_BASE_MINIMUM_WIDTH
    assert plot_embedded_preferred_width(None) == max(
        PLOT_PANEL_BASE_MINIMUM_WIDTH, PLOT_PANEL_DEFAULT_WIDTH
    )


def test_plot_widget_dock_width_is_figure_sized():
    """Options live in a dialog, so docked width no longer needs axes+stats side-by-side."""
    import inspect

    from molmanager.ui.plot import PlotWidget

    stub = type(
        "W",
        (),
        {
            "embedded_minimum_width": lambda self: 420,
            "embedded_preferred_width": lambda self: 640,
        },
    )()
    assert plot_embedded_minimum_width(stub) == 420
    assert plot_embedded_preferred_width(stub) == 640
    min_src = inspect.getsource(PlotWidget.embedded_minimum_width)
    pref_src = inspect.getsource(PlotWidget.embedded_preferred_width)
    assert "420" in min_src
    assert "640" in pref_src
    assert "_AXES_CONTROLS_MIN_WIDTH" not in min_src


def test_is_dockable_workspace_widget_accepts_viewer_marker():
    viewer = _ViewerLike()
    assert is_dockable_workspace_widget(viewer)
    assert not is_dockable_plot_widget(viewer)


def test_molecule_3d_viewer_widget_is_workspace_dockable():
    from molmanager.ui.mol_viewer_3d import Molecule3DViewerWidget

    assert getattr(Molecule3DViewerWidget, "dockable_in_workspace", False) is True
    assert is_dockable_workspace_widget(Molecule3DViewerWidget)


def test_selection_browser_widget_is_workspace_dockable():
    from molmanager.ui.selection_browser import SelectionBrowserWidget
    from molmanager.ui.som_browser import SomBrowserWidget

    assert getattr(SelectionBrowserWidget, "dockable_in_workspace", False) is True
    assert is_dockable_workspace_widget(SelectionBrowserWidget)
    assert not is_dockable_plot_widget(SelectionBrowserWidget)
    assert hasattr(SelectionBrowserWidget, "create_floating_dialog")
    assert hasattr(SelectionBrowserWidget, "_toggle_options_visible")
    assert hasattr(SelectionBrowserWidget, "_sync_options_chrome")
    assert is_dockable_workspace_widget(SomBrowserWidget)
    assert hasattr(SomBrowserWidget, "create_floating_dialog")
