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

"""Browse enumerated tautomer / protomer forms: 2D preview, table, arrow keys."""

from __future__ import annotations

from dataclasses import dataclass
from contextlib import suppress
from typing import Any, Sequence

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QAbstractScrollArea,
    QCheckBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QStyle,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...chem.molecule_conversion import mol_from_smiles, safe_float
from ...services.column_labels import COLUMN_PARENT_OID, COLUMN_PROTOMER_SOURCE_OID_LEGACY
from ...table.structure_depiction_layout import (
    BROWSER_STRUCTURE_PREVIEW_MIN_HEIGHT,
    BROWSER_STRUCTURE_PREVIEW_MIN_WIDTH,
)
from ..dockable_plot import (
    _GLYPH_BTN_SIZE,
    add_centered_browser_nav,
    discard_host_dialog_after_dock,
    make_add_to_main_button,
    make_send_window_button,
    request_close_plot_widget,
    style_browser_nav_buttons,
    style_plot_footer_text_button,
)
from ..dialogs.protomer import pka_text_for_source_oid
from ..widgets import NumericTableWidgetItem
from .chrome import (
    BrowserHostDialog,
    apply_browser_body_layout,
    floating_browser_minimum_width,
    install_browser_nav_shortcuts,
    pixmap_from_mol,
    style_browser_data_table,
    style_browser_preview_host,
    style_browser_structure_label,
)

_ROW_TABLE_ROW_HEIGHT = 28
_TABLE_MAX_VISIBLE_ROWS = 8
_HIT_INDEX_ROLE = Qt.UserRole


@dataclass(frozen=True)
class EnumeratedFormHit:
    """One tautomer or protomer form."""

    source_oid: int | None
    smiles: str
    score_text: str
    sort_key: float
    canonical: str = ""


@dataclass(frozen=True)
class EnumeratedFormGroup:
    """Forms that share a parent table row (or a SMILES-only run)."""

    source_oid: int | None
    hits: tuple[EnumeratedFormHit, ...]


def unique_column_name(app: Any, base: str) -> str:
    headers = list(getattr(app, "headers", None) or [])
    name = base
    i = 1
    while name in headers:
        i += 1
        name = f"{base} ({i})"
    return name


def parent_oid_column_name(app: Any) -> str:
    headers = list(getattr(app, "headers", None) or [])
    if COLUMN_PARENT_OID in headers:
        return COLUMN_PARENT_OID
    if COLUMN_PROTOMER_SOURCE_OID_LEGACY in headers:
        return COLUMN_PROTOMER_SOURCE_OID_LEGACY
    return unique_column_name(app, COLUMN_PARENT_OID)


def _oid_key(raw) -> int | None:
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def groups_from_tautomer_rows(rows: Sequence) -> list[EnumeratedFormGroup]:
    """Convert tautomer worker tuples into per-parent groups."""
    return _groups_from_rows(
        rows,
        hit_fn=lambda src, smi, score, is_canonical, *_rest: EnumeratedFormHit(
            source_oid=_oid_key(src),
            smiles=str(smi or "").strip(),
            score_text=str(int(score)),
            sort_key=float(int(score)),
            canonical="Yes" if is_canonical else "No",
        ),
    )


def groups_from_protomer_rows(rows: Sequence) -> list[EnumeratedFormGroup]:
    """Convert protomer worker tuples into per-parent groups."""
    return _groups_from_rows(
        rows,
        hit_fn=lambda src, smi, pct, *_rest: EnumeratedFormHit(
            source_oid=_oid_key(src),
            smiles=str(smi or "").strip(),
            score_text=f"{float(pct):.2f}",
            sort_key=float(pct),
        ),
    )


def _groups_from_rows(rows: Sequence, *, hit_fn) -> list[EnumeratedFormGroup]:
    buckets: dict[int | None, list[EnumeratedFormHit]] = {}
    order: list[int | None] = []
    for row in rows or ():
        if not row:
            continue
        hit = hit_fn(*row)
        if not hit.smiles:
            continue
        key = hit.source_oid
        if key not in buckets:
            buckets[key] = []
            order.append(key)
        buckets[key].append(hit)
    groups: list[EnumeratedFormGroup] = []
    for key in order:
        hits = tuple(sorted(buckets[key], key=lambda h: (-h.sort_key, h.smiles)))
        groups.append(EnumeratedFormGroup(source_oid=key, hits=hits))
    return groups


class EnumeratedFormBrowserWidget(QWidget):
    """2D structure preview plus a compact form table, with arrow browsing."""

    dockable_in_workspace = True
    supports_floating_title = False
    kind = ""
    form_noun = "form"
    window_title = "Form Browser"
    score_header = "Score"
    extra_header: str | None = None
    dialog_attr = ""
    add_status_noun = "form"

    def __init__(self, parent_app: Any = None, parent: QWidget | None = None):
        super().__init__(parent)
        self.parent_app = parent_app
        self._app = parent_app
        self._window_title = self.window_title
        self._all_groups: list[EnumeratedFormGroup] = []
        self._groups: list[EnumeratedFormGroup] = []
        self._group_idx = 0
        self._idx = 0
        self._preview_cache: dict[tuple, QPixmap] = {}
        self._filling_table = False
        self._selection_model = None
        self._build_chrome()
        self._wire_chrome()
        self._update_ui()

    def _table_headers(self) -> list[str]:
        names = ["Form", self.score_header]
        if self.extra_header:
            names.append(self.extra_header)
        return names

    def _build_chrome(self) -> None:
        root = QVBoxLayout(self)
        apply_browser_body_layout(root)

        self._cb_only_selected = QCheckBox("Browse Selected")
        self._cb_only_selected.setToolTip(
            "When checked, navigation walks only parents whose table row is selected.\n"
            "When unchecked, it walks every parent from the last run."
        )

        self._preview_host = QWidget(self)
        self._preview_host.setMinimumSize(360, 260)
        self._preview_host.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        style_browser_preview_host(self._preview_host)
        preview_ly = QVBoxLayout(self._preview_host)
        preview_ly.setContentsMargins(0, 0, 0, 0)
        preview_ly.setSpacing(0)
        self._struct_label = QLabel(self._preview_host)
        self._struct_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        style_browser_structure_label(self._struct_label)
        preview_ly.addWidget(self._struct_label, 1)
        root.addWidget(self._preview_host, 1)

        self._row_table = QTableWidget(0, 0, self)
        self._row_table.setObjectName("BrowserRowTable")
        self._row_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._row_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._row_table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self._row_table.setFocusPolicy(Qt.ClickFocus)
        self._row_table.verticalHeader().setVisible(False)
        hdr = self._row_table.horizontalHeader()
        hdr.setHighlightSections(False)
        hdr.setStretchLastSection(True)
        hdr.setSectionResizeMode(QHeaderView.Interactive)
        self._row_table.setSizeAdjustPolicy(QAbstractScrollArea.AdjustIgnored)
        self._row_table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._row_table.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._row_table.setWordWrap(False)
        self._row_table.setShowGrid(True)
        self._row_table.verticalHeader().setDefaultSectionSize(_ROW_TABLE_ROW_HEIGHT)
        self._row_table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        style_browser_data_table(self._row_table)
        bar = self._row_table.horizontalScrollBar()
        if bar is not None:
            bar.rangeChanged.connect(lambda *_a: self._fit_row_table_height())
        root.addWidget(self._row_table)
        self._fit_row_table_height()

        add_row = QHBoxLayout()
        add_row.setContentsMargins(0, 0, 0, 0)
        add_row.setSpacing(4)
        self._add_current_btn = QPushButton("Add current to table")
        self._add_sel_btn = QPushButton("Add selected to table")
        self._add_all_btn = QPushButton("Add all to table")
        noun = self.form_noun
        self._add_current_btn.setToolTip(f"Add the displayed {noun} as a new compound-table row.")
        self._add_sel_btn.setToolTip(f"Add the selected {noun}(s) from this table.")
        self._add_all_btn.setToolTip(f"Add every browsable {noun} as new compound-table rows.")
        add_row.addWidget(self._add_current_btn)
        add_row.addWidget(self._add_sel_btn)
        add_row.addWidget(self._add_all_btn)
        add_row.addStretch()
        root.addLayout(add_row)

        self._nav_bar = QWidget(self)
        self._nav_bar.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        row_btns = QHBoxLayout(self._nav_bar)
        row_btns.setContentsMargins(0, 0, 0, 0)
        row_btns.setSpacing(4)
        self._btn_first = QPushButton("<<")
        self._btn_first.setToolTip(f"First {noun} (Home)")
        self._btn_back = QPushButton("←")
        self._btn_back.setToolTip(f"Previous {noun} (←)")
        self._btn_fwd = QPushButton("→")
        self._btn_fwd.setToolTip(f"Next {noun} (→)")
        self._btn_last = QPushButton(">>")
        self._btn_last.setToolTip(f"Last {noun} (End)")
        self._btn_toggle_select = QPushButton()
        self._btn_toggle_select.setToolTip("Select this parent row in the compound table")
        style_browser_nav_buttons(
            self._btn_first,
            self._btn_back,
            self._btn_fwd,
            self._btn_last,
            self._btn_toggle_select,
            select_checkable=True,
        )
        add_centered_browser_nav(
            row_btns,
            [
                self._btn_first,
                self._btn_back,
                self._btn_fwd,
                self._btn_last,
                self._btn_toggle_select,
            ],
            trailing=self._cb_only_selected,
        )
        root.addWidget(self._nav_bar)

        self._footer_bar = QWidget(self)
        self._footer_bar.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        self._footer_bar.setMinimumHeight(_GLYPH_BTN_SIZE)
        foot = QHBoxLayout(self._footer_bar)
        foot.setContentsMargins(0, 0, 0, 0)
        foot.setSpacing(4)

        self._header_left = QWidget(self._footer_bar)
        self._header_left.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        left_ly = QHBoxLayout(self._header_left)
        left_ly.setContentsMargins(0, 0, 0, 0)
        left_ly.setSpacing(4)
        left_ly.addStretch(1)

        self._meta = QLabel(self._footer_bar)
        self._meta.setAlignment(Qt.AlignCenter)
        self._meta.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        self._meta.setMinimumHeight(_GLYPH_BTN_SIZE)

        self._header_right = QWidget(self._footer_bar)
        self._header_right.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        right_ly = QHBoxLayout(self._header_right)
        right_ly.setContentsMargins(0, 0, 0, 0)
        right_ly.setSpacing(4)
        right_ly.addStretch(1)
        self._add_to_main_btn = make_add_to_main_button(
            self,
            tooltip="Dock this browser beside the compound table.",
        )
        self._add_to_main_btn.clicked.connect(self._add_to_main_window)
        right_ly.addWidget(self._add_to_main_btn)
        self._send_window_btn = make_send_window_button(
            self,
            tooltip="Open this docked browser in a separate floating window.",
        )
        self._send_window_btn.clicked.connect(self._send_to_new_window)
        right_ly.addWidget(self._send_window_btn)
        self._close_btn = QPushButton("Close")
        self._close_btn.setToolTip("Close this browser.")
        self._close_btn.clicked.connect(self._close_docked_browser)
        style_plot_footer_text_button(self._close_btn)
        right_ly.addWidget(self._close_btn)

        foot.addWidget(self._header_left, 1)
        foot.addWidget(self._meta, 0)
        foot.addWidget(self._header_right, 1)
        self._apply_header_caption_font()
        root.insertWidget(0, self._footer_bar)

    def _wire_chrome(self) -> None:
        self._btn_first.clicked.connect(self._go_first)
        self._btn_back.clicked.connect(lambda: self._step(-1))
        self._btn_fwd.clicked.connect(lambda: self._step(1))
        self._btn_last.clicked.connect(self._go_last)
        self._btn_toggle_select.clicked.connect(self._toggle_current_row_selected)
        self._cb_only_selected.toggled.connect(self._on_only_selected_toggled)
        self._row_table.itemSelectionChanged.connect(self._on_table_selection_changed)
        self._add_current_btn.clicked.connect(self._add_current_to_table)
        self._add_sel_btn.clicked.connect(self._add_selected_to_table)
        self._add_all_btn.clicked.connect(self._add_all_to_table)
        install_browser_nav_shortcuts(
            self,
            go_first=self._go_first,
            step=self._step,
            go_last=self._go_last,
        )
        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.setInterval(60)
        self._resize_timer.timeout.connect(self._refresh_preview)
        self._selection_timer = QTimer(self)
        self._selection_timer.setSingleShot(True)
        self._selection_timer.setInterval(80)
        self._selection_timer.timeout.connect(self._refresh_selected_scope)
        self._sync_footer_chrome()
        self.setMinimumWidth(self.embedded_minimum_width())
        self._connect_table_selection()

    def _apply_header_caption_font(self) -> None:
        font = QFont(self._meta.font())
        font.setPointSize(max(9, font.pointSize()))
        self._meta.setFont(font)

    def rebind_parent_app(self, parent_app: Any | None) -> None:
        self._disconnect_table_selection()
        self.parent_app = parent_app
        self._app = parent_app
        self._connect_table_selection()

    def embedded_minimum_width(self) -> int:
        return max(360, BROWSER_STRUCTURE_PREVIEW_MIN_WIDTH // 2)

    def embedded_preferred_width(self) -> int:
        return max(self.embedded_minimum_width(), BROWSER_STRUCTURE_PREVIEW_MIN_WIDTH)

    def floating_content_minimum_width(self) -> int:
        return floating_browser_minimum_width(self, floor=self.embedded_minimum_width())

    def create_floating_dialog(self, parent_app) -> BrowserHostDialog:
        self.show()
        return self._dialog_cls()(parent_app, panel=self)

    def _dialog_cls(self) -> type[BrowserHostDialog]:
        raise NotImplementedError

    def set_groups(self, groups: list[EnumeratedFormGroup]) -> None:
        self._all_groups = list(groups or [])
        self._preview_cache.clear()
        has_oid = any(g.source_oid is not None for g in self._all_groups)
        self._cb_only_selected.setEnabled(has_oid)
        if not has_oid and self._cb_only_selected.isChecked():
            self._cb_only_selected.blockSignals(True)
            self._cb_only_selected.setChecked(False)
            self._cb_only_selected.blockSignals(False)
        self._apply_group_scope(preserve=False)
        dlg = self.window()
        if isinstance(dlg, BrowserHostDialog):
            dlg.setWindowTitle(self._window_title)

    def current_hit(self) -> EnumeratedFormHit | None:
        group = self._current_group()
        if not group or not (0 <= self._idx < len(group.hits)):
            return None
        return group.hits[self._idx]

    def _current_group(self) -> EnumeratedFormGroup | None:
        if not self._groups or not (0 <= self._group_idx < len(self._groups)):
            return None
        return self._groups[self._group_idx]

    def _total_forms(self) -> int:
        return sum(len(g.hits) for g in self._groups)

    def _add_to_main_window(self) -> None:
        if self.parent_app is None:
            return
        dock = getattr(self.parent_app, "dock_plot_widget", None)
        if not callable(dock) or not dock(self):
            return
        dlg = self.window()
        if isinstance(dlg, BrowserHostDialog) and self.dialog_attr:
            discard_host_dialog_after_dock(dlg, self.parent_app, self.dialog_attr)

    def _send_to_new_window(self) -> None:
        if self.parent_app is not None:
            undock = getattr(self.parent_app, "undock_plot_to_window", None)
            if callable(undock):
                undock(self)

    def _close_docked_browser(self) -> None:
        request_close_plot_widget(
            self,
            title="Close Browser",
            message="Close this browser?",
        )

    def _is_docked_in_main_window(self) -> bool:
        app = self.parent_app
        if app is None:
            return False
        check = getattr(app, "is_plot_docked", None)
        if callable(check):
            return bool(check(self))
        return False

    def _sync_footer_chrome(self) -> None:
        from ..dockable_plot import apply_plot_chrome_glyphs, sync_docked_footer_bar

        apply_plot_chrome_glyphs(self)
        floating = isinstance(self.window(), BrowserHostDialog)
        docked = self._is_docked_in_main_window()
        self._add_to_main_btn.setVisible(floating)
        self._send_window_btn.setVisible(docked)
        self._close_btn.setVisible(True)
        sync_docked_footer_bar(self, docked=docked)

    def event(self, event) -> bool:  # noqa: N802 — Qt API
        if event.type() == QEvent.ParentChange:
            with suppress(RuntimeError):
                self._sync_footer_chrome()
        return super().event(event)

    def resizeEvent(self, event) -> None:  # noqa: N802 — Qt API
        super().resizeEvent(event)
        timer = getattr(self, "_resize_timer", None)
        if timer is not None:
            timer.start()

    def _go_first(self) -> None:
        self._group_idx = 0
        self._idx = 0
        self._update_ui()

    def _go_last(self) -> None:
        self._group_idx = max(0, len(self._groups) - 1)
        group = self._current_group()
        self._idx = max(0, len(group.hits) - 1) if group is not None else 0
        self._update_ui()

    def _step(self, delta: int) -> None:
        if not self._groups or self._total_forms() <= 0:
            return
        step = 1 if int(delta) >= 0 else -1
        remaining = abs(int(delta)) or 1
        while remaining:
            group = self._current_group()
            if group is None:
                return
            nxt = self._idx + step
            if 0 <= nxt < len(group.hits):
                self._idx = nxt
            else:
                n = len(self._groups)
                self._group_idx = (self._group_idx + step) % n
                group = self._current_group()
                if group is None:
                    return
                self._idx = 0 if step > 0 else max(0, len(group.hits) - 1)
            remaining -= 1
        self._update_ui()

    def _on_only_selected_toggled(self, _checked: bool = False) -> None:
        self._apply_group_scope(preserve=True)

    def _selected_oids(self) -> set[int]:
        app = self._app
        if app is None:
            return set()
        getter = getattr(app, "_selected_oids_set", None)
        if not callable(getter):
            return set()
        try:
            return {int(x) for x in getter()}
        except (TypeError, ValueError):
            return set()

    def _apply_group_scope(self, *, preserve: bool) -> None:
        cur = self.current_hit() if preserve else None
        groups = list(self._all_groups)
        if self._cb_only_selected.isChecked():
            selected = self._selected_oids()
            groups = [
                g for g in groups if g.source_oid is not None and int(g.source_oid) in selected
            ]
        self._groups = groups
        self._group_idx = 0
        self._idx = 0
        if cur is not None:
            for gi, group in enumerate(self._groups):
                for hi, hit in enumerate(group.hits):
                    if hit == cur:
                        self._group_idx = gi
                        self._idx = hi
                        break
        self._update_ui()

    def _connect_table_selection(self) -> None:
        self._disconnect_table_selection()
        app = self._app
        table = getattr(app, "table", None) if app is not None else None
        sm = table.selectionModel() if table is not None else None
        if sm is None:
            return
        sm.selectionChanged.connect(self._on_host_table_selection_changed)
        self._selection_model = sm

    def _disconnect_table_selection(self) -> None:
        sm = getattr(self, "_selection_model", None)
        if sm is None:
            return
        with suppress(TypeError, RuntimeError):
            sm.selectionChanged.disconnect(self._on_host_table_selection_changed)
        self._selection_model = None

    def _on_host_table_selection_changed(self, *_args) -> None:
        if not self._cb_only_selected.isChecked():
            return
        timer = getattr(self, "_selection_timer", None)
        if timer is not None:
            timer.start()

    def _refresh_selected_scope(self) -> None:
        if self._cb_only_selected.isChecked():
            self._apply_group_scope(preserve=True)

    def _toggle_current_row_selected(self) -> None:
        group = self._current_group()
        app = self._app
        if group is None or group.source_oid is None or app is None:
            return
        oid = int(group.source_oid)
        selected = self._selected_oids()
        if oid in selected:
            selected.discard(oid)
        else:
            selected.add(oid)
        select = getattr(app, "select_table_oids", None)
        if callable(select):
            select(selected)
        self._sync_select_button()

    def _fit_row_table_height(self) -> None:
        table = self._row_table
        n_rows = max(1, min(int(table.rowCount() or 1), _TABLE_MAX_VISIBLE_ROWS))
        hdr_h = int(table.horizontalHeader().sizeHint().height())
        frame = 2 * int(table.frameWidth())
        style = table.style()
        extent = int(style.pixelMetric(QStyle.PM_ScrollBarExtent, None, table))
        hbar = table.horizontalScrollBar()
        hinted = int(hbar.sizeHint().height()) if hbar is not None else 0
        h_scroll = max(extent, hinted, 16)
        v_scroll = extent if int(table.rowCount() or 0) > _TABLE_MAX_VISIBLE_ROWS else 0
        table.setFixedHeight(
            hdr_h + n_rows * _ROW_TABLE_ROW_HEIGHT + frame + h_scroll + v_scroll + 4
        )

    def _score_item(self, text: str, hit_idx: int) -> QTableWidgetItem:
        num = safe_float(text)
        if num is None:
            item = QTableWidgetItem(text)
        else:
            item = NumericTableWidgetItem()
            item.setData(Qt.EditRole, num)
            item.setText(text)
        item.setData(_HIT_INDEX_ROLE, int(hit_idx))
        return item

    def _text_item(self, text: str, hit_idx: int) -> QTableWidgetItem:
        item = QTableWidgetItem(text)
        item.setData(_HIT_INDEX_ROLE, int(hit_idx))
        return item

    def _hit_index_for_table_row(self, row: int) -> int | None:
        if row < 0 or row >= self._row_table.rowCount():
            return None
        item = self._row_table.item(row, 0)
        if item is None:
            return None
        try:
            return int(item.data(_HIT_INDEX_ROLE))
        except (TypeError, ValueError):
            return None

    def _fill_row_table(self) -> None:
        group = self._current_group()
        hits = group.hits if group is not None else ()
        names = self._table_headers()
        self._filling_table = True
        self._row_table.blockSignals(True)
        try:
            self._row_table.setColumnCount(len(names))
            self._row_table.setHorizontalHeaderLabels(names)
            self._row_table.setRowCount(len(hits))
            ligand_idx = self._group_idx
            for row, hit in enumerate(hits):
                form_id = f"{ligand_idx + 1}.{row + 1}"
                self._row_table.setItem(row, 0, self._text_item(form_id, row))
                self._row_table.setItem(row, 1, self._score_item(hit.score_text, row))
                if self.extra_header:
                    self._row_table.setItem(row, 2, self._text_item(hit.canonical, row))
                self._row_table.setRowHeight(row, _ROW_TABLE_ROW_HEIGHT)
        finally:
            self._row_table.blockSignals(False)
            self._filling_table = False
        self._fit_row_table_height()
        self._select_current_table_row()

    def _select_current_table_row(self) -> None:
        if not (0 <= self._idx < self._row_table.rowCount()):
            self._row_table.clearSelection()
            return
        self._filling_table = True
        try:
            self._row_table.selectRow(self._idx)
        finally:
            self._filling_table = False

    def _on_table_selection_changed(self) -> None:
        if self._filling_table:
            return
        row = self._row_table.currentRow()
        hit_idx = self._hit_index_for_table_row(row)
        if hit_idx is None or hit_idx == self._idx:
            return
        self._idx = hit_idx
        self._sync_caption()
        self._sync_select_button()
        self._refresh_preview()

    def _selected_hits(self) -> list[EnumeratedFormHit]:
        group = self._current_group()
        if group is None:
            return []
        sm = self._row_table.selectionModel()
        rows = sm.selectedRows() if sm is not None else []
        hits: list[EnumeratedFormHit] = []
        seen: set[int] = set()
        for idx in rows:
            hit_idx = self._hit_index_for_table_row(int(idx.row()))
            if hit_idx is None or hit_idx in seen or not (0 <= hit_idx < len(group.hits)):
                continue
            seen.add(hit_idx)
            hits.append(group.hits[hit_idx])
        return hits

    def _fields_for_hit(self, hit: EnumeratedFormHit) -> dict[str, str]:
        app = self.parent_app
        oid_txt = "" if hit.source_oid is None else str(int(hit.source_oid))
        src_col = parent_oid_column_name(app)
        if self.kind == "tautomer":
            return {
                unique_column_name(app, "Tautomer score"): hit.score_text,
                unique_column_name(app, "Canonical tautomer"): hit.canonical,
                src_col: oid_txt,
            }
        fields = {
            unique_column_name(app, "Protomer %"): hit.score_text,
            src_col: oid_txt,
        }
        fields["pKa"] = pka_text_for_source_oid(app, hit.source_oid)
        return fields

    def _add_hits_to_table(self, hits: Sequence[EnumeratedFormHit]) -> None:
        app = self.parent_app
        if app is None or not hits:
            return
        batch = [(hit.smiles, self._fields_for_hit(hit)) for hit in hits if hit.smiles]
        if not batch:
            return
        added = app.add_rows_from_external_records_batch(batch)
        noun = self.add_status_noun
        app.status_label.setText(f"Added {added} {noun} row(s) to the table.")

    def _add_current_to_table(self) -> None:
        hit = self.current_hit()
        if hit is None:
            QMessageBox.information(self, self.window_title, f"No {self.form_noun} to add.")
            return
        self._add_hits_to_table([hit])

    def _add_selected_to_table(self) -> None:
        hits = self._selected_hits()
        if not hits:
            QMessageBox.information(
                self,
                self.window_title,
                f"Select one or more rows in the {self.form_noun} table.",
            )
            return
        self._add_hits_to_table(hits)

    def _add_all_to_table(self) -> None:
        hits = [hit for group in self._groups for hit in group.hits]
        if not hits:
            return
        self._add_hits_to_table(hits)

    def _sync_caption(self) -> None:
        n_groups = len(self._groups)
        group = self._current_group()
        if group is None or n_groups == 0:
            self._meta.setText(f"No {self.form_noun}s to browse.")
            return
        n_forms = len(group.hits)
        scope = "Selected" if self._cb_only_selected.isChecked() else "Parents"
        self._meta.setText(
            f"{scope}: {self._group_idx + 1} / {n_groups}  ·  "
            f"{self.form_noun.capitalize()} {self._idx + 1} / {n_forms}"
        )

    def _sync_select_button(self) -> None:
        group = self._current_group()
        if group is None or group.source_oid is None:
            self._btn_toggle_select.setEnabled(False)
            self._btn_toggle_select.setChecked(False)
            return
        self._btn_toggle_select.setEnabled(True)
        selected = int(group.source_oid) in self._selected_oids()
        self._btn_toggle_select.setChecked(selected)

    def _preview_pixel_size(self) -> tuple[int, int, float]:
        dpr = max(1.0, float(self.devicePixelRatioF()))
        lw = int(self._struct_label.width())
        lh = int(self._struct_label.height())
        if lw < 32 or lh < 32:
            lw = BROWSER_STRUCTURE_PREVIEW_MIN_WIDTH
            lh = BROWSER_STRUCTURE_PREVIEW_MIN_HEIGHT
        return max(1, int(lw * dpr)), max(1, int(lh * dpr)), dpr

    def _fit_preview_pixmap(self, pm: QPixmap, dpr: float) -> QPixmap:
        lw = int(self._struct_label.width())
        lh = int(self._struct_label.height())
        if lw < 32 or lh < 32:
            pm.setDevicePixelRatio(dpr)
            return pm
        canvas_w = max(1, int(lw * dpr))
        canvas_h = max(1, int(lh * dpr))
        canvas = QPixmap(canvas_w, canvas_h)
        canvas.fill(QColor(255, 255, 255))
        fitted = pm
        if fitted.width() != canvas_w or fitted.height() != canvas_h:
            fitted = pm.scaled(canvas_w, canvas_h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        painter = QPainter(canvas)
        x = (canvas_w - fitted.width()) // 2
        y = (canvas_h - fitted.height()) // 2
        painter.drawPixmap(x, y, fitted)
        painter.end()
        canvas.setDevicePixelRatio(dpr)
        return canvas

    def _refresh_preview(self) -> None:
        hit = self.current_hit()
        if hit is None:
            self._struct_label.clear()
            self._struct_label.setPixmap(QPixmap())
            self._struct_label.setText(f"No {self.form_noun}s to browse.")
            return
        smiles = hit.smiles
        pw, ph, dpr = self._preview_pixel_size()
        cache_key = (smiles, pw, ph)
        pm = self._preview_cache.get(cache_key)
        if pm is None or pm.isNull():
            mol = mol_from_smiles(smiles)
            pm = pixmap_from_mol(mol, pw, ph)
            if pm is not None and not pm.isNull():
                self._preview_cache[cache_key] = pm
        if pm is None or pm.isNull():
            self._struct_label.clear()
            self._struct_label.setPixmap(QPixmap())
            self._struct_label.setText("Could not draw structure.")
            return
        self._struct_label.setPixmap(self._fit_preview_pixmap(pm, dpr))
        self._struct_label.setText("")

    def _update_ui(self) -> None:
        n_groups = len(self._groups)
        n_forms = self._total_forms()
        nav_on = n_forms > 1
        for btn in (self._btn_first, self._btn_back, self._btn_fwd, self._btn_last):
            btn.setEnabled(nav_on)
        if n_groups == 0:
            self._group_idx = 0
            self._idx = 0
            self._sync_caption()
            self._fill_row_table()
            self._sync_select_button()
            self._refresh_preview()
            return
        self._group_idx = max(0, min(self._group_idx, n_groups - 1))
        group = self._current_group()
        n_hits = len(group.hits) if group is not None else 0
        self._idx = max(0, min(self._idx, max(0, n_hits - 1)))
        self._sync_caption()
        self._fill_row_table()
        self._sync_select_button()
        self._refresh_preview()


class TautomerBrowserWidget(EnumeratedFormBrowserWidget):
    kind = "tautomer"
    form_noun = "tautomer"
    window_title = "Tautomer Browser"
    score_header = "Score"
    extra_header = "Canonical"
    dialog_attr = "_tautomer_browser_dialog"
    add_status_noun = "tautomer"

    def _dialog_cls(self) -> type[BrowserHostDialog]:
        return TautomerBrowserDialog


class ProtomerBrowserWidget(EnumeratedFormBrowserWidget):
    kind = "protomer"
    form_noun = "protomer"
    window_title = "Protomer Browser"
    score_header = "% (approx.)"
    extra_header = None
    dialog_attr = "_protomer_browser_dialog"
    add_status_noun = "protomer"

    def _dialog_cls(self) -> type[BrowserHostDialog]:
        return ProtomerBrowserDialog


class TautomerBrowserDialog(BrowserHostDialog):
    """Floating window hosting tautomer enumeration results."""

    default_title = "Tautomer Browser"
    panel_cls = TautomerBrowserWidget
    fit_chrome = True
    refresh_preview_on_show = True
    min_size = (640, 720)
    initial_size = (720, 840)

    def set_groups(self, groups: list[EnumeratedFormGroup]) -> None:
        panel = getattr(self, "_panel", None)
        if panel is not None:
            panel.set_groups(groups)


class ProtomerBrowserDialog(BrowserHostDialog):
    """Floating window hosting protomer enumeration results."""

    default_title = "Protomer Browser"
    panel_cls = ProtomerBrowserWidget
    fit_chrome = True
    refresh_preview_on_show = True
    min_size = (640, 720)
    initial_size = (720, 840)

    def set_groups(self, groups: list[EnumeratedFormGroup]) -> None:
        panel = getattr(self, "_panel", None)
        if panel is not None:
            panel.set_groups(groups)
