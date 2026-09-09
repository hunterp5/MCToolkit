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

"""Shared helpers for plots docked beside the main compound table."""

from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QDialog, QVBoxLayout, QWidget

# Floor when no docked content is present (empty host / buttons only).
PLOT_PANEL_BASE_MINIMUM_WIDTH = 420
# Comfortable default dock width for a plot figure (options live in a dialog).
PLOT_PANEL_DEFAULT_WIDTH = 640


def discard_host_dialog_after_dock(dlg, host, attr_name: str) -> None:
    """Destroy the empty floating husk after its panel was reparented into the workspace."""
    if dlg is None:
        return
    if hasattr(dlg, "_panel"):
        dlg._panel = None
    dlg._force_close = True
    if host is not None and getattr(host, attr_name, None) is dlg:
        setattr(host, attr_name, None)
    try:
        dlg.close()
        dlg.deleteLater()
    except RuntimeError:
        pass


def make_plot_options_dialog(
    parent: QWidget,
    content: QWidget,
    *,
    title: str = "Plot Options",
    min_width: int = 520,
    min_height: int = 360,
) -> QDialog:
    """Build a modeless dialog that hosts a plot's options panel."""
    dlg = QDialog(parent)
    dlg.setWindowTitle(title)
    dlg.setModal(False)
    dlg.setWindowModality(Qt.NonModal)
    dlg.setAttribute(Qt.WA_DeleteOnClose, False)
    dlg.setMinimumWidth(min_width)
    dlg.setMinimumHeight(min_height)
    root = QVBoxLayout(dlg)
    root.setContentsMargins(8, 8, 8, 8)
    root.addWidget(content, 1)
    return dlg


def show_plot_options_dialog(dialog: QDialog | None) -> None:
    """Show and raise an existing plot-options dialog."""
    if dialog is None:
        return
    dialog.show()
    dialog.raise_()
    dialog.activateWindow()


def hide_plot_options_dialog(dialog: QDialog | None) -> None:
    """Hide a plot-options dialog if it is open."""
    if dialog is None:
        return
    try:
        dialog.hide()
    except RuntimeError:
        pass


def iter_plot_selection_views(root: QWidget | None) -> list:
    """Return widgets that implement ``sync_from_table_selection`` (plot ↔ table)."""
    if root is None:
        return []
    views: list = []
    seen: set[int] = set()

    def add(candidate) -> None:
        if candidate is None:
            return
        key = id(candidate)
        if key in seen:
            return
        if not callable(getattr(candidate, "sync_from_table_selection", None)):
            return
        seen.add(key)
        views.append(candidate)

    add(root)
    add(getattr(root, "_plot_view", None))
    add(getattr(root, "_plot_widget", None))
    return views


def is_dockable_plot_widget(widget) -> bool:
    """True when the widget can be placed in the main-window plot panel."""
    return getattr(widget, "only_selected_cb", None) is not None and bool(
        iter_plot_selection_views(widget)
    )


def is_dockable_workspace_widget(widget) -> bool:
    """True for plot panels or other workspace-dockable widgets (e.g. 2D/3D viewers)."""
    if is_dockable_plot_widget(widget):
        return True
    return bool(getattr(widget, "dockable_in_workspace", False))


def plot_embedded_minimum_width(widget: QWidget | None) -> int:
    """Minimum panel width so docked plot controls do not overlap or clip."""
    if widget is None:
        return PLOT_PANEL_BASE_MINIMUM_WIDTH
    custom = getattr(widget, "embedded_minimum_width", None)
    if callable(custom):
        try:
            return max(PLOT_PANEL_BASE_MINIMUM_WIDTH, int(custom()))
        except Exception:
            pass
    try:
        hint = int(widget.minimumSizeHint().width())
    except Exception:
        hint = 0
    return max(PLOT_PANEL_BASE_MINIMUM_WIDTH, hint)


def plot_embedded_preferred_width(widget: QWidget | None) -> int:
    """Preferred dock width (at least the minimum needed for controls)."""
    min_w = plot_embedded_minimum_width(widget)
    if widget is None:
        return max(min_w, PLOT_PANEL_DEFAULT_WIDTH)
    custom = getattr(widget, "embedded_preferred_width", None)
    if callable(custom):
        try:
            return max(min_w, int(custom()))
        except Exception:
            pass
    try:
        hint = int(widget.sizeHint().width())
    except Exception:
        hint = 0
    return max(min_w, hint, PLOT_PANEL_DEFAULT_WIDTH)
