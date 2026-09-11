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

"""Multi-pane workspace layouts: fixed-left table + configurable plot panes."""

from __future__ import annotations

from typing import Callable

from PyQt5.QtCore import QEvent, QObject, Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStackedLayout,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..dockable_plot import (
    PLOT_PANEL_BASE_MINIMUM_WIDTH,
    PLOT_PANEL_DEFAULT_WIDTH,
    adopt_dock_header_buttons,
    embed_in_plot_pane,
    plot_widget_display_title,
    restore_dock_header_buttons,
    style_plot_pane_title_edit,
    unembed_from_plot_pane,
)

LAYOUT_TABLE_ONLY = "table_only"
LAYOUT_TABLE_SINGLE = "table_single"
LAYOUT_TABLE_STACK = "table_stack"
LAYOUT_TABLE_SIDE = "table_side"
LAYOUT_QUADRANTS = "quadrants"
LAYOUT_TABLE_GRID = "table_grid"
DEFAULT_LAYOUT_ID = LAYOUT_TABLE_ONLY

LAYOUT_PRESETS: tuple[tuple[str, str], ...] = (
    (LAYOUT_TABLE_ONLY, "Table Only"),
    (LAYOUT_TABLE_SINGLE, "Table | 1 plot"),
    (LAYOUT_TABLE_STACK, "Table | 2 stacked plots"),
    (LAYOUT_TABLE_SIDE, "Table | 2 side-by-side plots"),
    (LAYOUT_QUADRANTS, "Quadrants (table upper-left)"),
    (LAYOUT_TABLE_GRID, "Grid 2×3 (table upper-left)"),
)


class _PaneActivateFilter(QObject):
    """Forward mouse presses on a docked plot to activate its host pane."""

    def __init__(self, pane: "PlotPane"):
        super().__init__(pane)
        self._pane = pane

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 — Qt API
        if event.type() == QEvent.MouseButtonPress:
            self._pane.activated.emit(self._pane)
        return False


class PlotPane(QFrame):
    """Host for one or more docked plot widgets, with pager chrome when stacked."""

    activated = pyqtSignal(object)  # PlotPane
    close_requested = pyqtSignal(object)  # PlotPane

    def __init__(self, pane_id: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.pane_id = pane_id
        self._pages: list[QWidget] = []
        self._activate_filter = _PaneActivateFilter(self)
        self.setObjectName("PlotPane")
        # Border width is owned by the stylesheet; avoid QFrame chrome fighting it.
        self.setFrameShape(QFrame.NoFrame)
        self.setMinimumWidth(PLOT_PANEL_BASE_MINIMUM_WIDTH // 2)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(2, 2, 2, 2)
        self._root.setSpacing(0)

        self._nav_host = QWidget()
        self._nav_host.setObjectName("PlotPaneNav")
        nav_ly = QHBoxLayout(self._nav_host)
        nav_ly.setContentsMargins(0, 0, 0, 0)
        nav_ly.setSpacing(3)
        self._prev_btn = QPushButton("‹")
        self._next_btn = QPushButton("›")
        for btn in (self._prev_btn, self._next_btn):
            btn.setFixedSize(22, 20)
            btn.setFlat(False)
            btn.setAutoDefault(False)
            btn.setDefault(False)
            btn.setFocusPolicy(Qt.NoFocus)
            btn.setStyleSheet(
                "QPushButton { font-size: 13px; font-weight: 700; padding: 0px; min-width: 22px; }"
            )
        self._prev_btn.setToolTip("Previous plot in this pane")
        self._next_btn.setToolTip("Next plot in this pane")
        self._prev_btn.clicked.connect(self.show_previous_page)
        self._next_btn.clicked.connect(self.show_next_page)
        self._title_edit = QLineEdit()
        self._title_edit.setObjectName("PlotPaneTitle")
        self._title_edit.setReadOnly(True)
        self._title_edit.setFocusPolicy(Qt.ClickFocus)
        self._title_edit.setToolTip("Double-click to rename this plot")
        style_plot_pane_title_edit(self._title_edit)
        self._title_edit.installEventFilter(self)
        self._title_edit.editingFinished.connect(self._commit_title_edit)
        # Compatibility alias for older tests/callers.
        self._title_label = self._title_edit
        self._page_label = QLabel("")
        self._page_label.setObjectName("PlotPanePage")
        self._page_label.setAlignment(Qt.AlignCenter)
        self._page_label.setFixedWidth(38)
        self._page_label.setStyleSheet("QLabel { font-size: 11px; padding: 0px 1px; }")
        nav_ly.addWidget(self._prev_btn)
        nav_ly.addWidget(self._title_edit)
        nav_ly.addWidget(self._page_label)
        nav_ly.addWidget(self._next_btn)
        # Compatibility alias used by older tests.
        self._pager = self._nav_host

        # Header: equal side strips keep the pager geometrically centered in the pane.
        self._header = QWidget()
        self._header.setObjectName("PlotPaneHeader")
        self._header.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        header_ly = QHBoxLayout(self._header)
        header_ly.setContentsMargins(3, 1, 3, 1)
        header_ly.setSpacing(3)

        self._header_left = QWidget()
        self._header_left.setObjectName("PlotPaneHeaderLeft")
        left_ly = QHBoxLayout(self._header_left)
        left_ly.setContentsMargins(0, 0, 0, 0)
        left_ly.setSpacing(3)
        self._leading_opts_host = QWidget()
        self._leading_opts_host.setObjectName("PlotPaneLeadingOpts")
        self._leading_opts_ly = QHBoxLayout(self._leading_opts_host)
        self._leading_opts_ly.setContentsMargins(0, 0, 0, 0)
        self._leading_opts_ly.setSpacing(3)
        left_ly.addWidget(self._leading_opts_host, 0)
        self._chrome_host = QWidget()
        self._chrome_host.setObjectName("PlotPaneChrome")
        self._chrome_ly = QHBoxLayout(self._chrome_host)
        self._chrome_ly.setContentsMargins(0, 0, 0, 0)
        self._chrome_ly.setSpacing(3)
        left_ly.addWidget(self._chrome_host, 0)
        left_ly.addStretch(1)

        self._header_right = QWidget()
        self._header_right.setObjectName("PlotPaneHeaderRight")
        right_ly = QHBoxLayout(self._header_right)
        right_ly.setContentsMargins(0, 0, 0, 0)
        right_ly.setSpacing(3)
        right_ly.addStretch(1)
        self._send_host = QWidget()
        self._send_host.setObjectName("PlotPaneSend")
        self._send_ly = QHBoxLayout(self._send_host)
        self._send_ly.setContentsMargins(0, 0, 0, 0)
        self._send_ly.setSpacing(3)
        right_ly.addWidget(self._send_host, 0)
        self._trailing_close_host = QWidget()
        self._trailing_close_host.setObjectName("PlotPaneTrailingClose")
        self._trailing_close_ly = QHBoxLayout(self._trailing_close_host)
        self._trailing_close_ly.setContentsMargins(0, 0, 0, 0)
        self._trailing_close_ly.setSpacing(3)
        right_ly.addWidget(self._trailing_close_host, 0)
        self._close_btn = QPushButton("×")
        self._close_btn.setObjectName("PlotPaneClose")
        self._close_btn.setFixedSize(20, 20)
        self._close_btn.setFlat(False)
        self._close_btn.setFocusPolicy(Qt.NoFocus)
        self._close_btn.setAutoDefault(False)
        self._close_btn.setDefault(False)
        self._close_btn.setToolTip("Close this plot pane")
        self._close_btn.setStyleSheet(
            "QPushButton {"
            " color: #c0392b;"
            " font-size: 13px;"
            " font-weight: 700;"
            " padding: 0px;"
            " }"
            "QPushButton:hover { color: #e74c3c; }"
            "QPushButton:pressed { color: #922b21; }"
        )
        self._close_btn.clicked.connect(lambda *_a: self.close_requested.emit(self))
        right_ly.addWidget(self._close_btn, 0)

        header_ly.addWidget(self._header_left, 1)
        header_ly.addWidget(self._nav_host, 0)
        header_ly.addWidget(self._header_right, 1)
        # Alias so callers/tests that still look at ``_footer`` find the chrome bar.
        self._footer = self._header
        self._root.addWidget(self._header)

        self._stack = QStackedWidget()
        self._stack.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        stack_ly = self._stack.layout()
        if stack_ly is not None and hasattr(stack_ly, "setSizeAdjustPolicy"):
            stack_ly.setSizeAdjustPolicy(QStackedLayout.AdjustIgnored)
        self._stack.currentChanged.connect(self._on_stack_current_changed)
        self._stack.hide()

        self._placeholder = QLabel("Plot pane\n(Add to Main Window…)")
        self._placeholder.setAlignment(Qt.AlignCenter)
        self._placeholder.setWordWrap(True)
        self._placeholder.setStyleSheet("color: palette(mid); padding: 12px;")
        self._root.addWidget(self._stack, 1)
        self._root.addWidget(self._placeholder, 1)
        self._header_button_owner = None
        self._title_edit_base = ""

        self._active = False
        self._set_active_style(False)
        self._refresh_pager()

    def refresh_theme(self) -> None:
        """Re-apply palette-backed chrome after a GUI theme or application font change."""
        self._set_active_style(self._active)
        self._placeholder.setStyleSheet("color: palette(mid); padding: 12px;")
        app = QApplication.instance()
        if app is not None:
            font = app.font()
            pal = app.palette()
            self.setPalette(pal)
            for widget in (
                self._header,
                self._footer,
                self._header_left,
                self._header_right,
                self._leading_opts_host,
                self._chrome_host,
                self._send_host,
                self._trailing_close_host,
                self._nav_host,
                self._close_btn,
                self._prev_btn,
                self._next_btn,
                self._title_edit,
                self._page_label,
                self._placeholder,
            ):
                widget.setPalette(pal)
                widget.setFont(font)
                style = widget.style()
                if style is not None:
                    style.unpolish(widget)
                    style.polish(widget)
                widget.update()
        for btn in (self._prev_btn, self._next_btn):
            btn.setFixedSize(22, 20)
            btn.setStyleSheet(
                "QPushButton { font-size: 13px; font-weight: 700; padding: 0px; min-width: 22px; }"
            )
        style_plot_pane_title_edit(self._title_edit)
        self.update()

    def plot_widget(self) -> QWidget | None:
        """Currently visible plot in this pane."""
        if not self._pages:
            return None
        current = self._stack.currentWidget()
        if current in self._pages:
            return current
        return self._pages[-1]

    def plot_widgets(self) -> list[QWidget]:
        """All plots hosted in this pane (visible first is not required)."""
        return list(self._pages)

    def page_count(self) -> int:
        return len(self._pages)

    def page_index(self) -> int:
        if not self._pages:
            return -1
        idx = int(self._stack.currentIndex())
        if 0 <= idx < len(self._pages):
            return idx
        return len(self._pages) - 1

    def is_empty(self) -> bool:
        return not self._pages

    def display_title(self) -> str:
        return plot_widget_display_title(self.plot_widget())

    @staticmethod
    def _title_for_widget(w: QWidget | None) -> str:
        return plot_widget_display_title(w)

    def eventFilter(self, obj, event):  # noqa: N802 — Qt API name
        if obj is self._title_edit and event.type() == QEvent.MouseButtonDblClick:
            if event.button() == Qt.LeftButton and self.plot_widget() is not None:
                self._begin_title_edit()
                return True
        if obj is self._title_edit and event.type() == QEvent.KeyPress:
            if event.key() == Qt.Key_Escape and not self._title_edit.isReadOnly():
                self._cancel_title_edit()
                return True
        return super().eventFilter(obj, event)

    def _begin_title_edit(self) -> None:
        self._title_edit_base = self._title_for_widget(self.plot_widget())
        self._title_edit.blockSignals(True)
        self._title_edit.setText(self._title_edit_base)
        self._title_edit.blockSignals(False)
        self._title_edit.setReadOnly(False)
        self._title_edit.setFocus(Qt.MouseFocusReason)
        self._title_edit.selectAll()

    def _cancel_title_edit(self) -> None:
        self._title_edit.blockSignals(True)
        self._title_edit.setText(self._title_edit_base)
        self._title_edit.blockSignals(False)
        self._title_edit.setReadOnly(True)
        self._title_edit.clearFocus()
        self._refresh_pager()

    def _commit_title_edit(self) -> None:
        if self._title_edit.isReadOnly():
            return
        widget = self.plot_widget()
        text = self._title_edit.text().strip()
        self._title_edit.setReadOnly(True)
        if widget is not None:
            if text:
                widget._pane_display_title = text
            elif hasattr(widget, "_pane_display_title"):
                try:
                    delattr(widget, "_pane_display_title")
                except Exception:
                    widget._pane_display_title = ""
        self._refresh_pager()

    def set_plot_widget(self, widget: QWidget | None) -> QWidget | None:
        """Replace this pane's stack with ``widget`` (or clear when ``None``)."""
        previous = self.plot_widget()
        if widget is None:
            self.set_plot_widgets([])
            return previous
        self.set_plot_widgets([widget])
        return previous if previous is not widget else None

    def set_plot_widgets(self, widgets: list[QWidget], *, current: int | None = None) -> None:
        """Replace the page stack. Detaches previous pages without deleting them."""
        current_id = None
        if current is None and self._pages:
            cur = self.plot_widget()
            current_id = id(cur) if cur is not None else None
        self._stack.blockSignals(True)
        try:
            owner = getattr(self, "_header_button_owner", None)
            if owner is not None:
                restore_dock_header_buttons(owner)
                self._header_button_owner = None
            for old in list(self._pages):
                self._uninstall_activate_filter(old)
                self._stack.removeWidget(old)
                old.setParent(None)
                unembed_from_plot_pane(old)
            self._pages = []
            for widget in widgets:
                if widget is None:
                    continue
                embed_in_plot_pane(widget)
                self._pages.append(widget)
                self._stack.addWidget(widget)
                self._install_activate_filter(widget)
            if self._pages:
                idx = 0
                if current is not None:
                    idx = max(0, min(int(current), len(self._pages) - 1))
                elif current_id is not None:
                    for i, w in enumerate(self._pages):
                        if id(w) == current_id:
                            idx = i
                            break
                self._stack.setCurrentIndex(idx)
        finally:
            self._stack.blockSignals(False)
        self._refresh_pager()
        self._sync_visible_footer()
        for widget in self._pages:
            embed_in_plot_pane(widget)

    def add_plot_widget(self, widget: QWidget) -> None:
        """Append ``widget`` and show it. If it is already here, just show it."""
        embed_in_plot_pane(widget)
        if widget in self._pages:
            self._stack.setCurrentWidget(widget)
            self._refresh_pager()
            self._sync_visible_footer()
            embed_in_plot_pane(widget)
            return
        self._pages.append(widget)
        self._stack.addWidget(widget)
        self._install_activate_filter(widget)
        self._stack.setCurrentWidget(widget)
        self._refresh_pager()
        self._sync_visible_footer()
        embed_in_plot_pane(widget)

    def remove_plot_widget(self, widget: QWidget) -> bool:
        """Detach ``widget`` from this pane. Returns True if it was present."""
        if widget not in self._pages:
            return False
        if getattr(self, "_header_button_owner", None) is widget:
            restore_dock_header_buttons(widget)
            self._header_button_owner = None
        idx = self._pages.index(widget)
        self._uninstall_activate_filter(widget)
        self._pages.remove(widget)
        self._stack.removeWidget(widget)
        try:
            widget.setParent(None)
        except RuntimeError:
            pass
        unembed_from_plot_pane(widget)
        if self._pages:
            self._stack.setCurrentIndex(min(idx, len(self._pages) - 1))
        self._refresh_pager()
        self._sync_visible_footer()
        return True

    def show_previous_page(self) -> None:
        n = len(self._pages)
        if n < 2:
            return
        self._stack.setCurrentIndex((self.page_index() - 1) % n)
        self.activated.emit(self)

    def show_next_page(self) -> None:
        n = len(self._pages)
        if n < 2:
            return
        self._stack.setCurrentIndex((self.page_index() + 1) % n)
        self.activated.emit(self)

    def set_page(self, index: int) -> None:
        if not self._pages:
            return
        self._stack.setCurrentIndex(max(0, min(int(index), len(self._pages) - 1)))

    def _on_stack_current_changed(self, _index: int) -> None:
        self._refresh_pager()
        self._sync_visible_footer()

    def _sync_visible_footer(self) -> None:
        current = self.plot_widget()
        owner = getattr(self, "_header_button_owner", None)
        if owner is not None and owner is not current:
            restore_dock_header_buttons(owner)
            self._header_button_owner = None
        if current is None:
            return
        sync = getattr(current, "_sync_footer_chrome", None)
        if callable(sync):
            try:
                sync()
            except RuntimeError:
                pass
        adopt_dock_header_buttons(
            self._chrome_ly,
            current,
            leading_opts_layout=self._leading_opts_ly,
            send_window_layout=self._send_ly,
            trailing_close_layout=self._trailing_close_ly,
        )
        self._header_button_owner = current

    def _refresh_pager(self) -> None:
        n = len(self._pages)
        self._header.show()
        if n == 0:
            owner = getattr(self, "_header_button_owner", None)
            if owner is not None:
                restore_dock_header_buttons(owner)
                self._header_button_owner = None
            self._nav_host.hide()
            self._stack.hide()
            self._placeholder.show()
            return
        self._placeholder.hide()
        self._stack.show()
        self._nav_host.show()
        multi = n > 1
        self._prev_btn.setVisible(multi)
        self._next_btn.setVisible(multi)
        self._prev_btn.setEnabled(multi)
        self._next_btn.setEnabled(multi)
        title = self._title_for_widget(self.plot_widget())
        editing = not self._title_edit.isReadOnly() and self._title_edit.hasFocus()
        if not editing:
            self._title_edit.blockSignals(True)
            self._title_edit.setText(title)
            self._title_edit.blockSignals(False)
        if multi:
            i = self.page_index()
            tip = f"Plot {i + 1} of {n}"
            self._page_label.setText(f"({i + 1}/{n})")
            self._page_label.setVisible(True)
            self._prev_btn.setToolTip(f"Previous plot ({tip})")
            self._next_btn.setToolTip(f"Next plot ({tip})")
        else:
            self._page_label.clear()
            self._page_label.setVisible(False)
            self._prev_btn.setToolTip("Previous plot in this pane")
            self._next_btn.setToolTip("Next plot in this pane")
        self._title_edit.setToolTip(f"{title}\nDouble-click to rename")

    def _install_activate_filter(self, widget: QWidget) -> None:
        widget.installEventFilter(self._activate_filter)
        for child in widget.findChildren(QWidget):
            child.installEventFilter(self._activate_filter)

    def _uninstall_activate_filter(self, widget: QWidget) -> None:
        try:
            widget.removeEventFilter(self._activate_filter)
        except RuntimeError:
            pass
        try:
            for child in widget.findChildren(QWidget):
                try:
                    child.removeEventFilter(self._activate_filter)
                except RuntimeError:
                    pass
        except RuntimeError:
            pass

    def clear_plot_widget(self) -> QWidget | None:
        """Remove the currently visible plot; other pages stay."""
        current = self.plot_widget()
        if current is None:
            return None
        self.remove_plot_widget(current)
        return current

    def set_active(self, active: bool) -> None:
        self._active = bool(active)
        self._set_active_style(self._active)

    def _set_active_style(self, active: bool) -> None:
        # Keep border width identical so activating a pane does not resize Plotly.
        color = "palette(highlight)" if active else "palette(mid)"
        self.setStyleSheet(f"QFrame#PlotPane {{ border: 2px solid {color}; border-radius: 2px; }}")

    def mousePressEvent(self, event) -> None:  # noqa: N802 — Qt API
        self.activated.emit(self)
        super().mousePressEvent(event)


class WorkspaceLayoutManager(QWidget):
    """Owns the content splitter tree: table region + plot panes."""

    layout_changed = pyqtSignal(str)
    pane_close_requested = pyqtSignal(object)  # PlotPane

    def __init__(self, table_area: QWidget, parent: QWidget | None = None):
        super().__init__(parent)
        self._table_area = table_area
        self._layout_id = DEFAULT_LAYOUT_ID
        self._panes: list[PlotPane] = []
        self._preferred_pane_id: str | None = None
        self._splitters: list[QSplitter] = []
        self._root_ly = QVBoxLayout(self)
        self._root_ly.setContentsMargins(0, 0, 0, 0)
        self._root_ly.setSpacing(0)
        self._workspace_root: QWidget | None = None
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.apply_layout(DEFAULT_LAYOUT_ID, preserve_plots=False)

    @property
    def layout_id(self) -> str:
        return self._layout_id

    def plot_panes(self) -> list[PlotPane]:
        return list(self._panes)

    def preferred_pane(self) -> PlotPane | None:
        if not self._panes:
            return None
        if self._preferred_pane_id:
            for p in self._panes:
                if p.pane_id == self._preferred_pane_id:
                    return p
        for p in self._panes:
            if p.is_empty():
                return p
        return self._panes[0]

    def set_preferred_pane(self, pane: PlotPane | None) -> None:
        self._preferred_pane_id = pane.pane_id if pane is not None else None
        for p in self._panes:
            p.set_active(p is pane)

    def refresh_theme(self) -> None:
        """Refresh plot pane selection outlines and pager fonts for the current GUI theme."""
        pref = self.preferred_pane()
        for pane in self._panes:
            pane.refresh_theme()
            pane.set_active(pane is pref)

    def pane_for_widget(self, widget: QWidget | None) -> PlotPane | None:
        if widget is None:
            return None
        for p in self._panes:
            if widget in p.plot_widgets():
                return p
        return None

    def iter_docked_widgets(self):
        for p in self._panes:
            yield from p.plot_widgets()

    def find_pane(self, pane_id: str) -> PlotPane | None:
        for p in self._panes:
            if p.pane_id == pane_id:
                return p
        return None

    def dock_into_pane(self, pane: PlotPane, widget: QWidget) -> QWidget | None:
        """Dock ``widget`` into ``pane`` (appends; does not replace other plots)."""
        snapshot = self.collect_splitter_sizes()
        previous = pane.plot_widget()
        other = self.pane_for_widget(widget)
        if other is not None and other is not pane:
            other.remove_plot_widget(widget)
        pane.add_plot_widget(widget)
        self.restore_splitter_sizes(snapshot)
        self.set_preferred_pane(pane)
        return previous if previous is not widget else None

    def release_widget(self, widget: QWidget) -> bool:
        pane = self.pane_for_widget(widget)
        if pane is None:
            return False
        return pane.remove_plot_widget(widget)

    def collect_splitter_sizes(self) -> dict:
        """Serializable nested splitter sizes for the current layout."""
        sizes: dict[str, list[int]] = {}
        ratios: dict[str, list[float]] = {}
        for i, sp in enumerate(self._splitters):
            try:
                vals = [int(s) for s in sp.sizes()]
            except RuntimeError:
                continue
            key = f"splitter_{i}"
            sizes[key] = vals
            total = float(sum(vals)) or 1.0
            ratios[key] = [float(v) / total for v in vals]
        return {
            "layout_id": self._layout_id,
            "sizes": sizes,
            "ratios": ratios,
            "preferred_pane_id": self._preferred_pane_id,
        }

    def restore_splitter_sizes(self, payload: dict | None) -> None:
        if not isinstance(payload, dict):
            return
        lid = payload.get("layout_id")
        # Sizes are layout-shaped; never apply a side-by-side snapshot onto stacked panes.
        if isinstance(lid, str) and lid and lid != self._layout_id:
            return
        sizes_map = payload.get("sizes")
        ratios_map = payload.get("ratios")
        if not isinstance(sizes_map, dict):
            sizes_map = {}
        if not isinstance(ratios_map, dict):
            ratios_map = {}
        for i, sp in enumerate(self._splitters):
            key = f"splitter_{i}"
            try:
                count = int(sp.count())
            except RuntimeError:
                continue
            applied = False
            ratios = ratios_map.get(key)
            if isinstance(ratios, list) and len(ratios) == count and count > 0:
                try:
                    orient = sp.orientation()
                    span = int(sp.width() if orient == Qt.Horizontal else sp.height())
                    if span <= 0:
                        span = int(sum(int(s) for s in sp.sizes()))
                    if span > 0:
                        floats = [max(0.0, float(r)) for r in ratios]
                        rsum = sum(floats) or 1.0
                        floats = [r / rsum for r in floats]
                        ints = [max(0, int(round(r * span))) for r in floats]
                        drift = span - sum(ints)
                        if ints:
                            ints[-1] = max(0, ints[-1] + drift)
                        sp.setSizes(ints)
                        applied = True
                except (RuntimeError, TypeError, ValueError):
                    applied = False
            if applied:
                continue
            vals = sizes_map.get(key)
            if isinstance(vals, list) and len(vals) == count:
                try:
                    sp.setSizes([max(0, int(v)) for v in vals])
                except (RuntimeError, TypeError, ValueError):
                    pass
        pref_id = payload.get("preferred_pane_id")
        if isinstance(pref_id, str) and pref_id:
            pane = self.find_pane(pref_id)
            if pane is not None:
                self.set_preferred_pane(pane)

    def apply_layout(
        self,
        layout_id: str,
        *,
        preserve_plots: bool = True,
        on_extra_plot: Callable[[QWidget], None] | None = None,
    ) -> list[QWidget]:
        """
        Rebuild the workspace for ``layout_id``.

        Returns plot widgets that no longer fit (caller should undock them).
        """
        if layout_id not in {p[0] for p in LAYOUT_PRESETS}:
            layout_id = DEFAULT_LAYOUT_ID

        kept_stacks: list[tuple[list[QWidget], int]] = []
        if preserve_plots:
            for pane in self._panes:
                widgets = pane.plot_widgets()
                if widgets:
                    kept_stacks.append((widgets, pane.page_index()))

        # Detach table and plots before destroying the tree.
        self._table_area.setParent(None)
        for widgets, _idx in kept_stacks:
            for w in widgets:
                w.setParent(None)
        for p in self._panes:
            p.set_plot_widget(None)

        if self._workspace_root is not None:
            self._root_ly.removeWidget(self._workspace_root)
            self._workspace_root.setParent(None)
            self._workspace_root.deleteLater()
            self._workspace_root = None

        self._splitters.clear()
        self._panes.clear()
        self._layout_id = layout_id

        if layout_id == LAYOUT_TABLE_ONLY:
            root = self._build_table_only()
        elif layout_id == LAYOUT_QUADRANTS:
            root = self._build_quadrants()
        elif layout_id == LAYOUT_TABLE_GRID:
            root = self._build_table_grid()
        elif layout_id == LAYOUT_TABLE_SIDE:
            root = self._build_table_with_plot_area(Qt.Horizontal, 2)
        elif layout_id == LAYOUT_TABLE_SINGLE:
            root = self._build_table_with_plot_area(None, 1)
        elif layout_id == LAYOUT_TABLE_STACK:
            root = self._build_table_with_plot_area(Qt.Vertical, 2)
        else:
            self._layout_id = DEFAULT_LAYOUT_ID
            root = self._build_table_only()

        self._workspace_root = root
        self._root_ly.addWidget(root, 1)

        extras: list[QWidget] = []
        for i, (widgets, idx) in enumerate(kept_stacks):
            if i < len(self._panes):
                self._panes[i].set_plot_widgets(widgets, current=idx)
            else:
                extras.extend(widgets)
                if on_extra_plot is not None:
                    for widget in widgets:
                        on_extra_plot(widget)

        pref = self.preferred_pane()
        self.set_preferred_pane(pref)
        for p in self._panes:
            self._wire_pane(p)

        self.layout_changed.emit(self._layout_id)
        return extras

    def _splitter_containing(self, widget: QWidget) -> QSplitter | None:
        for splitter in self._splitters:
            for i in range(splitter.count()):
                if splitter.widget(i) is widget:
                    return splitter
        return None

    def remove_pane(self, pane: PlotPane) -> bool:
        """Remove a plot pane from the splitter tree (plots must already be detached)."""
        if pane not in self._panes:
            return False
        if len(self._panes) <= 1:
            pane.set_plot_widgets([])
            self._panes.remove(pane)
            if self._preferred_pane_id == pane.pane_id:
                self._preferred_pane_id = None
            pane.setParent(None)
            pane.deleteLater()
            self.apply_layout(LAYOUT_TABLE_ONLY, preserve_plots=False)
            return True

        splitter = self._splitter_containing(pane)
        if splitter is None:
            return False

        index = -1
        for i in range(splitter.count()):
            if splitter.widget(i) is pane:
                index = i
                break
        if index < 0:
            return False

        old_sizes = [int(s) for s in splitter.sizes()]
        removed_size = old_sizes[index] if index < len(old_sizes) else 0

        if self._preferred_pane_id == pane.pane_id:
            self._preferred_pane_id = None

        pane.set_plot_widgets([])
        self._panes.remove(pane)
        pane.setParent(None)
        pane.deleteLater()

        remaining = splitter.count()
        if remaining > 0 and removed_size > 0:
            new_sizes = [int(s) for s in splitter.sizes()]
            target = min(index, remaining - 1)
            new_sizes[target] = max(0, new_sizes[target] + removed_size)
            splitter.setSizes(new_sizes)

        pref = self.preferred_pane()
        self.set_preferred_pane(pref)
        return True

    def _on_pane_activated(self, pane: PlotPane) -> None:
        self.set_preferred_pane(pane)

    def _on_pane_close_requested(self, pane: PlotPane) -> None:
        self.pane_close_requested.emit(pane)

    def _wire_pane(self, pane: PlotPane) -> None:
        try:
            pane.activated.disconnect(self._on_pane_activated)
        except TypeError:
            pass
        try:
            pane.close_requested.disconnect(self._on_pane_close_requested)
        except TypeError:
            pass
        pane.activated.connect(self._on_pane_activated)
        pane.close_requested.connect(self._on_pane_close_requested)

    def _new_pane(self, index: int) -> PlotPane:
        pane = PlotPane(f"pane_{index}", self)
        self._panes.append(pane)
        self._wire_pane(pane)
        return pane

    def _track_splitter(self, splitter: QSplitter) -> QSplitter:
        self._splitters.append(splitter)
        return splitter

    def _build_table_only(self) -> QWidget:
        """Full-width table with no plot panes."""
        host = QWidget()
        ly = QVBoxLayout(host)
        ly.setContentsMargins(0, 0, 0, 0)
        ly.setSpacing(0)
        ly.addWidget(self._table_area, 1)
        return host

    def _build_table_with_plot_area(
        self, plot_orientation: Qt.Orientation | None, n_panes: int
    ) -> QWidget:
        outer = self._track_splitter(QSplitter(Qt.Horizontal))
        outer.setHandleWidth(6)
        outer.setChildrenCollapsible(False)
        outer.addWidget(self._table_area)
        if n_panes <= 1 or plot_orientation is None:
            pane = self._new_pane(0)
            outer.addWidget(pane)
            outer.setStretchFactor(0, 1)
            outer.setStretchFactor(1, 1)
            outer.setSizes([700, PLOT_PANEL_DEFAULT_WIDTH])
            return outer

        plot_split = self._track_splitter(QSplitter(plot_orientation))
        plot_split.setHandleWidth(6)
        plot_split.setChildrenCollapsible(False)
        for i in range(n_panes):
            plot_split.addWidget(self._new_pane(i))
            plot_split.setStretchFactor(i, 1)
        if plot_orientation == Qt.Vertical:
            plot_split.setSizes([400, 400])
        else:
            plot_split.setSizes([420, 420])
        outer.addWidget(plot_split)
        outer.setStretchFactor(0, 1)
        outer.setStretchFactor(1, 1)
        outer.setSizes([700, PLOT_PANEL_DEFAULT_WIDTH])
        return outer

    def _build_quadrants(self) -> QWidget:
        """Table upper-left; three plot panes in UR, LL, LR."""
        outer = self._track_splitter(QSplitter(Qt.Vertical))
        outer.setHandleWidth(6)
        outer.setChildrenCollapsible(False)

        top = self._track_splitter(QSplitter(Qt.Horizontal))
        top.setHandleWidth(6)
        top.setChildrenCollapsible(False)
        top.addWidget(self._table_area)
        top.addWidget(self._new_pane(0))
        top.setStretchFactor(0, 1)
        top.setStretchFactor(1, 1)
        top.setSizes([700, 500])

        bottom = self._track_splitter(QSplitter(Qt.Horizontal))
        bottom.setHandleWidth(6)
        bottom.setChildrenCollapsible(False)
        bottom.addWidget(self._new_pane(1))
        bottom.addWidget(self._new_pane(2))
        bottom.setStretchFactor(0, 1)
        bottom.setStretchFactor(1, 1)
        bottom.setSizes([600, 600])

        outer.addWidget(top)
        outer.addWidget(bottom)
        outer.setStretchFactor(0, 1)
        outer.setStretchFactor(1, 1)
        outer.setSizes([450, 450])
        return outer

    def _build_table_grid(self) -> QWidget:
        """Table upper-left; five plot panes in the other cells of a 2×3 grid."""
        outer = self._track_splitter(QSplitter(Qt.Vertical))
        outer.setHandleWidth(6)
        outer.setChildrenCollapsible(False)

        top = self._track_splitter(QSplitter(Qt.Horizontal))
        top.setHandleWidth(6)
        top.setChildrenCollapsible(False)
        top.addWidget(self._table_area)
        top.addWidget(self._new_pane(0))
        top.addWidget(self._new_pane(1))
        top.setStretchFactor(0, 1)
        top.setStretchFactor(1, 1)
        top.setStretchFactor(2, 1)
        top.setSizes([500, 400, 400])

        bottom = self._track_splitter(QSplitter(Qt.Horizontal))
        bottom.setHandleWidth(6)
        bottom.setChildrenCollapsible(False)
        for i in range(3):
            bottom.addWidget(self._new_pane(i + 2))
            bottom.setStretchFactor(i, 1)
        bottom.setSizes([400, 400, 400])

        outer.addWidget(top)
        outer.addWidget(bottom)
        outer.setStretchFactor(0, 1)
        outer.setStretchFactor(1, 1)
        outer.setSizes([450, 450])
        return outer
