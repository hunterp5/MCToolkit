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

"""Selection browser panel: step through table rows with structure preview."""

from __future__ import annotations

from typing import Any

from PyQt5.QtCore import QItemSelectionModel, Qt, QTimer, QEvent
from PyQt5.QtGui import QImage, QKeySequence, QPixmap
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QShortcut,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..display_constants import (
    BROWSER_STRUCTURE_PREVIEW_MIN_HEIGHT,
    BROWSER_STRUCTURE_PREVIEW_MIN_WIDTH,
)
from .compound_table_model import CompoundTableModel
from .dockable_plot import discard_host_dialog_after_dock
from .property_columns_panel import PropertyColumnsPanel
from .qt_widget_utils import make_window_minimizable
from .table_selection import item_selection_for_view_rows


class SelectionBrowserWidget(QWidget):
    """Forward/back through the current selection or entire table; shows a structure preview."""

    dockable_in_workspace = True

    def __init__(self, parent_app: Any = None, parent: QWidget | None = None):
        super().__init__(parent)
        self.parent_app = parent_app
        self._app = parent_app
        self._window_title = "Browser"

        self._rows: list[int] = []
        self._idx = 0
        self._preview_pix_cache: dict[
            tuple[int, int, int], QPixmap
        ] = {}  # (oid, w_px, h_px) -> pixmap

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        self._cb_only_selected = QCheckBox("Browse Selected")
        self._cb_only_selected.setToolTip(
            "When checked, Browser walks only the current selection.\n"
            "When unchecked, Browser walks the entire table."
        )

        self._meta = QLabel()
        self._meta.setAlignment(Qt.AlignCenter)
        root.addWidget(self._meta)

        self._struct_label = QLabel()
        self._struct_label.setAlignment(Qt.AlignCenter)
        self._struct_label.setMinimumSize(360, 260)
        self._struct_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._struct_label.setStyleSheet(
            "background-color: palette(base); border: 1px solid palette(mid); border-radius: 4px;"
        )
        root.addWidget(self._struct_label, 1)

        self._options_host = QWidget(self)
        options_ly = QVBoxLayout(self._options_host)
        options_ly.setContentsMargins(0, 0, 0, 0)
        options_ly.setSpacing(0)
        self._prop_panel = PropertyColumnsPanel(self._options_host)
        self._prop_panel.bind_app(self._app)
        options_ly.addWidget(self._prop_panel)
        root.addWidget(self._options_host)
        self._options_visible = True

        row_btns = QHBoxLayout()
        self._btn_first = QPushButton("<<")
        self._btn_first.setToolTip("First eligible row in scope (Home)")
        self._btn_back = QPushButton("← Back")
        self._btn_back.setToolTip("Previous eligible row (←)")
        self._btn_fwd = QPushButton("Forward →")
        self._btn_fwd.setToolTip("Next eligible row (→)")
        self._btn_last = QPushButton(">>")
        self._btn_last.setToolTip("Last eligible row in scope (End)")
        row_btns.addWidget(self._btn_first)
        row_btns.addWidget(self._btn_back)
        row_btns.addWidget(self._btn_fwd)
        row_btns.addWidget(self._btn_last)
        row_btns.addStretch()
        root.addLayout(row_btns)

        self._btn_toggle_select = QPushButton("Select")
        self._btn_toggle_select.setToolTip("Select or deselect this row in the table")

        foot = QHBoxLayout()
        foot.setContentsMargins(0, 4, 0, 0)
        self._add_to_main_btn = QPushButton("Add to Main Window")
        self._add_to_main_btn.setToolTip("Dock this browser beside the compound table.")
        self._add_to_main_btn.clicked.connect(self._add_to_main_window)
        foot.addWidget(self._add_to_main_btn)
        self._send_window_btn = QPushButton("Send to New Window")
        self._send_window_btn.setToolTip("Open this docked browser in a separate floating window.")
        self._send_window_btn.clicked.connect(self._send_to_new_window)
        foot.addWidget(self._send_window_btn)
        self._close_btn = QPushButton("Close Browser")
        self._close_btn.setToolTip(
            "Close this docked browser and remove it from the workspace pane."
        )
        self._close_btn.clicked.connect(self._close_docked_browser)
        foot.addWidget(self._close_btn)
        foot.addWidget(self._cb_only_selected)
        foot.addWidget(self._btn_toggle_select)
        self._toggle_options_btn = QPushButton("Hide Options")
        self._toggle_options_btn.setAutoDefault(False)
        self._toggle_options_btn.setDefault(False)
        self._toggle_options_btn.setToolTip(
            "Hide column pickers so only the structure preview and navigation controls are shown."
        )
        self._toggle_options_btn.clicked.connect(self._toggle_options_visible)
        foot.addWidget(self._toggle_options_btn)
        foot.addStretch()
        root.addLayout(foot)

        self._btn_first.clicked.connect(self._go_first)
        self._btn_back.clicked.connect(lambda: self._step(-1))
        self._btn_fwd.clicked.connect(lambda: self._step(1))
        self._btn_last.clicked.connect(self._go_last)
        self._btn_toggle_select.clicked.connect(self._toggle_current_row_selected)
        self._cb_only_selected.toggled.connect(lambda _v: self.refresh_from_app())

        for key, slot in (
            (Qt.Key_Home, self._go_first),
            (Qt.Key_Left, lambda: self._step(-1)),
            (Qt.Key_Right, lambda: self._step(1)),
            (Qt.Key_End, self._go_last),
        ):
            sc = QShortcut(QKeySequence(key), self)
            sc.setContext(Qt.WidgetWithChildrenShortcut)
            sc.activated.connect(slot)

        self._auto_refresh_timer = QTimer(self)
        self._auto_refresh_timer.setSingleShot(True)
        self._auto_refresh_timer.setInterval(80)
        self._auto_refresh_timer.timeout.connect(
            lambda: self.refresh_from_app(preserve_position=True)
        )

        try:
            has_sel = bool(self._app._selected_logical_rows())
        except Exception:
            has_sel = False
        self._cb_only_selected.setChecked(has_sel)
        self.refresh_from_app()
        self._wire_table_updates()
        self._sync_footer_chrome()
        self._sync_options_chrome()
        self.setMinimumWidth(self.embedded_minimum_width())

    def rebind_parent_app(self, parent_app: Any | None) -> None:
        """Update the host app after dock/undock."""
        self.parent_app = parent_app
        self._app = parent_app
        self._prop_panel.bind_app(parent_app)

    def embedded_minimum_width(self) -> int:
        return max(360, BROWSER_STRUCTURE_PREVIEW_MIN_WIDTH // 2)

    def embedded_preferred_width(self) -> int:
        return max(self.embedded_minimum_width(), 480)

    def create_floating_dialog(self, parent_app) -> "SelectionBrowserDialog":
        """Re-open this browser in a floating window after undocking from the main table."""
        self.show()
        return SelectionBrowserDialog(parent_app, panel=self)

    def _add_to_main_window(self) -> None:
        if self.parent_app is None:
            return
        dock = getattr(self.parent_app, "dock_plot_widget", None)
        if not callable(dock):
            return
        dlg = self.window()
        if not dock(self):
            return
        if isinstance(dlg, SelectionBrowserDialog):
            discard_host_dialog_after_dock(dlg, self.parent_app, "_selection_browser_dialog")

    def _send_to_new_window(self) -> None:
        if self.parent_app is not None:
            undock = getattr(self.parent_app, "undock_plot_to_window", None)
            if callable(undock):
                undock(self)

    def _close_docked_browser(self) -> None:
        if self.parent_app is not None:
            close_fn = getattr(self.parent_app, "close_docked_plot", None)
            if callable(close_fn):
                close_fn(self)

    def _is_docked_in_main_window(self) -> bool:
        app = self.parent_app
        if app is None:
            return False
        check = getattr(app, "is_plot_docked", None)
        if callable(check):
            return bool(check(self))
        return False

    def _sync_footer_chrome(self) -> None:
        floating = isinstance(self.window(), SelectionBrowserDialog)
        docked = self._is_docked_in_main_window()
        self._add_to_main_btn.setVisible(floating)
        self._send_window_btn.setVisible(docked)
        self._close_btn.setVisible(docked)

    def _sync_options_chrome(self) -> None:
        """Show or hide property column pickers; keep the toggle button visible."""
        visible = bool(getattr(self, "_options_visible", True))
        host = getattr(self, "_options_host", None)
        if host is not None:
            host.setVisible(visible)
        btn = getattr(self, "_toggle_options_btn", None)
        if btn is not None:
            if visible:
                btn.setText("Hide Options")
                btn.setToolTip(
                    "Hide column pickers so only the structure preview and navigation controls are shown."
                )
            else:
                btn.setText("Show Options")
                btn.setToolTip("Show customizable property column pickers.")

    def _toggle_options_visible(self) -> None:
        self._options_visible = not bool(getattr(self, "_options_visible", True))
        self._sync_options_chrome()

    def event(self, event) -> bool:  # noqa: N802 — Qt API
        if event.type() == QEvent.ParentChange:
            try:
                self._sync_footer_chrome()
            except RuntimeError:
                pass
        return super().event(event)

    def _wire_table_updates(self) -> None:
        """Keep Browser in sync when the table, filters, or selection change."""
        if getattr(self, "_table_updates_wired", False):
            return
        app = self._app
        model = getattr(app, "_table_model", None)
        if model is None:
            return

        def _schedule_refresh() -> None:
            self._auto_refresh_timer.start()

        def _on_data_changed(top_left, bottom_right, roles=()) -> None:
            structure_col = CompoundTableModel.STRUCTURE_COL
            if (
                top_left.isValid()
                and bottom_right.isValid()
                and top_left.column() == structure_col
                and bottom_right.column() == structure_col
            ):
                paint_roles = {
                    Qt.DecorationRole,
                    Qt.SizeHintRole,
                    Qt.DisplayRole,
                    Qt.ToolTipRole,
                }
                if not roles or set(roles) <= paint_roles:
                    return
            _schedule_refresh()

        model.dataChanged.connect(_on_data_changed)
        model.rowsInserted.connect(_schedule_refresh)
        model.rowsRemoved.connect(_schedule_refresh)
        model.modelReset.connect(_schedule_refresh)
        model.layoutChanged.connect(_schedule_refresh)
        model.headerDataChanged.connect(_schedule_refresh)
        proxy = getattr(app, "_filter_proxy_model", None)
        if proxy is not None:
            proxy.layoutChanged.connect(_schedule_refresh)
            proxy.modelReset.connect(_schedule_refresh)
        sm = app.table.selectionModel()
        if sm is not None:
            sm.selectionChanged.connect(_schedule_refresh)
        self._table_updates_wired = True

    def resizeEvent(self, event) -> None:  # noqa: N802 — Qt API
        super().resizeEvent(event)
        if self._rows and 0 <= self._idx < len(self._rows):
            self._update_preview(self._rows[self._idx])

    def refresh_from_app(self, *, preserve_position: bool = False) -> None:
        """Recompute row scope; optionally keep the current row (by OID) when the table changes."""
        app = self._app
        cur_oid: int | None = None
        if preserve_position:
            row = self._current_row()
            if row is not None:
                try:
                    cur_oid = int(app._table_model.row_oid(row))
                except Exception:
                    cur_oid = None
        self._refresh_property_columns()
        self._rows = self._rows_for_scope(app)
        self._idx = 0
        if self._rows:
            if preserve_position and cur_oid is not None:
                for j, rr in enumerate(self._rows):
                    try:
                        if int(app._table_model.row_oid(rr)) == cur_oid:
                            self._idx = j
                            break
                    except Exception:
                        continue
            self._idx = self._first_navigable_index(self._idx, +1)
        self._preview_pix_cache.clear()
        self._update_ui(scroll_table=not preserve_position)

    def _rows_for_scope(self, app: Any) -> list[int]:
        visible = app._visible_source_row_indices()
        if self._cb_only_selected.isChecked():
            raw = list(app._selected_logical_rows())
            if visible is None:
                vis = raw
            else:
                vis_set = set(visible)
                vis = [r for r in raw if r in vis_set]
            return vis if vis else raw
        n = int(app._table_model.rowCount())
        if visible is None:
            return list(range(n))
        ordered = [r for r in range(n) if r in set(visible)]
        if ordered:
            return ordered
        return list(range(n))

    def _row_navigable(self, r: int) -> bool:
        if not (0 <= r < self._app._table_model.rowCount()):
            return False
        return self._app._is_source_row_visible(r)

    def _first_navigable_index(self, start: int, delta: int) -> int:
        n = len(self._rows)
        if n == 0:
            return 0
        i = start % n
        for _ in range(n):
            if self._row_navigable(self._rows[i]):
                return i
            i = (i + delta) % n
        return start % n

    def _last_navigable_index(self) -> int:
        n = len(self._rows)
        if n == 0:
            return 0
        for i in range(n - 1, -1, -1):
            if self._row_navigable(self._rows[i]):
                return i
        return self._first_navigable_index(0, +1)

    def _go_first(self) -> None:
        if not self._rows:
            return
        self._idx = self._first_navigable_index(0, +1)
        self._focus_row(self._rows[self._idx])

    def _go_last(self) -> None:
        if not self._rows:
            return
        self._idx = self._last_navigable_index()
        self._focus_row(self._rows[self._idx])

    def _step(self, delta: int) -> None:
        n = len(self._rows)
        if n == 0:
            return
        if n == 1:
            self._focus_row(self._rows[0])
            return
        nxt = (self._idx + delta) % n
        start = nxt
        for _ in range(n):
            r = self._rows[nxt]
            if self._row_navigable(r):
                self._idx = nxt
                self._focus_row(r)
                return
            nxt = (nxt + delta) % n
            if nxt == start:
                break
        self._idx = self._first_navigable_index(self._idx, delta)
        if self._rows:
            self._focus_row(self._rows[self._idx])

    def _view_index_for_source_row(
        self, logical_row: int, *, column: int = CompoundTableModel.STRUCTURE_COL
    ):
        app = self._app
        m = app._table_model
        if logical_row < 0 or logical_row >= m.rowCount():
            return None
        src_ix = m.index(logical_row, column)
        proxy = getattr(app, "_filter_proxy_model", None)
        view_model = app.table.model()
        if proxy is not None and view_model is proxy:
            view_ix = proxy.mapFromSource(src_ix)
            return view_ix if view_ix.isValid() else None
        return src_ix if src_ix.isValid() else None

    def _focus_row(self, logical_row: int) -> None:
        app = self._app
        tbl = app.table
        view_ix = self._view_index_for_source_row(logical_row)
        if view_ix is None:
            return
        sm = tbl.selectionModel()
        if sm is not None:
            sm.setCurrentIndex(view_ix, QItemSelectionModel.Current)
        tbl.scrollTo(view_ix, QAbstractItemView.PositionAtCenter)
        self._sync_caption(logical_row)
        self._update_preview(logical_row)

    def _sync_caption(self, logical_row: int) -> None:
        n = len(self._rows)
        scope = "Selected set" if self._cb_only_selected.isChecked() else "Table"
        self._meta.setText(f"{scope}: {self._idx + 1} / {n}  ·  Row {logical_row + 1}")
        self._update_property_values()

    def _refresh_property_columns(self) -> None:
        self._prop_panel.refresh_columns()

    def _current_row(self) -> int | None:
        if not self._rows:
            return None
        if not (0 <= self._idx < len(self._rows)):
            return None
        return self._rows[self._idx]

    def _is_row_selected(self, logical_row: int) -> bool:
        app = self._app
        override = getattr(app, "_selected_oids_override", None)
        if override is not None:
            try:
                oid = int(app._table_model.row_oid(logical_row))
                return oid in override
            except (IndexError, ValueError, TypeError):
                return False
        view_rows = app._source_rows_to_view_rows([logical_row])
        if not view_rows:
            return False
        try:
            sm = app.table.selectionModel()
            view_model = app.table.model()
            if sm is None or view_model is None:
                return False
            return bool(
                sm.isRowSelected(int(view_rows[0]), view_model.index(int(view_rows[0]), 0).parent())
            )
        except Exception:
            return False

    def _toggle_current_row_selected(self) -> None:
        r = self._current_row()
        if r is None:
            return
        app = self._app
        sm = app.table.selectionModel()
        view_model = app.table.model()
        if sm is None or view_model is None:
            return
        view_rows = app._source_rows_to_view_rows([r])
        if not view_rows:
            return
        last_col = max(0, view_model.columnCount() - 1)
        sel = item_selection_for_view_rows(view_model, view_rows, last_col=last_col)
        if sel.isEmpty():
            return
        already = self._is_row_selected(r)
        mode = QItemSelectionModel.Deselect if already else QItemSelectionModel.Select
        sm.select(sel, mode | QItemSelectionModel.Rows)

        if self._cb_only_selected.isChecked():
            try:
                oid = int(app._table_model.row_oid(r))
            except Exception:
                oid = None
            self.refresh_from_app()
            if oid is not None and self._rows:
                for j, rr in enumerate(self._rows):
                    try:
                        if int(app._table_model.row_oid(rr)) == oid:
                            self._idx = j
                            break
                    except Exception:
                        continue
                self._update_ui()
        else:
            self._sync_select_button()

    def _update_property_values(self) -> None:
        r = self._current_row()
        oid = None
        if r is not None:
            try:
                oid = int(self._app._table_model.row_oid(r))
            except Exception:
                oid = None
        self._prop_panel.set_source_oid(oid)
        self._sync_select_button()

    def _sync_select_button(self) -> None:
        r = self._current_row()
        if r is None:
            self._btn_toggle_select.setEnabled(False)
            self._btn_toggle_select.setText("Select")
            return
        self._btn_toggle_select.setEnabled(True)
        self._btn_toggle_select.setText("Deselect" if self._is_row_selected(r) else "Select")

    def _structure_pixmap(self, logical_row: int):
        m = self._app._table_model
        ix = m.index(logical_row, CompoundTableModel.STRUCTURE_COL)
        return m.data(ix, Qt.DecorationRole)

    def _preview_pixel_size(self) -> tuple[int, int, float]:
        dpr = max(1.0, float(self.devicePixelRatioF()))
        lw = max(self._struct_label.width(), BROWSER_STRUCTURE_PREVIEW_MIN_WIDTH)
        lh = max(self._struct_label.height(), BROWSER_STRUCTURE_PREVIEW_MIN_HEIGHT)
        return int(lw * dpr), int(lh * dpr), dpr

    def _render_preview_pixmap(self, logical_row: int, pw: int, ph: int) -> QPixmap | None:
        try:
            from rdkit.Chem.Draw import rdMolDraw2D
        except Exception:
            return None
        app = self._app
        try:
            oid = int(app._table_model.row_oid(logical_row))
        except Exception:
            return None
        cache_key = (oid, pw, ph)
        cached = self._preview_pix_cache.get(cache_key)
        if cached is not None and not cached.isNull():
            return cached
        mol = getattr(app, "mols", {}).get(oid)
        if mol is None:
            return None
        try:
            d = rdMolDraw2D.MolDraw2DCairo(pw, ph)
            rdMolDraw2D.PrepareAndDrawMolecule(d, mol)
            d.FinishDrawing()
            img = QImage.fromData(d.GetDrawingText())
            pm = QPixmap.fromImage(img)
            if not pm.isNull():
                self._preview_pix_cache[cache_key] = pm
                return pm
        except Exception:
            return None
        return None

    def _update_preview(self, logical_row: int) -> None:
        pw, ph, dpr = self._preview_pixel_size()
        pm = self._render_preview_pixmap(logical_row, pw, ph)
        if pm is None or pm.isNull():
            table_pm = self._structure_pixmap(logical_row)
            if isinstance(table_pm, QPixmap) and not table_pm.isNull():
                if table_pm.width() >= pw * 0.9 and table_pm.height() >= ph * 0.9:
                    pm = table_pm
        if isinstance(pm, QPixmap) and not pm.isNull():
            if pm.width() != pw or pm.height() != ph:
                pm = pm.scaled(pw, ph, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            pm.setDevicePixelRatio(dpr)
            self._struct_label.setPixmap(pm)
            self._struct_label.setText("")
        else:
            self._struct_label.clear()
            self._struct_label.setPixmap(QPixmap())
            self._struct_label.setText("(no structure available)")

    def _update_ui(self, *, scroll_table: bool = True) -> None:
        n = len(self._rows)
        single = n <= 1
        has_rows = n > 0
        self._btn_first.setEnabled(has_rows)
        self._btn_last.setEnabled(has_rows)
        self._btn_back.setEnabled(not single and has_rows)
        self._btn_fwd.setEnabled(not single and has_rows)
        if n == 0:
            if self._cb_only_selected.isChecked():
                self._meta.setText(
                    "No rows selected — uncheck “Browse Selected” or select rows in the table."
                )
            else:
                self._meta.setText("Table is empty.")
            self._struct_label.clear()
            self._struct_label.setPixmap(QPixmap())
            self._struct_label.setText("")
            return
        self._idx = max(0, min(self._idx, n - 1))
        self._idx = self._first_navigable_index(self._idx, +1)
        r = self._rows[self._idx]
        if scroll_table:
            self._focus_row(r)
        else:
            self._sync_caption(r)
            self._update_preview(r)


class SelectionBrowserDialog(QDialog):
    """Floating window hosting a :class:`SelectionBrowserWidget`."""

    def __init__(self, parent: Any = None, *, panel: SelectionBrowserWidget | None = None):
        super().__init__(parent)
        self.parent_app = parent
        self.setWindowTitle("Browser")
        self.setModal(False)
        self.setWindowModality(Qt.NonModal)
        self.resize(480, 520)
        self._force_close = False

        if panel is not None:
            self._panel = panel
            self._panel.setParent(self)
            self._panel.rebind_parent_app(parent)
            self._panel.show()
        else:
            self._panel = SelectionBrowserWidget(parent, self)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self._panel, 1)
        self._panel._sync_footer_chrome()
        self._panel._sync_options_chrome()
        make_window_minimizable(self)

    def refresh_from_app(self, *, preserve_position: bool = False) -> None:
        self._panel.refresh_from_app(preserve_position=preserve_position)

    def closeEvent(self, event) -> None:  # noqa: N802 — Qt API
        if self._force_close:
            self._force_close = False
        elif getattr(self, "_panel", None) is not None and self._panel.parent() is not self:
            self._panel = None
        event.accept()
