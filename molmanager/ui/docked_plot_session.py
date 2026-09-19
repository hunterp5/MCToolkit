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

"""Restore docked plot widgets from ``.cms`` session payloads."""

from __future__ import annotations

import logging

from PySide6.QtWidgets import QWidget

logger = logging.getLogger(__name__)


def apply_pane_display_title(widget: QWidget | None, title: object) -> None:
    if widget is None or not isinstance(title, str):
        return
    text = title.strip()
    if not text:
        return
    widget._pane_display_title = text


def restore_docked_plot_widget(parent_app, spec: dict) -> QWidget | None:
    """Build a docked plot widget from a session ``plots[]`` entry."""
    if not isinstance(spec, dict):
        return None
    state = spec.get("state")
    if not isinstance(state, dict):
        state = spec
    kind = str(spec.get("kind") or state.get("kind") or "plotter")

    widget: QWidget | None = None
    try:
        if kind == "plotter":
            from .plot import PlotWidget

            widget = PlotWidget.from_session_state(parent_app, state)
        elif kind == "dimension_reduction":
            from .dialogs.dimensionality_reduction import dimension_reduction_panel_from_session

            widget = dimension_reduction_panel_from_session(parent_app, state)
        elif kind == "medchem_space":
            from .dialogs.medchem_space import medchem_plot_panel_from_session

            widget = medchem_plot_panel_from_session(parent_app, state)
        elif kind == "sali_map":
            from .sali_map import SaliMapPanel

            widget = SaliMapPanel.from_session_state(parent_app, state)
        elif kind == "activity_cliff_map":
            from .activity_cliff_map import ActivityCliffMapPanel

            widget = ActivityCliffMapPanel.from_session_state(parent_app, state)
        elif kind == "mmp_neighborhood_map":
            from .mmp_neighborhood_map import MmpNeighborhoodMapPanel

            widget = MmpNeighborhoodMapPanel.from_session_state(parent_app, state)
        else:
            logger.warning("Unknown docked plot kind in session: %s", kind)
            return None
    except Exception:
        logger.exception("Failed to restore docked plot (kind=%s)", kind)
        return None

    apply_pane_display_title(widget, spec.get("display_title"))
    return widget
