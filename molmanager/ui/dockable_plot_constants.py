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

"""Constants shared by docked-plot chrome, titles, and pane embed."""

from __future__ import annotations

from PySide6.QtGui import QColor

# Floor when no docked content is present (empty host / buttons only).
PLOT_PANEL_BASE_MINIMUM_WIDTH = 420
# Comfortable default dock width for a plot figure (options live in a dialog).
PLOT_PANEL_DEFAULT_WIDTH = 640
# Plot region narrower than this is treated as collapsed (grow to the layout default).
PLOT_PANEL_COLLAPSED_WIDTH = 48

_PANE_EMBED_ATTR = "_molmanager_pane_embed_state"
_DOCK_HEADER_HOME_ATTR = "_molmanager_dock_header_homes"
_FLOAT_TITLE_EDIT_ATTR = "_float_title_edit"
_FLOAT_TITLE_FILTER_ATTR = "_float_title_filter"
_FLOAT_TITLE_BASE_ATTR = "_float_title_edit_base"
_FLOAT_TITLE_RESIZE_FILTER_ATTR = "_float_title_resize_filter"
_DOCK_LEADING_OPTS_ATTRS = ("_opts_btn", "_clear_sel_btn")
_DOCK_HEADER_BUTTON_ATTRS = (
    "select_egg_btn",
    "select_yolk_btn",
    "select_region_btn",
    "_btn_browse",
)
# Floating: Add to Main. Docked: Send to New Window. Same footer slot.
_DOCK_SEND_WINDOW_ATTRS = (
    "_add_to_main_btn",
    "_send_window_btn",
)
_DOCK_TRAILING_CLOSE_BUTTON_ATTRS = (
    "_close_plot_btn",
    "_close_viewer_btn",
    "_close_btn",
)
_DOCK_TEXT_CHROME_ATTRS = (
    "_close_plot_btn",
    "_close_viewer_btn",
    "_close_btn",
    "select_egg_btn",
    "select_yolk_btn",
    "select_region_btn",
    "_btn_browse",
)
_GLYPH_BTN_SIZE = 20
_GLYPH_ICON_SIZE = 14
_GLYPH_INK = QColor(20, 20, 20)
_FOOTER_TEXT_FONT_PX = 12
_FOOTER_TEXT_PAD_H = 4
_PANE_TITLE_EDIT_WIDTH = 156
_BROWSER_NAV_BTN_WIDTH = 36
_BROWSER_NAV_BTN_HEIGHT = 24
_BROWSER_NAV_ICON_SIZE = 16
# Docked plot body: no extra air under the pane header.
PLOT_BODY_MARGINS = (2, 0, 2, 2)
PLOT_BODY_SPACING = 2
