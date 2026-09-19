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

"""Dock chrome, Plot Options dialog, and pane width for the ligand 3D viewer."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QHBoxLayout, QLayout, QSizePolicy, QWidget

from .dockable_plot import show_plot_options_dialog

if TYPE_CHECKING:
    from .mol_3d_dialog import Molecule3DViewerDialog


def _molecule_3d_viewer_dialog_cls() -> type:
    """Lazy import to avoid a widget↔dialog cycle at module load."""
    from .mol_3d_dialog import Molecule3DViewerDialog

    return Molecule3DViewerDialog


def _layout_visible_min_width(layout) -> int:
    """Sum size hints of visible widgets in a box layout, including spacing and margins."""
    if layout is None:
        return 0
    try:
        margins = layout.contentsMargins()
        total = int(margins.left() + margins.right())
        spacing = int(layout.spacing())
    except Exception:
        total = 0
        spacing = 0
    n_vis = 0
    try:
        count = int(layout.count())
    except Exception:
        return total
    for i in range(count):
        item = layout.itemAt(i)
        if item is None:
            continue
        w = item.widget()
        if w is None or w.isHidden():
            continue
        n_vis += 1
        hint = max(int(w.sizeHint().width()), int(w.minimumSizeHint().width()), 0)
        total += hint
    if n_vis > 1:
        total += spacing * (n_vis - 1)
    return total


class Mol3DChromeMixin:
    """Footer dock/undock chrome and viewer options dialog."""

    def rebind_parent_app(self, parent_app: QWidget | None) -> None:
        """Update the host app after dock/undock and refresh property columns."""
        self.parent_app = parent_app
        if self._prop_panel is not None:
            self._prop_panel.bind_app(parent_app)
            self._prop_panel.set_source_oid(self._source_oid)
        self._wire_property_column_updates()

    def embedded_minimum_width(self) -> int:
        host = getattr(self, "_conf_nav_host", None)
        if host is None:
            return 420
        row_w = _layout_visible_min_width(host.layout())
        return max(1200, row_w + 32)

    def embedded_preferred_width(self) -> int:
        return max(self.embedded_minimum_width(), 1280)

    def _apply_footer_size_constraints(self, foot: QHBoxLayout) -> None:
        status = getattr(self, "_viewer_status", None)
        for i in range(foot.count()):
            item = foot.itemAt(i)
            w = item.widget() if item is not None else None
            if w is None or w is status:
                continue
            w.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
        foot.setSizeConstraint(QLayout.SetMinimumSize)

    def create_floating_dialog(self, parent_app) -> "Molecule3DViewerDialog":
        """Re-open this viewer in a floating window after undocking from the main table."""
        return _molecule_3d_viewer_dialog_cls()(
            None,
            parent_app,
            window_title=self._window_title,
            viewer_widget=self,
        )

    def _add_to_main_window(self) -> None:
        if self.parent_app is None:
            return
        dock = getattr(self.parent_app, "dock_plot_widget", None)
        if not callable(dock):
            return
        dlg = self.window()
        teardown = getattr(dlg, "_scope_sync_disconnect", None)
        if callable(teardown):
            teardown()
        if not dock(self):
            return
        if isinstance(dlg, _molecule_3d_viewer_dialog_cls()):
            dlg._viewer_widget = None
            dlg._force_close = True
            dlg.close()

    def _send_to_new_window(self) -> None:
        if self.parent_app is not None:
            undock = getattr(self.parent_app, "undock_plot_to_window", None)
            if callable(undock):
                undock(self)

    def _close_docked_viewer(self) -> None:
        from .dockable_plot import request_close_plot_widget

        request_close_plot_widget(
            self,
            title="Close Viewer",
            message="Close this viewer?",
        )

    def _is_docked_in_main_window(self) -> bool:
        app = self.parent_app
        if app is None:
            return False
        check = getattr(app, "is_plot_docked", None)
        if callable(check):
            return bool(check(self))
        return getattr(app, "_docked_plot_widget", None) is self

    def _sync_footer_chrome(self) -> None:
        """Floating: opts + Add. Docked: opts + Send + Close (Close moves beside pane ×)."""
        from .dockable_plot import apply_plot_chrome_glyphs, sync_docked_footer_bar

        apply_plot_chrome_glyphs(self)
        floating = isinstance(self.window(), _molecule_3d_viewer_dialog_cls())
        docked = self._is_docked_in_main_window()
        self._add_to_main_btn.setVisible(floating)
        self._send_window_btn.setVisible(docked)
        self._close_viewer_btn.setVisible(docked)
        sync_docked_footer_bar(self, docked=docked)
        if not docked:
            self.setMinimumWidth(self.embedded_minimum_width())

    def _sync_options_chrome(self) -> None:
        """Show or hide property column pickers from Viewer Settings."""
        if getattr(self, "_prop_panel", None) is None:
            return
        visible = bool(getattr(self, "_options_visible", True))
        spin = getattr(self, "_spin_field_count", None)
        count = int(spin.value()) if spin is not None else 1
        host = getattr(self, "_options_host", None)
        if host is not None:
            host.setVisible(visible and count > 0)
        cb = getattr(self, "_cb_hide_options", None)
        if cb is not None and cb.isChecked() == visible:
            cb.blockSignals(True)
            cb.setChecked(not visible)
            cb.blockSignals(False)

    def _on_hide_options_toggled(self, checked: bool) -> None:
        self._options_visible = not bool(checked)
        self._sync_options_chrome()

    def _on_field_count_changed(self, value: int) -> None:
        panel = getattr(self, "_prop_panel", None)
        if panel is not None:
            panel.set_visible_slot_count(int(value))
        self._sync_options_chrome()

    def _open_viewer_options(self) -> None:
        show_plot_options_dialog(getattr(self, "_opts_dialog", None))

    def event(self, event):  # noqa: N802 — Qt API name
        if event.type() == QEvent.ParentChange:
            self._sync_footer_chrome()
        return super().event(event)

    def _host_app(self) -> QWidget | None:
        if self.parent_app is not None:
            return self.parent_app
        parent = self.parent()
        return parent if parent is not None else None

    def _set_viewer_status(self, message: str) -> None:
        msg = (message or "").strip()
        status = getattr(self, "_viewer_status", None)
        if status is not None:
            status.setText(msg)
        app = self._host_app()
        plabel = getattr(app, "status_label", None) if app is not None else None
        if plabel is not None and msg:
            try:
                plabel.setText(msg)
            except Exception:
                pass
