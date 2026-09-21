# This file is part of MCToolkit.
# Copyright (C) 2026 Hunter Picard
#
# MCToolkit is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# MCToolkit is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with MCToolkit. If not, see <https://www.gnu.org/licenses/>.

"""Workspace plot docking owner: dock/undock, panel width, and pane close."""

from __future__ import annotations

import logging
from typing import Any, Protocol

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QMessageBox

from .app_roles import ProgressChrome

logger = logging.getLogger(__name__)


class PlotDockChrome(Protocol):
    """Window methods PlotDockHost needs beyond status-bar chrome."""

    def apply_workspace_layout(self, layout_id: str) -> None: ...
    def _prepare_tool_plot(self, plot_widget: Any) -> None: ...
    def _sync_active_plots_from_table_selection(self) -> None: ...
    def _prepare_tool_dialog(self, dialog: Any) -> None: ...
    def _bind_undocked_browser_dialog(self, dlg: Any) -> bool: ...
    def _register_plot_dialog(self, dlg: Any) -> None: ...
    def _register_floating_result_dialog(self, dlg: Any) -> None: ...


class PlotDockHostApp(ProgressChrome, PlotDockChrome, Protocol):
    """What the dock host reads from the window."""


def _plot_dialog_and_widget_types():
    """Import plot window types when QtWebEngine is available in this process."""
    try:
        from .plot import PlotDialog, PlotWidget
    except ImportError:
        return None, None
    return PlotDialog, PlotWidget


class PlotDockHost:
    """Owns docked-plot lifecycle for :class:`~mctoolkit.ui.main_window.ChemistryWorkspaceWindow`.

    Public entry points remain on the main window (via ``install_window_forwards``)
    so existing callers keep working; this object holds the implementation.
    """

    def __init__(self, app: PlotDockHostApp) -> None:
        self._app = app

    def workspace(self):
        return getattr(self._app, "_workspace_layout", None)

    @staticmethod
    def _docked_widget_kind(plot_widget) -> str:
        title = getattr(plot_widget, "_window_title", None)
        if title:
            return str(title)
        if getattr(plot_widget, "dockable_in_workspace", False) and not getattr(
            plot_widget, "only_selected_cb", None
        ):
            return "Viewer"
        return "Plot"

    def iter_docked_plot_widgets(self):
        mgr = self.workspace()
        if mgr is None:
            return
        yield from mgr.iter_docked_widgets()

    def pane_for_plot_widget(self, plot_widget):
        mgr = self.workspace()
        if mgr is None:
            return None
        return mgr.pane_for_widget(plot_widget)

    def is_plot_docked(self, plot_widget) -> bool:
        return self.pane_for_plot_widget(plot_widget) is not None

    def find_docked_plot_widget(self, predicate):
        for w in self.iter_docked_plot_widgets():
            try:
                if predicate(w):
                    return w
            except RuntimeError:
                continue
        return None

    @property
    def _docked_plot_widget(self):
        """Compatibility: preferred pane's plot, else first docked plot."""
        mgr = self.workspace()
        if mgr is None:
            return None
        pref = mgr.preferred_pane()
        if pref is not None and pref.plot_widget() is not None:
            return pref.plot_widget()
        for w in mgr.iter_docked_widgets():
            return w
        return None

    @_docked_plot_widget.setter
    def _docked_plot_widget(self, value) -> None:
        # Legacy assignments clear nothing useful; ignore None writes from old paths.
        if value is None:
            return
        mgr = self.workspace()
        if mgr is None:
            return
        pane = mgr.preferred_pane() or (mgr.plot_panes()[0] if mgr.plot_panes() else None)
        if pane is not None:
            mgr.dock_into_pane(pane, value)

    def _plot_panel_splitter_sizes(self) -> list[int] | None:
        """Outer table|plots sizes when the workspace uses a horizontal outer splitter."""
        mgr = self.workspace()
        if mgr is None or not mgr._splitters:
            return None
        splitter = mgr._splitters[0]
        try:
            sizes = [int(s) for s in splitter.sizes()]
        except RuntimeError:
            return None
        if len(sizes) < 2:
            return None
        return sizes

    def _docked_plot_content_widths(self) -> tuple[int, int]:
        """Return ``(minimum_width, preferred_width)`` for docked plot content."""
        from .dockable_plot import (
            PLOT_PANEL_BASE_MINIMUM_WIDTH,
            PLOT_PANEL_DEFAULT_WIDTH,
            plot_embedded_minimum_width,
            plot_embedded_preferred_width,
        )

        widgets = list(self.iter_docked_plot_widgets())
        if not widgets:
            return PLOT_PANEL_BASE_MINIMUM_WIDTH, PLOT_PANEL_DEFAULT_WIDTH
        min_w = max(plot_embedded_minimum_width(w) for w in widgets)
        pref_w = max(plot_embedded_preferred_width(w) for w in widgets)
        return min_w, pref_w

    def _apply_plot_panel_minimum_width(self) -> int:
        from .dockable_plot import PLOT_PANEL_BASE_MINIMUM_WIDTH

        mgr = self.workspace()
        if mgr is None:
            return PLOT_PANEL_BASE_MINIMUM_WIDTH
        min_w, _pref = self._docked_plot_content_widths()
        if not list(self.iter_docked_plot_widgets()):
            min_w = PLOT_PANEL_BASE_MINIMUM_WIDTH
        return min_w

    def _ensure_plot_panel_width(self, preferred: int | None = None) -> None:
        """Give the plot region a usable width when the outer splitter is horizontal."""
        from .dockable_plot import PLOT_PANEL_COLLAPSED_WIDTH

        mgr = self.workspace()
        if mgr is None or not mgr._splitters:
            return
        if mgr.layout_id in {"quadrants", "table_grid"}:
            return
        splitter = mgr._splitters[0]
        try:
            sizes = [int(s) for s in splitter.sizes()]
        except RuntimeError:
            return
        if len(sizes) < 2:
            return
        table_w, plot_w = sizes[0], sizes[1]
        # Existing panes already have a share of the window; do not grow them to
        # the docked widget's floating sizeHint / preferred width.
        if preferred is None and plot_w >= PLOT_PANEL_COLLAPSED_WIDTH:
            return
        min_w = self._apply_plot_panel_minimum_width()
        _content_min, content_pref = self._docked_plot_content_widths()
        if preferred is not None:
            want = max(min_w, int(preferred))
        else:
            want = max(min_w, content_pref)
        if plot_w >= want:
            return
        total = max(table_w + plot_w, want + 200)
        new_plot = min(want, max(min_w, total - 200))
        new_table = max(200, total - new_plot)
        splitter.setSizes([new_table, new_plot])

    def _target_plot_pane(self):
        """Return the active plot pane, expanding Table Only to a table|plot split."""
        from .main_window.workspace_layout import LAYOUT_TABLE_SINGLE

        mgr = self.workspace()
        if mgr is None:
            return None
        if mgr.plot_panes():
            return mgr.preferred_pane()
        # No panes (Table Only): split the table with a single plot pane.
        self._app.apply_workspace_layout(LAYOUT_TABLE_SINGLE)
        panes = mgr.plot_panes()
        if not panes:
            return None
        pane = panes[0]
        mgr.set_preferred_pane(pane)
        return pane

    def dock_plot_widget(self, plot_widget, pane=None) -> bool:
        """Move a plot or viewer widget into the active workspace plot pane."""
        from .dockable_plot import is_dockable_workspace_widget

        if not is_dockable_workspace_widget(plot_widget):
            _dialog_cls, plot_cls = _plot_dialog_and_widget_types()
            if plot_cls is None or not isinstance(plot_widget, plot_cls):
                return False
        mgr = self.workspace()
        if mgr is None:
            return False

        target = pane if pane is not None else self._target_plot_pane()
        if target is None:
            return False

        prior_teardown = getattr(plot_widget, "_scope_sync_disconnect", None)
        if callable(prior_teardown):
            prior_teardown()
        mgr.dock_into_pane(target, plot_widget)
        self.show_docked_plot_panel()
        self._wire_docked_plot_widget(plot_widget)
        kind = self._docked_widget_kind(plot_widget)
        pane_n = mgr.plot_panes().index(target) + 1
        n_pages = target.page_count()
        if n_pages > 1:
            self._app.status_label.setText(
                f"{kind}: docked in pane {pane_n} ({target.page_index() + 1}/{n_pages})."
            )
        else:
            self._app.status_label.setText(f"{kind}: docked in pane {pane_n}.")
        mark = getattr(self._app, "_mark_session_dirty", None)
        if callable(mark):
            mark()
        return True

    def _wire_docked_plot_widget(self, plot_widget) -> None:
        """Attach session/scope hooks used for any docked plot or viewer."""
        self._app._prepare_tool_plot(plot_widget)
        try:
            plot_widget.destroyed.disconnect(self._on_docked_plot_destroyed)
        except (TypeError, RuntimeError):
            pass
        plot_widget.destroyed.connect(self._on_docked_plot_destroyed)
        self._app._sync_active_plots_from_table_selection()
        sync_footer = getattr(plot_widget, "_sync_footer_chrome", None)
        if callable(sync_footer):
            sync_footer()

    def _float_released_plot_widget(self, plot_widget) -> None:
        """Open a released docked plot in a floating dialog when possible."""
        if plot_widget is None:
            return
        factory = getattr(plot_widget, "create_floating_dialog", None)
        try:
            if callable(factory):
                dlg = factory(self._app)
                self._app._prepare_tool_dialog(dlg)
                if hasattr(dlg, "_plot_widget") or hasattr(dlg, "_panel"):
                    pass
                if not self._app._bind_undocked_browser_dialog(dlg):
                    plot_dialog_cls, _plot_cls = _plot_dialog_and_widget_types()
                    if plot_dialog_cls is not None and isinstance(dlg, plot_dialog_cls):
                        self._app._register_plot_dialog(dlg)
                    else:
                        self._app._register_floating_result_dialog(dlg)
                plot_widget.show()
                dlg.show()
                dlg.raise_()
                dlg.activateWindow()
                return
        except Exception:
            logger.exception("Failed to float released plot widget")
        try:
            plot_widget.setParent(None)
            plot_widget.deleteLater()
        except RuntimeError:
            pass

    def _sync_plot_panel_bottom_visibility(self) -> None:
        """No shared host bottom bar in multi-pane layout."""
        return

    def show_docked_plot_panel(self) -> None:
        """Ensure the workspace plot region has usable width."""
        mgr = self.workspace()
        if mgr is not None:
            mgr.show()
        # Session restore owns splitter sizes; do not fight them with auto-grow.
        if getattr(self._app, "_pending_session_workspace_layout", None):
            return
        QTimer.singleShot(0, self._ensure_plot_panel_width)

    def hide_docked_plot_panel(self) -> None:
        """Collapse plot region width on horizontal layouts (table keeps space)."""
        mgr = self.workspace()
        if mgr is None or not mgr._splitters:
            return
        if mgr.layout_id == "quadrants":
            return
        splitter = mgr._splitters[0]
        try:
            sizes = [int(s) for s in splitter.sizes()]
        except RuntimeError:
            return
        total = sum(sizes) if sizes else 0
        if total <= 0:
            total = max(splitter.width(), 1)
        splitter.setSizes([total, 0])

    def _on_docked_plot_destroyed(self, *_args) -> None:
        mgr = self.workspace()
        if mgr is None:
            return
        for pane in mgr.plot_panes():
            for w in list(pane.plot_widgets()):
                try:
                    import shiboken6

                    if not shiboken6.isValid(w):
                        pane.remove_plot_widget(w)
                except Exception:
                    pass

    def close_plot_panel_keep_plot(self) -> None:
        """Hide/collapse the plot region; docked widgets are preserved."""
        self.hide_docked_plot_panel()
        self._app.status_label.setText("Plot panel hidden.")

    def close_docked_plot(self, plot_widget=None, *, confirm: bool = True) -> None:
        """Close a docked plot (``plot_widget`` or the preferred/occupied pane)."""
        mgr = self.workspace()
        if mgr is None:
            return
        if plot_widget is None:
            pane = mgr.preferred_pane()
            plot_widget = pane.plot_widget() if pane is not None else None
            if plot_widget is None:
                for p in mgr.plot_panes():
                    if p.plot_widget() is not None:
                        pane = p
                        plot_widget = p.plot_widget()
                        break
        else:
            pane = mgr.pane_for_widget(plot_widget)
        if plot_widget is None:
            self._app.status_label.setText("No docked plot to close.")
            return
        self._notify_docked_plot_closing(plot_widget)
        self._release_plot_widget_from_panel_host(plot_widget)
        try:
            plot_widget.setParent(None)
            plot_widget.deleteLater()
        except RuntimeError:
            pass
        self._app.status_label.setText("Plot closed.")

    def close_plot_pane(self, pane=None) -> None:
        """Close a workspace plot pane and delete every plot it contains."""
        mgr = self.workspace()
        if mgr is None:
            return
        if pane is None:
            pane = mgr.preferred_pane()
        if pane is None:
            self._app.status_label.setText("No plot pane to close.")
            return

        widgets = list(pane.plot_widgets())
        if widgets:
            n = len(widgets)
            noun = "plot" if n == 1 else "plots"
            reply = QMessageBox.question(
                self._app,
                "Close Plot Pane",
                f"This pane has {n} {noun}. Close the pane and discard "
                f"{'it' if n == 1 else 'them'}?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return

        for plot_widget in widgets:
            self._notify_docked_plot_closing(plot_widget)
            self._release_plot_widget_from_panel_host(plot_widget)
            try:
                plot_widget.hide()
                plot_widget.setParent(None)
                plot_widget.deleteLater()
            except RuntimeError:
                pass

        if not mgr.remove_pane(pane):
            self._app.status_label.setText("Could not close plot pane.")
            return

        self._apply_plot_panel_minimum_width()
        remaining = len(mgr.plot_panes())
        if remaining:
            self._app.status_label.setText(
                f"Plot pane closed ({len(widgets)} plot(s) removed). {remaining} pane(s) remain."
            )
        else:
            self._app.status_label.setText(
                f"Plot pane closed ({len(widgets)} plot(s) removed). Table-only layout."
            )

    def _release_plot_widget_from_panel_host(self, plot_widget) -> None:
        mgr = self.workspace()
        if mgr is not None:
            mgr.release_widget(plot_widget)
        teardown = getattr(plot_widget, "_scope_sync_disconnect", None)
        if callable(teardown):
            teardown()
        sync_footer = getattr(plot_widget, "_sync_footer_chrome", None)
        if callable(sync_footer):
            try:
                sync_footer()
            except RuntimeError:
                pass
        self._apply_plot_panel_minimum_width()

    def _notify_docked_plot_closing(self, plot_widget) -> None:
        closing = getattr(plot_widget, "on_docked_plot_closing", None)
        if not callable(closing):
            return
        try:
            closing()
        except RuntimeError:
            pass

    def undock_plot_to_window(self, plot_widget=None) -> bool:
        """Move a docked plot into a floating window."""
        mgr = self.workspace()
        if mgr is None:
            return False
        if plot_widget is None:
            pane = mgr.preferred_pane()
            plot_widget = pane.plot_widget() if pane is not None else None
            if plot_widget is None:
                for p in mgr.plot_panes():
                    if p.plot_widget() is not None:
                        plot_widget = p.plot_widget()
                        break
        if plot_widget is None:
            return False

        factory = getattr(plot_widget, "create_floating_dialog", None)
        if callable(factory):
            self._release_plot_widget_from_panel_host(plot_widget)
            dlg = factory(self._app)
            self._app._prepare_tool_dialog(dlg)
            if not self._app._bind_undocked_browser_dialog(dlg):
                plot_dialog_cls, _plot_cls = _plot_dialog_and_widget_types()
                if plot_dialog_cls is not None and isinstance(dlg, plot_dialog_cls):
                    self._app._register_plot_dialog(dlg)
                else:
                    self._app._register_floating_result_dialog(dlg)
            plot_widget.show()
            dlg.show()
            dlg.raise_()
            dlg.activateWindow()
            sync_footer = getattr(plot_widget, "_sync_footer_chrome", None)
            if callable(sync_footer):
                sync_footer()
            kind = self._docked_widget_kind(plot_widget)
            self._app.status_label.setText(f"{kind}: moved to separate window.")
            mark = getattr(self._app, "_mark_session_dirty", None)
            if callable(mark):
                mark()
            return True

        _dialog_cls, plot_cls = _plot_dialog_and_widget_types()
        if plot_cls is None or not isinstance(plot_widget, plot_cls):
            self._release_plot_widget_from_panel_host(plot_widget)
            return False

        from .plot import PlotDialog

        self._release_plot_widget_from_panel_host(plot_widget)
        dlg = PlotDialog(self._app, plot_widget=plot_widget)
        self._app._register_plot_dialog(dlg)
        self._app._prepare_tool_dialog(dlg)
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()
        self._app.status_label.setText("Plot: moved to separate window.")
        mark = getattr(self._app, "_mark_session_dirty", None)
        if callable(mark):
            mark()
        return True
