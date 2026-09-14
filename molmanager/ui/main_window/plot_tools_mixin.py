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

"""Plot docking, plot↔table sync, and multi-pane workspace helpers."""

from __future__ import annotations

import logging

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import QDialog, QMessageBox

logger = logging.getLogger(__name__)


class PlotToolsMixin:
    def _workspace(self):
        return getattr(self, "_workspace_layout", None)

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
        mgr = self._workspace()
        if mgr is None:
            return
        yield from mgr.iter_docked_widgets()

    def pane_for_plot_widget(self, plot_widget):
        mgr = self._workspace()
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
        mgr = self._workspace()
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
        mgr = self._workspace()
        if mgr is None:
            return
        pane = mgr.preferred_pane() or (mgr.plot_panes()[0] if mgr.plot_panes() else None)
        if pane is not None:
            mgr.dock_into_pane(pane, value)

    def _plot_panel_splitter_sizes(self) -> list[int] | None:
        """Outer table|plots sizes when the workspace uses a horizontal outer splitter."""
        mgr = self._workspace()
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
        from ..dockable_plot import (
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
        from ..dockable_plot import PLOT_PANEL_BASE_MINIMUM_WIDTH

        mgr = self._workspace()
        if mgr is None:
            return PLOT_PANEL_BASE_MINIMUM_WIDTH
        min_w, _pref = self._docked_plot_content_widths()
        if not list(self.iter_docked_plot_widgets()):
            min_w = PLOT_PANEL_BASE_MINIMUM_WIDTH
        return min_w

    def _ensure_plot_panel_width(self, preferred: int | None = None) -> None:
        """Give the plot region a usable width when the outer splitter is horizontal."""
        from ..dockable_plot import PLOT_PANEL_COLLAPSED_WIDTH

        mgr = self._workspace()
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

    def _sync_dialog_only_selected_scope(
        self, dialog: QDialog, *, selected_count: int | None = None
    ) -> None:
        """Refresh a tool dialog's scope checkbox label/count from the current table selection."""
        cb = getattr(dialog, "only_selected_cb", None)
        if cb is None:
            return
        try:
            from PyQt5 import sip

            if sip.isdeleted(cb):
                return
        except Exception:
            pass
        prefix = getattr(dialog, "_only_selected_scope_prefix", "Selected Rows Only")
        if selected_count is None:
            count_fn = getattr(self, "_selected_row_count_fast", None)
            n = int(count_fn()) if callable(count_fn) else len(self._selected_logical_rows())
        else:
            n = int(selected_count)
        try:
            if n > 0:
                cb.setEnabled(True)
                cb.setText(f"{prefix} ({n} row(s))")
            else:
                cb.setEnabled(False)
                cb.setChecked(False)
                cb.setText(prefix)
        except RuntimeError:
            return

    def _prepare_tool_dialog(self, dialog: QDialog) -> None:
        """Let the main table stay interactive and keep scope UI in sync while the dialog is open."""
        dialog.setModal(False)
        dialog.setWindowModality(Qt.NonModal)
        self._attach_tool_scope_sync(dialog, on_finished_signal=dialog.finished)

    def _prepare_tool_plot(self, plot_widget) -> None:
        """Keep docked plot scope UI in sync with table selection changes."""
        self._attach_tool_scope_sync(plot_widget, on_finished_signal=plot_widget.destroyed)

    def _iter_active_plot_selection_views(self) -> list:
        """Plot surfaces that mirror table row selection (dock, floating plotter, PCA/t-SNE)."""
        from ..dockable_plot import iter_plot_selection_views

        views: list = []
        seen: set[int] = set()

        def add_from(root) -> None:
            for view in iter_plot_selection_views(root):
                key = id(view)
                if key in seen:
                    continue
                seen.add(key)
                views.append(view)

        for docked in self.iter_docked_plot_widgets():
            add_from(docked)
        for plot_dlg in self._iter_plot_dialogs():
            pw = getattr(plot_dlg, "_plot_widget", None)
            if pw is not None:
                add_from(pw)
            else:
                add_from(plot_dlg)
        for attr in (
            "_pca_dialog",
            "_tsne_dialog",
            "_umap_dialog",
            "_som_dialog",
            "_boiled_egg_dialog",
            "_golden_triangle_dialog",
            "_sali_map_dialog",
            "_activity_cliff_map_dialog",
            "_mmp_neighborhood_map_dialog",
        ):
            dlg = getattr(self, attr, None)
            if dlg is None:
                continue
            panel = getattr(dlg, "_panel", None)
            if panel is not None:
                add_from(panel)
                continue
            add_from(dlg)
        for dlg in list(getattr(self, "_floating_result_dialogs", [])):
            try:
                from PyQt5 import sip

                if sip.isdeleted(dlg):
                    continue
            except Exception:
                pass
            panel = getattr(dlg, "_panel", None)
            if panel is not None:
                add_from(panel)
            else:
                add_from(dlg)
        return views

    def _refresh_active_plot_axis_columns(self) -> None:
        """Update plotter axis dropdowns when table columns or numeric bounds change."""
        for view in self._iter_active_plot_selection_views():
            refresh = getattr(view, "refresh_axis_columns", None) or getattr(
                view, "refresh_spoke_columns", None
            )
            if callable(refresh):
                try:
                    refresh()
                except RuntimeError:
                    pass

    def _refresh_attached_tool_scope_labels(self) -> None:
        """Update all open tool/plot scope checkboxes once per selection fan-out."""
        count_fn = getattr(self, "_selected_row_count_fast", None)
        n = int(count_fn()) if callable(count_fn) else len(self._selected_logical_rows())
        alive: list = []
        for target in list(getattr(self, "_scope_sync_targets", [])):
            try:
                from PyQt5 import sip

                if sip.isdeleted(target):
                    continue
            except Exception:
                pass
            alive.append(target)
            self._sync_dialog_only_selected_scope(target, selected_count=n)
        self._scope_sync_targets = alive

    def _sync_active_plots_from_table_selection(self) -> None:
        from ..plot_table_sync import selected_oids_for_plot

        self._refresh_attached_tool_scope_labels()
        selected = selected_oids_for_plot(self)
        # Share one OID set across every open plot for this fan-out tick.
        self._cached_plot_selected_oids = frozenset(selected)
        try:
            for view in self._iter_active_plot_selection_views():
                try:
                    sync = getattr(view, "sync_from_table_selection", None)
                    if not callable(sync):
                        continue
                    try:
                        sync(selected_oids=selected)
                    except TypeError:
                        sync()
                except RuntimeError:
                    pass
        finally:
            self._cached_plot_selected_oids = None

    def _schedule_sync_active_plots_from_table_selection(self) -> None:
        timer = getattr(self, "_plot_table_sync_timer", None)
        if timer is None:
            return
        timer.start(40)

    def _iter_active_plot_hosts(self) -> list:
        """Docked / floating plot panels that can rebuild from the current table."""
        hosts: list = []
        seen: set[int] = set()

        def add(candidate) -> None:
            if candidate is None:
                return
            key = id(candidate)
            if key in seen:
                return
            seen.add(key)
            hosts.append(candidate)

        for docked in self.iter_docked_plot_widgets():
            add(docked)
        for plot_dlg in self._iter_plot_dialogs():
            add(getattr(plot_dlg, "_plot_widget", None) or plot_dlg)
        for attr in (
            "_pca_dialog",
            "_tsne_dialog",
            "_umap_dialog",
            "_som_dialog",
            "_boiled_egg_dialog",
            "_golden_triangle_dialog",
            "_sali_map_dialog",
            "_activity_cliff_map_dialog",
            "_mmp_neighborhood_map_dialog",
        ):
            dlg = getattr(self, attr, None)
            if dlg is None:
                continue
            add(getattr(dlg, "_panel", None) or dlg)
        for dlg in list(getattr(self, "_floating_result_dialogs", [])):
            add(getattr(dlg, "_panel", None) or dlg)
        return hosts

    def _replot_active_plots(self) -> None:
        """Refresh plot data after filters or table edits change visible rows."""
        for host in self._iter_active_plot_hosts():
            fn = getattr(host, "_schedule_plot", None) or getattr(host, "_rebuild_figure", None)
            if not callable(fn):
                continue
            try:
                fn()
            except RuntimeError:
                pass

    def _schedule_active_plots_replot(self, *, delay_ms: int = 80, force: bool = False) -> None:
        if (
            not force
            and getattr(self, "_background_job_ui_active", None)
            and self._background_job_ui_active()
        ):
            return
        timer = getattr(self, "_plot_replot_timer", None)
        if timer is None:
            return
        timer.start(max(0, int(delay_ms)))

    def _prune_plot_dialogs(self) -> None:
        alive: list = []
        for dlg in getattr(self, "_plot_dialogs", []):
            try:
                dlg.isVisible()
                alive.append(dlg)
            except RuntimeError:
                pass
        self._plot_dialogs = alive

    def _iter_plot_dialogs(self) -> list:
        self._prune_plot_dialogs()
        return list(self._plot_dialogs)

    def _register_plot_dialog(self, dlg) -> None:
        """Track a floating plotter window (multiple instances allowed)."""
        if not hasattr(self, "_plot_dialogs"):
            self._plot_dialogs = []
        self._prune_plot_dialogs()
        self._plot_dialogs.append(dlg)
        panel = getattr(dlg, "_plot_widget", None)
        custom = getattr(panel, "_pane_display_title", None) if panel is not None else None
        if isinstance(custom, str) and custom.strip():
            dlg.setWindowTitle(custom.strip())
        else:
            n = len(self._plot_dialogs)
            dlg.setWindowTitle("Plot Data" if n == 1 else f"Plot Data ({n})")
        dlg.destroyed.connect(lambda *_a, d=dlg: self._unregister_plot_dialog(d))

    def _unregister_plot_dialog(self, dlg) -> None:
        try:
            self._plot_dialogs.remove(dlg)
        except (ValueError, AttributeError):
            pass
        self._prune_plot_dialogs()

    def _create_plot_dialog(self):
        from ..plot import PlotDialog

        d = PlotDialog(self)
        self._prepare_tool_dialog(d)
        return d

    def _attach_tool_scope_sync(self, target, *, on_finished_signal) -> None:
        """Wire table selection changes to a dialog/plot ``only_selected_cb`` until teardown."""
        if getattr(target, "only_selected_cb", None) is None:
            return
        prior = getattr(target, "_scope_sync_disconnect", None)
        if callable(prior):
            prior()
        if not hasattr(self, "_scope_sync_targets"):
            self._scope_sync_targets = []
        if target not in self._scope_sync_targets:
            self._scope_sync_targets.append(target)
        self._sync_dialog_only_selected_scope(target)
        sm = self.table.selectionModel()
        if sm is None:
            return

        def on_sel_changed(*_args):
            # Scope labels refresh once in the coalesced plot fan-out (avoids N× row scans).
            self._schedule_sync_active_plots_from_table_selection()

        sm.selectionChanged.connect(on_sel_changed)

        def teardown(*_args):
            try:
                from PyQt5 import sip

                if sm is not None and not sip.isdeleted(sm):
                    sm.selectionChanged.disconnect(on_sel_changed)
            except (TypeError, RuntimeError):
                pass
            try:
                self._scope_sync_targets.remove(target)
            except (ValueError, AttributeError):
                pass
            target._scope_sync_disconnect = None

        on_finished_signal.connect(teardown)
        target._scope_sync_disconnect = teardown

    def _target_plot_pane(self):
        """Return the active plot pane, expanding Table Only to a table|plot split."""
        from .workspace_layout import LAYOUT_TABLE_SINGLE

        mgr = self._workspace()
        if mgr is None:
            return None
        if mgr.plot_panes():
            return mgr.preferred_pane()
        # No panes (Table Only): split the table with a single plot pane.
        self.apply_workspace_layout(LAYOUT_TABLE_SINGLE)
        panes = mgr.plot_panes()
        if not panes:
            return None
        pane = panes[0]
        mgr.set_preferred_pane(pane)
        return pane

    def dock_plot_widget(self, plot_widget, pane=None) -> bool:
        """Move a plot or viewer widget into the active workspace plot pane."""
        from ..dockable_plot import is_dockable_workspace_widget
        from ..plot import PlotWidget

        if not is_dockable_workspace_widget(plot_widget) and not isinstance(
            plot_widget, PlotWidget
        ):
            return False
        mgr = self._workspace()
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
            self.status_label.setText(
                f"{kind}: docked in pane {pane_n} ({target.page_index() + 1}/{n_pages})."
            )
        else:
            self.status_label.setText(f"{kind}: docked in pane {pane_n}.")
        mark = getattr(self, "_mark_session_dirty", None)
        if callable(mark):
            mark()
        return True

    def _wire_docked_plot_widget(self, plot_widget) -> None:
        """Attach session/scope hooks used for any docked plot or viewer."""
        self._prepare_tool_plot(plot_widget)
        try:
            plot_widget.destroyed.disconnect(self._on_docked_plot_destroyed)
        except (TypeError, RuntimeError):
            pass
        plot_widget.destroyed.connect(self._on_docked_plot_destroyed)
        self._sync_active_plots_from_table_selection()
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
                dlg = factory(self)
                self._prepare_tool_dialog(dlg)
                if hasattr(dlg, "_plot_widget") or hasattr(dlg, "_panel"):
                    pass
                from ..plot import PlotDialog

                if isinstance(dlg, PlotDialog):
                    self._register_plot_dialog(dlg)
                elif not self._bind_undocked_browser_dialog(dlg):
                    self._register_floating_result_dialog(dlg)
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

    def _bind_undocked_browser_dialog(self, dlg) -> bool:
        """Track Data → Browser / Predict SOM windows after undock. Return True if handled."""
        from ..selection_browser import SelectionBrowserDialog
        from ..som_browser import SomBrowserDialog

        if isinstance(dlg, SelectionBrowserDialog):
            self._selection_browser_dialog = dlg
            try:
                dlg.destroyed.connect(self._on_selection_browser_dialog_destroyed)
            except Exception:
                pass
            return True
        if isinstance(dlg, SomBrowserDialog):
            self._som_browser_dialog = dlg
            try:
                dlg.destroyed.connect(self._on_som_browser_dialog_destroyed)
            except Exception:
                pass
            return True
        return False

    def _register_floating_result_dialog(self, dlg) -> None:
        """Track undocked SALI/cliff/MMP/etc. windows for table↔plot selection sync."""
        if not hasattr(self, "_floating_result_dialogs"):
            self._floating_result_dialogs = []
        alive: list = []
        for existing in self._floating_result_dialogs:
            try:
                from PyQt5 import sip

                if sip.isdeleted(existing):
                    continue
            except Exception:
                pass
            alive.append(existing)
        if dlg not in alive:
            alive.append(dlg)
            try:
                dlg.destroyed.connect(lambda *_a, d=dlg: self._unregister_floating_result_dialog(d))
            except Exception:
                pass
        self._floating_result_dialogs = alive

    def _unregister_floating_result_dialog(self, dlg) -> None:
        try:
            self._floating_result_dialogs.remove(dlg)
        except (ValueError, AttributeError):
            pass

    def _sync_plot_panel_bottom_visibility(self) -> None:
        """No shared host bottom bar in multi-pane layout."""
        return

    def show_docked_plot_panel(self) -> None:
        """Ensure the workspace plot region has usable width."""
        mgr = self._workspace()
        if mgr is not None:
            mgr.show()
        # Session restore owns splitter sizes; do not fight them with auto-grow.
        if getattr(self, "_pending_session_workspace_layout", None):
            return
        QTimer.singleShot(0, self._ensure_plot_panel_width)

    def hide_docked_plot_panel(self) -> None:
        """Collapse plot region width on horizontal layouts (table keeps space)."""
        mgr = self._workspace()
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
        mgr = self._workspace()
        if mgr is None:
            return
        for pane in mgr.plot_panes():
            for w in list(pane.plot_widgets()):
                try:
                    from PyQt5 import sip

                    if sip.isdeleted(w):
                        pane.remove_plot_widget(w)
                except Exception:
                    pass

    def close_plot_panel_keep_plot(self) -> None:
        """Hide/collapse the plot region; docked widgets are preserved."""
        self.hide_docked_plot_panel()
        self.status_label.setText("Plot panel hidden.")

    def close_docked_plot(self, plot_widget=None, *, confirm: bool = True) -> None:
        """Close a docked plot (``plot_widget`` or the preferred/occupied pane)."""
        mgr = self._workspace()
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
            self.status_label.setText("No docked plot to close.")
            return
        self._release_plot_widget_from_panel_host(plot_widget)
        try:
            plot_widget.setParent(None)
            plot_widget.deleteLater()
        except RuntimeError:
            pass
        self.status_label.setText("Plot closed.")

    def close_plot_pane(self, pane=None) -> None:
        """Close a workspace plot pane and delete every plot it contains."""
        mgr = self._workspace()
        if mgr is None:
            return
        if pane is None:
            pane = mgr.preferred_pane()
        if pane is None:
            self.status_label.setText("No plot pane to close.")
            return

        widgets = list(pane.plot_widgets())
        if widgets:
            n = len(widgets)
            noun = "plot" if n == 1 else "plots"
            reply = QMessageBox.question(
                self,
                "Close Plot Pane",
                f"This pane has {n} {noun}. Close the pane and discard "
                f"{'it' if n == 1 else 'them'}?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return

        for plot_widget in widgets:
            self._release_plot_widget_from_panel_host(plot_widget)
            try:
                plot_widget.setParent(None)
                plot_widget.deleteLater()
            except RuntimeError:
                pass

        if not mgr.remove_pane(pane):
            self.status_label.setText("Could not close plot pane.")
            return

        self._apply_plot_panel_minimum_width()
        remaining = len(mgr.plot_panes())
        if remaining:
            self.status_label.setText(
                f"Plot pane closed ({len(widgets)} plot(s) removed). {remaining} pane(s) remain."
            )
        else:
            self.status_label.setText(
                f"Plot pane closed ({len(widgets)} plot(s) removed). Table-only layout."
            )

    def _release_plot_widget_from_panel_host(self, plot_widget) -> None:
        mgr = self._workspace()
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

    def undock_plot_to_window(self, plot_widget=None) -> bool:
        """Move a docked plot into a floating window."""
        from ..plot import PlotDialog, PlotWidget

        mgr = self._workspace()
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
            dlg = factory(self)
            self._prepare_tool_dialog(dlg)
            if isinstance(dlg, PlotDialog):
                self._register_plot_dialog(dlg)
            elif not self._bind_undocked_browser_dialog(dlg):
                self._register_floating_result_dialog(dlg)
            plot_widget.show()
            dlg.show()
            dlg.raise_()
            dlg.activateWindow()
            sync_footer = getattr(plot_widget, "_sync_footer_chrome", None)
            if callable(sync_footer):
                sync_footer()
            kind = self._docked_widget_kind(plot_widget)
            self.status_label.setText(f"{kind}: moved to separate window.")
            mark = getattr(self, "_mark_session_dirty", None)
            if callable(mark):
                mark()
            return True

        if not isinstance(plot_widget, PlotWidget):
            self._release_plot_widget_from_panel_host(plot_widget)
            return False

        self._release_plot_widget_from_panel_host(plot_widget)
        dlg = PlotDialog(self, plot_widget=plot_widget)
        self._register_plot_dialog(dlg)
        self._prepare_tool_dialog(dlg)
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()
        self.status_label.setText("Plot: moved to separate window.")
        mark = getattr(self, "_mark_session_dirty", None)
        if callable(mark):
            mark()
        return True
