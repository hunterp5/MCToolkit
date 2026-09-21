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

"""Shared filter-card chrome, drag/drop host, and enable/invert controls."""

from contextlib import suppress

from PySide6.QtCore import QEvent, QMimeData, QPoint, Qt
from PySide6.QtGui import QDrag
from PySide6.QtWidgets import (
    QAbstractButton,
    QAbstractItemView,
    QAbstractSlider,
    QApplication,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .range_slider import RangeSlider

# --- Filter cards (compact; panel scrolls) -------------------------------------
FILTER_CARD_MIME = "application/x-mctoolkit-filter-card"
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


def _mime_has_filter_card(mime: QMimeData) -> bool:
    return mime.hasFormat(FILTER_CARD_MIME)


def _filter_card_mime_payload(mime: QMimeData) -> bytes:
    if mime.hasFormat(FILTER_CARD_MIME):
        return bytes(mime.data(FILTER_CARD_MIME))
    return b""


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
    cb.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
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
    """True mixin: drag empty card chrome to reorder (shared by all filter card types)."""

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
            drag.exec(Qt.MoveAction)
        finally:
            polish_widget_property(self, "fcDragging", False)


class FilterCardsHost(QWidget):
    """Scroll-area contents that accept filter-card drops for reordering."""

    def __init__(self, on_reorder=None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._on_reorder = on_reorder
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event) -> None:  # noqa: N802 — Qt API
        if _mime_has_filter_card(event.mimeData()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:  # noqa: N802 — Qt API
        if _mime_has_filter_card(event.mimeData()):
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
            wanted = int(_filter_card_mime_payload(mime).decode("ascii"))
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
    """True mixin: shared On/Off + Invert controls. Subclasses must define ``changed`` and ``removed``."""

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
        with suppress(TypeError):
            edit.editingFinished.disconnect(self._fc_commit_title_edit)
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
        with suppress(TypeError):
            edit.editingFinished.disconnect(self._fc_commit_title_edit)
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
