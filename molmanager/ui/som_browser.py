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

"""Modeless SOM results browser: step through FAME3R maps like File → Browser."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

from PyQt5.QtCore import QEvent, Qt, QTimer
from PyQt5.QtGui import QImage, QKeySequence, QPixmap
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QShortcut,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..display_constants import (
    BROWSER_STRUCTURE_PREVIEW_MIN_HEIGHT,
    BROWSER_STRUCTURE_PREVIEW_MIN_WIDTH,
)
from ..som_prediction import (
    SOM_CANCELLED_ERROR,
    SOM_ENTROPY_COLUMN,
    SOM_FAME_COLUMN,
    SOM_MAP_COLUMN,
    SOM_PROB_COLUMN,
    SOM_SITES_COLUMN,
    SomAtomHit,
    render_som_map_png,
)
from .dockable_plot import discard_host_dialog_after_dock
from .property_columns_panel import PropertyColumnsPanel
from .qt_widget_utils import make_window_minimizable
from .strings import TOOL_PREDICT_SOM


@dataclass(frozen=True)
class SomBrowseRecord:
    """One molecule in the SOM results browser."""

    oid: int | None
    smiles: str
    atoms: tuple[SomAtomHit, ...] = ()
    error: str | None = None
    columns: dict[str, str] = field(default_factory=dict)


def records_from_worker_rows(
    rows: Sequence, *, include_cancelled: bool = False
) -> list[SomBrowseRecord]:
    """Convert Predict SOM worker tuples into browser records.

    Cancelled placeholders are omitted by default so the browser only shows
    molecules that actually returned a result.
    """
    out: list[SomBrowseRecord] = []
    for row in rows or ():
        if not row:
            continue
        oid, cols, _png, atoms, _headers = row[:5]
        col_d = dict(cols or {})
        hits = tuple(hit for hit in (_coerce_atom_hit(a) for a in (atoms or ())) if hit is not None)
        raw_map = str(col_d.get(SOM_MAP_COLUMN) or "").strip()
        smiles = raw_map if _looks_like_smiles(raw_map) else ""
        err = None
        if not hits:
            err = raw_map if not smiles else "No SOM atoms were returned."
            if not err:
                err = "No SOM atoms were returned."
        out.append(
            SomBrowseRecord(
                oid=None if oid is None else int(oid),
                smiles=smiles,
                atoms=hits,
                error=err,
                columns=col_d,
            )
        )
    if include_cancelled:
        return out
    return [r for r in out if r.error != SOM_CANCELLED_ERROR]


def _looks_like_smiles(text: str) -> bool:
    t = (text or "").strip()
    if not t or t.upper() == "N/A" or t == SOM_CANCELLED_ERROR or " " in t:
        return False
    if t.startswith("No ") or "failed" in t.lower() or "error" in t.lower():
        return False
    return True


def _coerce_atom_hit(item: Any) -> SomAtomHit | None:
    if isinstance(item, SomAtomHit):
        return item
    if isinstance(item, dict):
        try:
            return SomAtomHit(
                atom_id=int(item["atom_id"]),
                probability=float(item["probability"]),
                is_som=bool(item.get("is_som")),
                fame_score=item.get("fame_score"),
                shannon_entropy=item.get("shannon_entropy"),
            )
        except (KeyError, TypeError, ValueError):
            return None
    return None


class SomBrowserWidget(QWidget):
    """Forward/back through SOM maps with a File → Browser style preview."""

    dockable_in_workspace = True

    def __init__(self, parent_app: Any = None, parent: QWidget | None = None):
        super().__init__(parent)
        self.parent_app = parent_app
        self._app = parent_app
        self._window_title = f"{TOOL_PREDICT_SOM} Browser"
        self._records: list[SomBrowseRecord] = []
        self._idx = 0
        self._preview_cache: dict[tuple, QPixmap] = {}
        self._emphasized_atom: int | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        self._meta = QLabel()
        self._meta.setAlignment(Qt.AlignCenter)
        root.addWidget(self._meta)

        self._summary = QLabel()
        self._summary.setAlignment(Qt.AlignCenter)
        self._summary.setWordWrap(True)
        self._summary.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._summary.setStyleSheet("font-weight: 600;")
        root.addWidget(self._summary)

        self._struct_label = QLabel()
        self._struct_label.setAlignment(Qt.AlignCenter)
        self._struct_label.setMinimumSize(360, 260)
        self._struct_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._struct_label.setStyleSheet(
            "background-color: palette(base); border: 1px solid palette(mid); border-radius: 4px;"
        )
        root.addWidget(self._struct_label, 1)

        self._atom_table = QTableWidget(0, 4)
        self._atom_table.setHorizontalHeaderLabels(["Atom", "Probability", "SOM", "Entropy"])
        self._atom_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self._atom_table.verticalHeader().setVisible(False)
        self._atom_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._atom_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._atom_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._atom_table.setToolTip("Select an atom to highlight it on the 2D map.")
        self._atom_table.setMaximumHeight(180)
        self._atom_table.itemSelectionChanged.connect(self._on_atom_selection_changed)
        root.addWidget(self._atom_table)

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
        self._btn_first.setToolTip("First molecule (Home)")
        self._btn_back = QPushButton("← Back")
        self._btn_back.setToolTip("Previous molecule (←)")
        self._btn_fwd = QPushButton("Forward →")
        self._btn_fwd.setToolTip("Next molecule (→)")
        self._btn_last = QPushButton(">>")
        self._btn_last.setToolTip("Last molecule (End)")
        self._btn_select = QPushButton("Select")
        self._btn_select.setToolTip("Select this row in the compound table")
        row_btns.addWidget(self._btn_first)
        row_btns.addWidget(self._btn_back)
        row_btns.addWidget(self._btn_fwd)
        row_btns.addWidget(self._btn_last)
        row_btns.addWidget(self._btn_select)
        row_btns.addStretch()
        root.addLayout(row_btns)

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
        self._toggle_options_btn = QPushButton("Hide Options")
        self._toggle_options_btn.setAutoDefault(False)
        self._toggle_options_btn.setDefault(False)
        self._toggle_options_btn.setToolTip(
            "Hide column pickers so only the SOM map and navigation controls are shown."
        )
        self._toggle_options_btn.clicked.connect(self._toggle_options_visible)
        foot.addWidget(self._toggle_options_btn)
        foot.addStretch()
        root.addLayout(foot)

        self._btn_first.clicked.connect(self._go_first)
        self._btn_back.clicked.connect(lambda: self._step(-1))
        self._btn_fwd.clicked.connect(lambda: self._step(1))
        self._btn_last.clicked.connect(self._go_last)
        self._btn_select.clicked.connect(self._select_current_row)

        for key, slot in (
            (Qt.Key_Home, self._go_first),
            (Qt.Key_Left, lambda: self._step(-1)),
            (Qt.Key_Right, lambda: self._step(1)),
            (Qt.Key_End, self._go_last),
        ):
            sc = QShortcut(QKeySequence(key), self)
            sc.setContext(Qt.WidgetWithChildrenShortcut)
            sc.activated.connect(slot)

        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.setInterval(60)
        self._resize_timer.timeout.connect(self._refresh_preview)

        self._sync_footer_chrome()
        self._sync_options_chrome()
        self.setMinimumWidth(self.embedded_minimum_width())
        self._update_ui()

    def rebind_parent_app(self, parent_app: Any | None) -> None:
        self.parent_app = parent_app
        self._app = parent_app
        self._prop_panel.bind_app(parent_app)

    def embedded_minimum_width(self) -> int:
        return max(360, BROWSER_STRUCTURE_PREVIEW_MIN_WIDTH // 2)

    def embedded_preferred_width(self) -> int:
        return max(self.embedded_minimum_width(), 480)

    def create_floating_dialog(self, parent_app) -> "SomBrowserDialog":
        self.show()
        return SomBrowserDialog(parent_app, panel=self)

    def set_records(self, records: list[SomBrowseRecord]) -> None:
        self._records = list(records or [])
        self._idx = 0
        self._preview_cache.clear()
        has_oid = any(r.oid is not None for r in self._records)
        self._options_host.setVisible(has_oid and bool(getattr(self, "_options_visible", True)))
        self._toggle_options_btn.setVisible(has_oid)
        self._update_ui()

    def _add_to_main_window(self) -> None:
        if self.parent_app is None:
            return
        dock = getattr(self.parent_app, "dock_plot_widget", None)
        if not callable(dock):
            return
        dlg = self.window()
        if not dock(self):
            return
        if isinstance(dlg, SomBrowserDialog):
            discard_host_dialog_after_dock(dlg, self.parent_app, "_som_browser_dialog")

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
        floating = isinstance(self.window(), SomBrowserDialog)
        docked = self._is_docked_in_main_window()
        self._add_to_main_btn.setVisible(floating)
        self._send_window_btn.setVisible(docked)
        self._close_btn.setVisible(docked)

    def _sync_options_chrome(self) -> None:
        visible = bool(getattr(self, "_options_visible", True))
        has_oid = any(r.oid is not None for r in self._records)
        host = getattr(self, "_options_host", None)
        if host is not None:
            host.setVisible(visible and has_oid)
        btn = getattr(self, "_toggle_options_btn", None)
        if btn is not None:
            if visible:
                btn.setText("Hide Options")
                btn.setToolTip(
                    "Hide column pickers so only the SOM map and navigation controls are shown."
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

    def resizeEvent(self, event) -> None:  # noqa: N802 — Qt API
        super().resizeEvent(event)
        timer = getattr(self, "_resize_timer", None)
        if timer is not None:
            timer.start()

    def _current(self) -> SomBrowseRecord | None:
        if not self._records or not (0 <= self._idx < len(self._records)):
            return None
        return self._records[self._idx]

    def _go_first(self) -> None:
        self._idx = 0
        self._update_ui()

    def _go_last(self) -> None:
        self._idx = max(0, len(self._records) - 1)
        self._update_ui()

    def _step(self, delta: int) -> None:
        if not self._records:
            return
        self._idx = (self._idx + int(delta)) % len(self._records)
        self._update_ui()

    def _select_current_row(self) -> None:
        rec = self._current()
        app = self._app
        if rec is None or rec.oid is None or app is None:
            return
        select = getattr(app, "select_table_oids", None)
        if callable(select):
            select([int(rec.oid)], extra_status=TOOL_PREDICT_SOM)

    def _preview_pixel_size(self) -> tuple[int, int, float]:
        dpr = max(1.0, float(self.devicePixelRatioF()))
        lw = max(self._struct_label.width(), BROWSER_STRUCTURE_PREVIEW_MIN_WIDTH)
        lh = max(self._struct_label.height(), BROWSER_STRUCTURE_PREVIEW_MIN_HEIGHT)
        return int(lw * dpr), int(lh * dpr), dpr

    def _refresh_preview(self) -> None:
        rec = self._current()
        if rec is None:
            self._struct_label.clear()
            self._struct_label.setPixmap(QPixmap())
            self._struct_label.setText("")
            return
        if rec.error and not rec.atoms:
            self._struct_label.clear()
            self._struct_label.setPixmap(QPixmap())
            self._struct_label.setText(rec.error)
            return
        pw, ph, dpr = self._preview_pixel_size()
        cache_key = (rec.oid, rec.smiles, pw, ph, len(rec.atoms), self._emphasized_atom)
        pm = self._preview_cache.get(cache_key)
        if pm is None or pm.isNull():
            png = render_som_map_png(
                rec.smiles,
                rec.atoms,
                width=pw,
                height=ph,
                emphasize_atom=self._emphasized_atom,
            )
            if png:
                pm = QPixmap.fromImage(QImage.fromData(png))
                if not pm.isNull():
                    self._preview_cache[cache_key] = pm
        if pm is None or pm.isNull():
            self._struct_label.clear()
            self._struct_label.setPixmap(QPixmap())
            self._struct_label.setText("(could not render SOM map)")
            return
        if pm.width() != pw or pm.height() != ph:
            pm = pm.scaled(pw, ph, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        pm.setDevicePixelRatio(dpr)
        self._struct_label.setPixmap(pm)
        self._struct_label.setText("")

    def _selected_atom_id(self) -> int | None:
        model = self._atom_table.selectionModel()
        if model is None:
            return None
        rows = model.selectedRows()
        if not rows:
            return None
        item = self._atom_table.item(rows[0].row(), 0)
        if item is None:
            return None
        data = item.data(Qt.UserRole)
        try:
            return int(data)
        except (TypeError, ValueError):
            return None

    def _on_atom_selection_changed(self) -> None:
        atom_id = self._selected_atom_id()
        if atom_id == self._emphasized_atom:
            return
        self._emphasized_atom = atom_id
        self._refresh_preview()

    def _fill_atom_table(self, rec: SomBrowseRecord | None) -> None:
        self._atom_table.blockSignals(True)
        try:
            self._atom_table.clearSelection()
            self._atom_table.setRowCount(0)
            if rec is None or not rec.atoms:
                self._emphasized_atom = None
                return
            ranked = sorted(rec.atoms, key=lambda a: (-a.probability, a.atom_id))
            for hit in ranked:
                r = self._atom_table.rowCount()
                self._atom_table.insertRow(r)
                values = (
                    str(hit.atom_id),
                    f"{hit.probability:.3f}",
                    "yes" if hit.is_som else "",
                    "" if hit.shannon_entropy is None else f"{hit.shannon_entropy:.3f}",
                )
                for c, text in enumerate(values):
                    item = QTableWidgetItem(text)
                    if c == 0:
                        item.setData(Qt.UserRole, int(hit.atom_id))
                    if hit.is_som:
                        item.setBackground(self.palette().alternateBase())
                    self._atom_table.setItem(r, c, item)
            self._emphasized_atom = None
        finally:
            self._atom_table.blockSignals(False)

    def _update_ui(self) -> None:
        n = len(self._records)
        single = n <= 1
        has_rows = n > 0
        self._btn_first.setEnabled(has_rows)
        self._btn_last.setEnabled(has_rows)
        self._btn_back.setEnabled(not single and has_rows)
        self._btn_fwd.setEnabled(not single and has_rows)
        rec = self._current()
        self._btn_select.setEnabled(rec is not None and rec.oid is not None)
        if not has_rows:
            self._meta.setText("No SOM results.")
            self._summary.setText("")
            self._fill_atom_table(None)
            self._prop_panel.set_source_oid(None)
            self._refresh_preview()
            return
        self._idx = max(0, min(self._idx, n - 1))
        rec = self._current()
        row_txt = ""
        if rec is not None and rec.oid is not None and self._app is not None:
            try:
                logical = int(self._app._table_model.logical_row_for_oid(int(rec.oid)))
                if logical >= 0:
                    row_txt = f"  ·  Row {logical + 1}"
            except Exception:
                row_txt = ""
        self._meta.setText(f"{TOOL_PREDICT_SOM}: {self._idx + 1} / {n}{row_txt}")
        cols = rec.columns if rec is not None else {}
        sites = cols.get(SOM_SITES_COLUMN) or "—"
        probs = cols.get(SOM_PROB_COLUMN) or "—"
        entropy = cols.get(SOM_ENTROPY_COLUMN) or "—"
        fame = cols.get(SOM_FAME_COLUMN)
        summary = f"SOM sites {sites}  ·  {probs}  ·  entropy {entropy}"
        if fame:
            summary += f"  ·  FAME {fame}"
        self._summary.setText(summary)
        self._fill_atom_table(rec)
        self._prop_panel.set_source_oid(None if rec is None else rec.oid)
        self._refresh_preview()


class SomBrowserDialog(QDialog):
    """Floating window hosting a :class:`SomBrowserWidget`."""

    def __init__(self, parent: Any = None, *, panel: SomBrowserWidget | None = None):
        super().__init__(parent)
        self.parent_app = parent
        self.setWindowTitle(f"{TOOL_PREDICT_SOM} Browser")
        self.setModal(False)
        self.setWindowModality(Qt.NonModal)
        self.resize(520, 720)
        self._force_close = False

        if panel is not None:
            self._panel = panel
            self._panel.setParent(self)
            self._panel.rebind_parent_app(parent)
            self._panel.show()
        else:
            self._panel = SomBrowserWidget(parent, self)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self._panel, 1)
        self._panel._sync_footer_chrome()
        self._panel._sync_options_chrome()
        make_window_minimizable(self)
        self.setModal(False)
        self.setWindowModality(Qt.NonModal)

    def set_records(self, records: list[SomBrowseRecord]) -> None:
        panel = getattr(self, "_panel", None)
        if panel is None:
            return
        panel.set_records(records)

    def closeEvent(self, event) -> None:  # noqa: N802 — Qt API
        if self._force_close:
            self._force_close = False
        elif getattr(self, "_panel", None) is not None and self._panel.parent() is not self:
            self._panel = None
        event.accept()
