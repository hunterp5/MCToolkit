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

"""Filter panel cards (numeric range, substructure, text, category)."""

from PyQt5.QtCore import QEvent, QMimeData, QPoint, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QDrag
from PyQt5.QtWidgets import (
    QAbstractButton,
    QAbstractItemView,
    QAbstractSlider,
    QApplication,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .range_slider import RangeSlider

# --- Filter cards (compact; panel scrolls) -------------------------------------
FILTER_CARD_MIME = "application/x-molmanager-filter-card"
_FILTER_CARD_MIN_HEIGHT_RANGE = 122
_FILTER_CARD_MIN_HEIGHT_SUBSTRUCTURE = 118
_FILTER_CARD_MIN_HEIGHT_TEXT = 104
_FILTER_CARD_MIN_HEIGHT_CATEGORY = 140
_FC_PAD = 4
_FC_GAP = 4
_FC_CTRL_H = 20
_FC_SLIDER_H = 16
_FC_LIST_MAX = 96
_FC_MINI_LABEL_W = 26
_FC_TOOL_BTN_MIN_W = 48
_FC_TOOL_BTN_WIDE_MIN_W = 76

# Interactive controls: dragging from these should not reorder cards.
_FC_DRAG_BLOCKERS = (
    QAbstractButton,
    QAbstractItemView,
    QAbstractSlider,
    QComboBox,
    QLineEdit,
    RangeSlider,
)


def filter_card_drop_index(host: QWidget, y: int, dragged: QWidget) -> int:
    """Index among sibling cards (excluding ``dragged``) for a drop at local ``y``."""
    layout = host.layout()
    if layout is None:
        return 0
    insert_at = 0
    for i in range(layout.count()):
        item = layout.itemAt(i)
        w = item.widget() if item is not None else None
        if w is None or w is dragged:
            continue
        if y < w.y() + w.height() // 2:
            return insert_at
        insert_at += 1
    return insert_at


def _fc_install_card_shell(card: QFrame, min_height_px: int) -> None:
    from ..theme import filter_card_stylesheet

    card.setObjectName("FilterCard")
    card.setFrameShape(QFrame.NoFrame)
    card.setMinimumHeight(min_height_px)
    card.setMinimumWidth(0)
    card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
    card.setStyleSheet(filter_card_stylesheet())
    card.setCursor(Qt.ArrowCursor)


def _fc_card_layout(card: QFrame) -> QVBoxLayout:
    """Shared card insets: equal pad to the border and equal gap between rows (incl. title)."""
    ly = QVBoxLayout(card)
    ly.setContentsMargins(_FC_PAD, _FC_PAD, _FC_PAD, _FC_PAD)
    ly.setSpacing(_FC_GAP)
    return ly


def style_filter_card_remove_button(btn: QPushButton) -> None:
    btn.setObjectName("fcRemove")
    btn.setText("×")
    btn.setFixedSize(18, 18)
    btn.setCursor(Qt.PointingHandCursor)
    btn.setToolTip("Remove this filter")
    btn.setAutoDefault(False)
    btn.setDefault(False)


def _fc_configure_column_combo(cb: QComboBox) -> None:
    """Keep the combo within the filter panel; long names scroll in the dropdown."""
    cb.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLength)
    cb.setMinimumContentsLength(8)
    cb.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    cb.setMinimumWidth(0)


def _fc_toggle_btn(
    btn: QPushButton,
    *,
    min_width: int | None = None,
    active: bool | None = None,
) -> None:
    from ..theme import polish_widget_property

    btn.setObjectName("fcToggle")
    btn.setAutoDefault(False)
    btn.setDefault(False)
    btn.setFixedHeight(_FC_CTRL_H)
    btn.setMinimumWidth(int(min_width) if min_width is not None else 0)
    btn.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
    if active is not None:
        polish_widget_property(btn, "fcActive", bool(active))


def _fc_toolbar_button(text: str, *, wide: bool = False) -> QPushButton:
    """Compact filter-panel button matching On/Invert toggle styling."""
    btn = QPushButton(text)
    min_w = _FC_TOOL_BTN_WIDE_MIN_W if wide else _FC_TOOL_BTN_MIN_W
    _fc_toggle_btn(btn, min_width=min_w, active=False)
    return btn


def _fc_set_toggle_active(btn: QPushButton, active: bool) -> None:
    from ..theme import polish_widget_property

    polish_widget_property(btn, "fcActive", bool(active))


def _fc_mini_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("fcMiniLabel")
    lbl.setFixedWidth(_FC_MINI_LABEL_W)
    lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
    return lbl


class _FilterCardDragMixin:
    """Drag empty card chrome to reorder within the filter panel (not from controls)."""

    _fc_drag_start: QPoint | None = None

    def _fc_is_drag_chrome(self, pos: QPoint) -> bool:
        child = self.childAt(pos)
        while child is not None and child is not self:
            if isinstance(child, _FC_DRAG_BLOCKERS):
                return False
            child = child.parentWidget()
        return True

    def mousePressEvent(self, event) -> None:  # noqa: N802 — Qt API
        if event.button() == Qt.LeftButton and self._fc_is_drag_chrome(event.pos()):
            self._fc_drag_start = QPoint(event.pos())
        else:
            self._fc_drag_start = None
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 — Qt API
        start = self._fc_drag_start
        if (
            start is not None
            and event.buttons() & Qt.LeftButton
            and (event.pos() - start).manhattanLength() >= QApplication.startDragDistance()
        ):
            self._fc_drag_start = None
            self._fc_begin_reorder_drag()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 — Qt API
        self._fc_drag_start = None
        super().mouseReleaseEvent(event)

    def _fc_begin_reorder_drag(self) -> None:
        from ..theme import polish_widget_property

        polish_widget_property(self, "fcDragging", True)
        mime = QMimeData()
        mime.setData(FILTER_CARD_MIME, str(id(self)).encode("ascii"))
        drag = QDrag(self)
        drag.setMimeData(mime)
        try:
            drag.exec_(Qt.MoveAction)
        finally:
            polish_widget_property(self, "fcDragging", False)


class FilterCardsHost(QWidget):
    """Scroll-area contents that accept filter-card drops for reordering."""

    def __init__(self, on_reorder=None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._on_reorder = on_reorder
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event) -> None:  # noqa: N802 — Qt API
        if event.mimeData().hasFormat(FILTER_CARD_MIME):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:  # noqa: N802 — Qt API
        if event.mimeData().hasFormat(FILTER_CARD_MIME):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event) -> None:  # noqa: N802 — Qt API
        card = self._card_from_mime(event.mimeData())
        if card is None or self._on_reorder is None:
            event.ignore()
            return
        idx = filter_card_drop_index(self, event.pos().y(), card)
        self._on_reorder(card, idx)
        event.acceptProposedAction()

    def _card_from_mime(self, mime: QMimeData):
        try:
            wanted = int(bytes(mime.data(FILTER_CARD_MIME)).decode("ascii"))
        except (TypeError, ValueError):
            return None
        layout = self.layout()
        if layout is None:
            return None
        for i in range(layout.count()):
            item = layout.itemAt(i)
            w = item.widget() if item is not None else None
            if w is not None and id(w) == wanted:
                return w
        return None


class _FilterCardTitleLabel(QLabel):
    """Shows the filter title; double-click starts in-place rename."""

    def __init__(self, on_edit_request, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self._on_edit_request = on_edit_request
        self.setObjectName("fcSectionTitle")
        self.setToolTip("Double-click to rename")
        self.setCursor(Qt.IBeamCursor)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802 — Qt API
        if event.button() == Qt.LeftButton:
            self._on_edit_request()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


class _FilterCardEnableInvertMixin:
    """Shared On/Off + Invert controls. Subclasses must define ``changed`` and ``removed`` signals."""

    def _fc_init_enable_invert(
        self,
        invert_tooltip: str,
        *,
        toolbar_min_width: int | None = None,
    ) -> None:
        self._filter_enabled_on = True
        self.enable_btn = QPushButton("On")
        self.enable_btn.setToolTip("Turn this filter on or off.")
        self.enable_btn.clicked.connect(self._on_enable_clicked)
        _fc_toggle_btn(
            self.enable_btn,
            min_width=toolbar_min_width,
            active=True,
        )
        self._sync_enable_button_appearance()
        self._invert_on = False
        self.invert_btn = QPushButton("Invert")
        self.invert_btn.setToolTip(invert_tooltip)
        self.invert_btn.clicked.connect(self._on_invert_clicked)
        _fc_toggle_btn(
            self.invert_btn,
            min_width=toolbar_min_width,
            active=False,
        )
        self._sync_invert_button_appearance()

    def _fc_add_title_row(self, parent_layout: QVBoxLayout, title: str) -> QPushButton:
        """Editable title + remove (×) on the top row (double-click title to rename)."""
        self._filter_title_fallback = str(title or "Filter")
        self._title_host = QWidget()
        self._title_host_lyt = QHBoxLayout(self._title_host)
        self._title_host_lyt.setContentsMargins(0, 0, 0, 0)
        self._title_host_lyt.setSpacing(_FC_GAP)
        self._title_label = _FilterCardTitleLabel(
            self._fc_begin_title_edit, self._filter_title_fallback
        )
        # Match control row height; horizontal pad only (vertical inset comes from card layout).
        self._title_label.setMinimumHeight(_FC_CTRL_H)
        self._title_label.setMaximumHeight(_FC_CTRL_H)
        self._title_host_lyt.addWidget(self._title_label, 1)
        self._title_edit: QLineEdit | None = None
        rem = QPushButton()
        style_filter_card_remove_button(rem)
        rem.clicked.connect(lambda: self.removed.emit(self))
        self._title_host_lyt.addWidget(rem, 0, Qt.AlignVCenter)
        self._remove_btn = rem
        parent_layout.addWidget(self._title_host)
        return rem

    def filter_title(self) -> str:
        if self._title_edit is not None:
            return (self._title_edit.text() or "").strip() or self._filter_title_fallback
        return self._title_label.text()

    def set_filter_title(self, title: str) -> None:
        text = (title or "").strip() or self._filter_title_fallback
        self._filter_title_fallback = text
        if self._title_edit is not None:
            self._title_edit.setText(text)
        else:
            self._title_label.setText(text)

    def _fc_begin_title_edit(self) -> None:
        if self._title_edit is not None:
            return
        edit = QLineEdit(self._title_label.text())
        edit.setObjectName("fcTitleEdit")
        edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        edit.setMinimumHeight(_FC_CTRL_H)
        edit.installEventFilter(self)
        self._title_host_lyt.replaceWidget(self._title_label, edit)
        self._title_label.hide()
        self._title_edit = edit
        edit.editingFinished.connect(self._fc_commit_title_edit)
        edit.setFocus(Qt.MouseFocusReason)
        edit.selectAll()

    def _fc_commit_title_edit(self) -> None:
        edit = self._title_edit
        if edit is None:
            return
        self._title_edit = None
        edit.blockSignals(True)
        try:
            edit.editingFinished.disconnect(self._fc_commit_title_edit)
        except TypeError:
            pass
        new = (edit.text() or "").strip() or self._filter_title_fallback
        self._title_label.setText(new)
        self._filter_title_fallback = new
        self._title_host_lyt.replaceWidget(edit, self._title_label)
        edit.deleteLater()
        self._title_label.show()

    def _fc_cancel_title_edit(self) -> None:
        edit = self._title_edit
        if edit is None:
            return
        edit.blockSignals(True)
        try:
            edit.editingFinished.disconnect(self._fc_commit_title_edit)
        except TypeError:
            pass
        self._title_host_lyt.replaceWidget(edit, self._title_label)
        edit.deleteLater()
        self._title_edit = None
        self._title_label.show()

    def eventFilter(self, obj, event):  # noqa: N802 — Qt API
        if obj is getattr(self, "_title_edit", None) and event.type() == QEvent.KeyPress:
            if event.key() == Qt.Key_Escape:
                self._fc_cancel_title_edit()
                return True
        return super().eventFilter(obj, event)

    def _fc_add_header_toolbar(
        self,
        parent_layout: QVBoxLayout,
        *,
        leading: QWidget | None = None,
        extra_buttons: list[QPushButton] | None = None,
    ) -> None:
        """Toolbar row of stretchable toggles (dropdowns sit on their own row; × is on the title)."""
        row = QHBoxLayout()
        row.setSpacing(_FC_GAP)
        if leading is not None:
            # Kept for callers that still pass a leading widget; prefer a separate row.
            row.addWidget(leading, 1, Qt.AlignVCenter)
        buttons = [self.enable_btn, self.invert_btn, *(extra_buttons or [])]
        for btn in buttons:
            btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            btn.setMinimumWidth(0)
            row.addWidget(btn, 1, Qt.AlignVCenter)
        parent_layout.addLayout(row)

    def _sync_invert_button_appearance(self) -> None:
        if self._invert_on:
            self.invert_btn.setText("Inverted")
        else:
            self.invert_btn.setText("Invert")
        _fc_set_toggle_active(self.invert_btn, self._invert_on)

    def _on_invert_clicked(self) -> None:
        self._invert_on = not self._invert_on
        self._sync_invert_button_appearance()
        self.changed.emit()

    def _sync_enable_button_appearance(self) -> None:
        if self._filter_enabled_on:
            self.enable_btn.setText("On")
        else:
            self.enable_btn.setText("Off")
        _fc_set_toggle_active(self.enable_btn, self._filter_enabled_on)

    def _on_enable_clicked(self) -> None:
        self._filter_enabled_on = not self._filter_enabled_on
        self._sync_enable_button_appearance()
        self.changed.emit()

    def filter_enabled(self) -> bool:
        return self._filter_enabled_on

    def filter_inverted(self) -> bool:
        return self._invert_on

    def restore_filter_flags(self, enabled: bool = True, inverted: bool = False) -> None:
        self._filter_enabled_on = bool(enabled)
        self._sync_enable_button_appearance()
        self._invert_on = bool(inverted)
        self._sync_invert_button_appearance()

    def refresh_theme_styles(self) -> None:
        """Re-apply toggle state after the card stylesheet changes (theme switch)."""
        self._sync_enable_button_appearance()
        self._sync_invert_button_appearance()
        sync_case = getattr(self, "_sync_case_button_appearance", None)
        if callable(sync_case):
            sync_case()
        sync_partial = getattr(self, "_sync_partial_button_appearance", None)
        if callable(sync_partial):
            sync_partial()


class FilterCard(_FilterCardDragMixin, _FilterCardEnableInvertMixin, QFrame):
    changed = pyqtSignal()
    removed = pyqtSignal(object)

    def __init__(self, props, app, initial_property: str | None = None):
        super().__init__()
        self.app, self.scale = app, 100
        _fc_install_card_shell(self, _FILTER_CARD_MIN_HEIGHT_RANGE)
        l = _fc_card_layout(self)
        self._fc_add_title_row(l, "Slider")
        self.cb = QComboBox()
        _fc_configure_column_combo(self.cb)
        self.cb.addItems(props)
        if initial_property and self.cb.findText(initial_property) >= 0:
            self.cb.setCurrentText(initial_property)
        self.cb.currentTextChanged.connect(self.refresh_limits)
        self._fc_init_enable_invert("Show rows outside the min/max range.")
        self._fc_add_header_toolbar(l)
        l.addWidget(self.cb)

        bounds_lyt = QHBoxLayout()
        bounds_lyt.setSpacing(_FC_GAP)
        bounds_lyt.addWidget(_fc_mini_label("Min"))
        self.min_edit = QLineEdit()
        self.min_edit.setMinimumWidth(40)
        self.min_edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.min_edit.editingFinished.connect(self.sync_from_text)
        bounds_lyt.addWidget(self.min_edit, 1)
        bounds_lyt.addWidget(_fc_mini_label("Max"))
        self.max_edit = QLineEdit()
        self.max_edit.setMinimumWidth(40)
        self.max_edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.max_edit.editingFinished.connect(self.sync_from_text)
        bounds_lyt.addWidget(self.max_edit, 1)
        l.addLayout(bounds_lyt)

        self.range_slider = RangeSlider(self)
        self.range_slider.setFixedHeight(_FC_SLIDER_H)
        self.range_slider.rangeChanged.connect(self._sync_slider_edits)
        self.range_slider.sliderReleased.connect(self._commit_slider_filter)
        l.addWidget(self.range_slider)
        self.refresh_limits()

    def update_prop_list(self, new_props, old_n=None, new_n=None):
        self.cb.blockSignals(True)
        current = self.cb.currentText()
        self.cb.clear()
        self.cb.addItems(new_props)
        if old_n and current == old_n:
            if new_n:
                self.cb.setCurrentText(new_n)
                self.cb.blockSignals(False)
                self.refresh_limits()
                return False
            self.cb.blockSignals(False)
            return True
        self.cb.setCurrentText(current)
        self.cb.blockSignals(False)
        return False

    def refresh_limits(self):
        prop = self.cb.currentText()
        if not prop:
            return
        self.blockSignals(True)
        b_meta = self.app.global_bounds.get(prop, {"min": 0, "max": 100, "is_int": False})
        b_min, b_max = b_meta["min"], b_meta["max"]
        self.scale = 1 if b_meta["is_int"] else 100
        lo = int(b_min * self.scale)
        hi = int(b_max * self.scale)
        self.range_slider.blockSignals(True)
        self.range_slider.setRange(lo, hi)
        self.range_slider.setValues(lo, hi)
        self.range_slider.blockSignals(False)
        fmt = "{:.0f}" if b_meta["is_int"] else "{:.2f}"
        self.min_edit.setText(fmt.format(b_min))
        self.max_edit.setText(fmt.format(b_max))
        self.blockSignals(False)
        self.changed.emit()

    def _sync_slider_edits(self, *_args) -> None:
        """Update min/max text while dragging without re-filtering the table."""
        vmin = self.range_slider.lowerValue()
        vmax = self.range_slider.upperValue()
        fmt = "{:.0f}" if self.scale == 1 else "{:.2f}"
        self.min_edit.setText(fmt.format(vmin / self.scale))
        self.max_edit.setText(fmt.format(vmax / self.scale))

    def _commit_slider_filter(self) -> None:
        self._sync_slider_edits()
        self.changed.emit()

    def sync_from_slider(self, which: str | None = None):
        del which
        self._sync_slider_edits()
        self.changed.emit()

    def sync_from_text(self):
        try:
            v_min, v_max = float(self.min_edit.text()), float(self.max_edit.text())
            if v_min > v_max:
                v_min = v_max
            self.range_slider.blockSignals(True)
            self.range_slider.setValues(int(v_min * self.scale), int(v_max * self.scale))
            self.range_slider.blockSignals(False)
            self._sync_slider_edits()
            self.changed.emit()
        except Exception:
            self.sync_from_slider(None)

    def get_cfg(self):
        return {
            "column": self.cb.currentText(),
            "min": self.range_slider.lowerValue() / self.scale,
            "max": self.range_slider.upperValue() / self.scale,
            "enabled": self._filter_enabled_on,
            "inverted": self._invert_on,
        }

    def restore_state(self, prop: str, min_val: float, max_val: float) -> None:
        self.blockSignals(True)
        if self.cb.findText(prop) >= 0:
            self.cb.setCurrentText(prop)
        b_meta = self.app.global_bounds.get(prop, {"min": 0, "max": 100, "is_int": False})
        self.scale = 1 if b_meta["is_int"] else 100
        lo, hi = float(b_meta["min"]), float(b_meta["max"])
        self.range_slider.blockSignals(True)
        self.range_slider.setRange(int(lo * self.scale), int(hi * self.scale))
        lo_v = max(min(min_val, max_val), lo)
        hi_v = min(max(max_val, min_val), hi)
        self.range_slider.setValues(int(lo_v * self.scale), int(hi_v * self.scale))
        self.range_slider.blockSignals(False)
        fmt = "{:.0f}" if self.scale == 1 else "{:.2f}"
        self.min_edit.setText(fmt.format(self.range_slider.lowerValue() / self.scale))
        self.max_edit.setText(fmt.format(self.range_slider.upperValue() / self.scale))
        self.blockSignals(False)


class SubstructureFilterCard(_FilterCardDragMixin, _FilterCardEnableInvertMixin, QFrame):
    changed = pyqtSignal()
    removed = pyqtSignal(object)

    def __init__(self, structure_sources: list[str] | None = None):
        super().__init__()
        self._last_smarts = ""
        self._last_query = None
        _fc_install_card_shell(self, _FILTER_CARD_MIN_HEIGHT_SUBSTRUCTURE)
        l = _fc_card_layout(self)
        self._fc_add_title_row(l, "Substructure")
        self.src_combo = QComboBox()
        _fc_configure_column_combo(self.src_combo)
        self.set_structure_sources(structure_sources or ["Structure"])
        self.src_combo.currentIndexChanged.connect(self._on_source_change)
        self._fc_init_enable_invert("Hide rows that match SMARTS instead of showing them.")
        self._fc_add_header_toolbar(l)
        l.addWidget(self.src_combo)

        self.smarts_edit = QLineEdit()
        self.smarts_edit.setPlaceholderText("SMARTS, e.g. [F,Cl], [!C;R], or [M]")
        self.smarts_edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.smarts_edit.setMinimumWidth(0)
        self.smarts_edit.textChanged.connect(self._on_change)
        l.addWidget(self.smarts_edit)

    def _on_change(self, _txt: str) -> None:
        self._last_query = None
        self._last_smarts = ""
        self.changed.emit()

    def _on_source_change(self, _idx: int = 0) -> None:
        self.changed.emit()

    def _compiled_query(self):
        from ...smarts_patterns import mol_from_smarts

        s = (self.smarts_edit.text() or "").strip()
        if not s:
            self._last_smarts = ""
            self._last_query = None
            return None
        if s == self._last_smarts:
            return self._last_query
        q = mol_from_smarts(s)
        self._last_smarts = s
        self._last_query = q
        return q

    def match_mol(self, mol) -> bool:
        q = self._compiled_query()
        if q is None:
            s = (self.smarts_edit.text() or "").strip()
            return True if not s else False
        try:
            return bool(mol is not None and mol.HasSubstructMatch(q))
        except Exception:
            return False

    def structure_source(self) -> str:
        return (self.src_combo.currentText() or "").strip() or "Structure"

    def set_structure_sources(self, sources: list[str]) -> None:
        """Refresh available structure sources, preserving the current selection when possible."""
        prev = self.structure_source() if self.src_combo.count() else "Structure"
        self.src_combo.blockSignals(True)
        self.src_combo.clear()
        items = [s for s in sources if s] or ["Structure"]
        self.src_combo.addItems(items)
        idx = self.src_combo.findText(prev)
        self.src_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.src_combo.blockSignals(False)

    def set_structure_source(self, source: str) -> None:
        name = (source or "").strip() or "Structure"
        idx = self.src_combo.findText(name)
        if idx < 0:
            self.src_combo.addItem(name)
            idx = self.src_combo.findText(name)
        if idx >= 0:
            self.src_combo.blockSignals(True)
            self.src_combo.setCurrentIndex(idx)
            self.src_combo.blockSignals(False)

    def get_cfg(self):
        return {
            "type": "substructure",
            "smarts": (self.smarts_edit.text() or "").strip(),
            "structure_source": self.structure_source(),
            "enabled": self._filter_enabled_on,
            "inverted": self._invert_on,
        }

    def set_smarts(self, smarts: str) -> None:
        self.smarts_edit.blockSignals(True)
        self.smarts_edit.setText(smarts or "")
        self.smarts_edit.blockSignals(False)
        self._last_smarts = ""
        self._last_query = None


class TextFilterCard(_FilterCardDragMixin, _FilterCardEnableInvertMixin, QFrame):
    """Filter rows by text in a chosen column (partial or exact, case optional)."""

    changed = pyqtSignal()
    removed = pyqtSignal(object)

    def __init__(self, columns: list[str], app):
        super().__init__()
        self.app = app
        self._case_sensitive = False
        self._partial_match = True
        _fc_install_card_shell(self, _FILTER_CARD_MIN_HEIGHT_TEXT)
        l = _fc_card_layout(self)
        self._fc_add_title_row(l, "Text")
        self.cb = QComboBox()
        _fc_configure_column_combo(self.cb)
        self.cb.addItems(columns)
        self.cb.currentTextChanged.connect(lambda _t: self.changed.emit())
        self._fc_init_enable_invert(
            "Invert matching rows.",
            toolbar_min_width=_FC_TOOL_BTN_MIN_W,
        )
        self.partial_btn = _fc_toolbar_button("Partial")
        self.partial_btn.setToolTip("Substring vs exact cell match.")
        self.partial_btn.clicked.connect(self._on_partial_clicked)
        self._sync_partial_button_appearance()
        self.case_btn = _fc_toolbar_button("Ignore Case", wide=True)
        self.case_btn.setToolTip("Case-sensitive vs ignore case.")
        self.case_btn.clicked.connect(self._on_case_clicked)
        self._sync_case_button_appearance()
        self._fc_add_header_toolbar(
            l,
            extra_buttons=[self.partial_btn, self.case_btn],
        )
        l.addWidget(self.cb)
        self.text_edit = QLineEdit()
        self.text_edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.text_edit.setMinimumWidth(0)
        self._sync_match_placeholder()
        self._text_filter_timer = QTimer(self)
        self._text_filter_timer.setSingleShot(True)
        self._text_filter_timer.timeout.connect(self.changed.emit)
        self.text_edit.textChanged.connect(self._schedule_text_filter_changed)
        l.addWidget(self.text_edit)

    def _schedule_text_filter_changed(self, _text: str = "") -> None:
        self._text_filter_timer.start(280)

    def _sync_match_placeholder(self) -> None:
        if self._partial_match:
            self.text_edit.setPlaceholderText("Match substring (empty = no filter)")
        else:
            self.text_edit.setPlaceholderText("Match full cell (empty = no filter)")

    def _sync_case_button_appearance(self) -> None:
        if self._case_sensitive:
            self.case_btn.setText("Case")
        else:
            self.case_btn.setText("Ignore Case")
        _fc_set_toggle_active(self.case_btn, self._case_sensitive)

    def _on_case_clicked(self) -> None:
        self._case_sensitive = not self._case_sensitive
        self._sync_case_button_appearance()
        self.changed.emit()

    def _sync_partial_button_appearance(self) -> None:
        if self._partial_match:
            self.partial_btn.setText("Partial")
        else:
            self.partial_btn.setText("Exact")
        _fc_set_toggle_active(self.partial_btn, self._partial_match)

    def _on_partial_clicked(self) -> None:
        self._partial_match = not self._partial_match
        self._sync_partial_button_appearance()
        self._sync_match_placeholder()
        self.changed.emit()

    def set_column(self, name: str) -> None:
        if name and self.cb.findText(name) >= 0:
            self.cb.setCurrentText(name)

    def update_prop_list(self, new_props, old_n=None, new_n=None):
        self.cb.blockSignals(True)
        current = self.cb.currentText()
        self.cb.clear()
        self.cb.addItems(new_props)
        if old_n and current == old_n:
            if new_n:
                self.cb.setCurrentText(new_n)
                self.cb.blockSignals(False)
                self.changed.emit()
                return False
            self.cb.blockSignals(False)
            return True
        if current and self.cb.findText(current) >= 0:
            self.cb.setCurrentText(current)
        elif self.cb.count():
            self.cb.setCurrentIndex(0)
        self.cb.blockSignals(False)
        return False

    def row_matches(self, row: int) -> bool:
        prop = self.cb.currentText()
        if not prop:
            return True
        raw = self.app._table_model.value_for_header(row, prop) or ""
        needle = (self.text_edit.text() or "").strip()
        if not needle:
            return True
        if self._partial_match:
            if self._case_sensitive:
                inside = needle in raw
            else:
                inside = needle.lower() in raw.lower()
        else:
            if self._case_sensitive:
                inside = raw == needle
            else:
                inside = raw.lower() == needle.lower()
        return not inside if self._invert_on else inside

    def get_cfg(self):
        return {
            "column": self.cb.currentText(),
            "text": self.text_edit.text() or "",
            "enabled": self._filter_enabled_on,
            "inverted": self._invert_on,
            "case_sensitive": self._case_sensitive,
            "partial_match": self._partial_match,
        }

    def restore_from_session(
        self,
        prop: str,
        text: str,
        *,
        case_sensitive: bool = False,
        partial_match: bool = True,
    ) -> None:
        self.cb.blockSignals(True)
        if prop and self.cb.findText(prop) >= 0:
            self.cb.setCurrentText(prop)
        self.cb.blockSignals(False)
        self.text_edit.blockSignals(True)
        self.text_edit.setText(text or "")
        self.text_edit.blockSignals(False)
        self._case_sensitive = bool(case_sensitive)
        self._partial_match = bool(partial_match)
        self._sync_case_button_appearance()
        self._sync_partial_button_appearance()
        self._sync_match_placeholder()


class CategoryFilterCard(_FilterCardDragMixin, _FilterCardEnableInvertMixin, QFrame):
    """Filter rows by membership in selected distinct values of a column."""

    changed = pyqtSignal()
    removed = pyqtSignal(object)
    _BLANK = "\u0000blank\u0000"

    def __init__(self, columns: list[str], app):
        super().__init__()
        self.app = app
        _fc_install_card_shell(self, _FILTER_CARD_MIN_HEIGHT_CATEGORY)
        l = _fc_card_layout(self)
        self._fc_add_title_row(l, "Category")
        self.cb = QComboBox()
        _fc_configure_column_combo(self.cb)
        self.cb.addItems(columns)
        self.cb.currentTextChanged.connect(self._on_column_changed)
        self._fc_init_enable_invert(
            "Invert category selection.",
            toolbar_min_width=_FC_TOOL_BTN_MIN_W,
        )
        self.all_btn = _fc_toolbar_button("All")
        self.all_btn.setToolTip("Check every category in the list.")
        self.all_btn.clicked.connect(self._select_all_categories)
        self.none_btn = _fc_toolbar_button("None")
        self.none_btn.setToolTip("Uncheck every category in the list.")
        self.none_btn.clicked.connect(self._select_no_categories)
        self._fc_add_header_toolbar(
            l,
            extra_buttons=[self.all_btn, self.none_btn],
        )
        l.addWidget(self.cb)
        self.list_widget = QListWidget()
        self.list_widget.setSelectionMode(QAbstractItemView.NoSelection)
        self.list_widget.setMaximumHeight(_FC_LIST_MAX)
        self.list_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.list_widget.setMinimumWidth(0)
        # Cached for ``row_matches`` during a single ``apply_filters`` pass (avoid O(rows × list) work).
        self._category_checked_cache: frozenset[str] | None = None
        self._category_n_checkable_cache: int | None = None
        self.list_widget.itemChanged.connect(self._on_category_list_item_changed)
        l.addWidget(self.list_widget)
        self._populate_list()

    def _bust_category_selection_cache(self) -> None:
        self._category_checked_cache = None
        self._category_n_checkable_cache = None

    def _on_category_list_item_changed(self, _it) -> None:
        self._bust_category_selection_cache()
        self.changed.emit()

    def _set_all_category_checkstates(self, state) -> None:
        self.list_widget.blockSignals(True)
        for i in range(self.list_widget.count()):
            it = self.list_widget.item(i)
            if it.flags() & Qt.ItemIsUserCheckable:
                it.setCheckState(state)
        self.list_widget.blockSignals(False)
        self._bust_category_selection_cache()
        self.changed.emit()

    def _select_all_categories(self) -> None:
        self._set_all_category_checkstates(Qt.Checked)

    def _select_no_categories(self) -> None:
        self._set_all_category_checkstates(Qt.Unchecked)

    def _ensure_category_filter_cache(self) -> None:
        if self._category_checked_cache is not None:
            return
        out: list[str] = []
        n_checkable = 0
        for i in range(self.list_widget.count()):
            it = self.list_widget.item(i)
            if it.flags() & Qt.ItemIsUserCheckable:
                n_checkable += 1
                if it.checkState() == Qt.Checked:
                    out.append(self._role_value(it))
        self._category_checked_cache = frozenset(out)
        self._category_n_checkable_cache = n_checkable

    def _on_column_changed(self, _t: str) -> None:
        QTimer.singleShot(0, lambda: self._populate_list())

    def set_column(self, name: str) -> None:
        if name and self.cb.findText(name) >= 0:
            self.cb.blockSignals(True)
            self.cb.setCurrentText(name)
            self.cb.blockSignals(False)
            self._populate_list()

    def column_name(self) -> str:
        return (self.cb.currentText() or "").strip()

    def checked_values(self) -> frozenset[str]:
        self._ensure_category_filter_cache()
        return self._category_checked_cache or frozenset()

    def _role_value(self, item: QListWidgetItem) -> str:
        d = item.data(Qt.UserRole)
        if d == self._BLANK:
            return ""
        return str(d) if d is not None else (item.text() or "")

    def _populate_list(self, select_values: frozenset[str] | None = None) -> None:
        self._bust_category_selection_cache()
        self.list_widget.blockSignals(True)
        self.list_widget.clear()
        prop = self.cb.currentText()
        if not prop or prop not in self.app.headers:
            self.list_widget.blockSignals(False)
            self.changed.emit()
            return
        ordered: list[str] = []
        cap = 2000
        ensure_sqlite = getattr(self.app, "_ensure_sqlite_store_current", None)
        store = getattr(self.app, "_sqlite_store", None)
        sqlite_ready = True
        if callable(ensure_sqlite):
            sqlite_ready = ensure_sqlite()
        if sqlite_ready and store is not None and prop in store.headers:
            ordered = store.distinct_values(prop, limit=cap + 1)
        else:
            seen: set[str] = set()
            for r in range(self.app._table_model.rowCount()):
                v = self.app._table_model.value_for_header(r, prop) or ""
                if v not in seen:
                    seen.add(v)
                    ordered.append(v)
            ordered.sort(key=lambda x: x.lower())
        truncated = len(ordered) > cap
        for v in ordered[:cap]:
            label = "(blank)" if v == "" else v
            it = QListWidgetItem(label)
            it.setData(Qt.UserRole, self._BLANK if v == "" else v)
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            want = select_values
            if want is None:
                it.setCheckState(Qt.Checked)
            else:
                it.setCheckState(Qt.Checked if v in want else Qt.Unchecked)
            self.list_widget.addItem(it)
        self.list_widget.blockSignals(False)
        if truncated:
            tip = QListWidgetItem(f"… ({len(ordered)} distinct; showing first {cap})")
            tip.setFlags(tip.flags() & ~Qt.ItemIsUserCheckable)
            self.list_widget.addItem(tip)
        self.changed.emit()

    def update_prop_list(self, new_props, old_n=None, new_n=None):
        self.cb.blockSignals(True)
        current = self.cb.currentText()
        self.cb.clear()
        self.cb.addItems(new_props)
        if old_n and current == old_n:
            if new_n:
                self.cb.setCurrentText(new_n)
                self.cb.blockSignals(False)
                self._populate_list()
                return False
            self.cb.blockSignals(False)
            return True
        if current and self.cb.findText(current) >= 0:
            self.cb.setCurrentText(current)
        elif self.cb.count():
            self.cb.setCurrentIndex(0)
        self.cb.blockSignals(False)
        self._populate_list()
        return False

    def _checked_values(self) -> frozenset[str]:
        self._ensure_category_filter_cache()
        return self._category_checked_cache or frozenset()

    def row_matches(self, row: int) -> bool:
        self._ensure_category_filter_cache()
        prop = self.cb.currentText()
        if not prop:
            return True
        raw = self.app._table_model.value_for_header(row, prop) or ""
        n_checkable = int(self._category_n_checkable_cache or 0)
        if n_checkable == 0:
            return True
        sel = self._category_checked_cache or frozenset()
        inside = raw in sel if sel else False
        if self._invert_on:
            return not inside
        return inside

    def get_cfg(self):
        return {
            "column": self.cb.currentText(),
            "values": sorted(self._checked_values()),
            "enabled": self._filter_enabled_on,
            "inverted": self._invert_on,
        }

    def restore_from_session(self, prop: str, values: list[str]) -> None:
        self.cb.blockSignals(True)
        if prop and self.cb.findText(prop) >= 0:
            self.cb.setCurrentText(prop)
        self.cb.blockSignals(False)
        self._populate_list(frozenset(str(x) for x in (values or [])))


def next_default_filter_title(existing_filters: list, card_cls: type) -> str:
    """Return "Type" or "Type N" for the next card of ``card_cls``."""
    if card_cls is FilterCard:
        base = "Slider"
    elif card_cls is SubstructureFilterCard:
        base = "Substructure"
    elif card_cls is TextFilterCard:
        base = "Text"
    elif card_cls is CategoryFilterCard:
        base = "Category"
    else:
        base = "Filter"
    n = sum(1 for f in existing_filters if isinstance(f, card_cls))
    return base if n == 0 else f"{base} {n + 1}"
