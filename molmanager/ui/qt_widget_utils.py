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

"""Small Qt widget helpers shared across dialogs (keep dependency-free beyond PySide6)."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QEvent, QObject, QPointF, Qt
from PySide6.QtGui import QFont, QMouseEvent, QWheelEvent
from PySide6.QtWidgets import (
    QAbstractScrollArea,
    QAbstractSpinBox,
    QApplication,
    QComboBox,
    QDial,
    QSlider,
    QTextEdit,
    QWidget,
)


def qobject_is_deleted(obj: Any) -> bool:
    """Return True when *obj* is missing or its C++ QObject has already been destroyed."""
    if obj is None:
        return True
    try:
        import shiboken6

        if isinstance(obj, QObject) and not shiboken6.isValid(obj):
            return True
    except Exception:
        return True
    return False


def monospace_text_font() -> QFont:
    f = QFont("Consolas")
    if not f.exactMatch():
        f = QFont("Courier New")
    f.setStyleHint(QFont.Monospace)
    return f


def apply_monospace_to_text_edit(w: QTextEdit) -> None:
    w.setFont(monospace_text_font())


def append_viewer_log(viewer, text: str) -> None:
    """Forward a progress line to Protein Viewer ``append_log`` when present.

    When the viewer is missing, the line still goes to the session Log window.
    """
    t = (text or "").rstrip()
    if not t:
        return
    append = getattr(viewer, "append_log", None)
    if callable(append):
        append(text)
        return
    from ..platform_support.session_log import record_ui_log

    record_ui_log(t, name="molmanager.ui.tools")


def make_window_minimizable(widget: QWidget) -> None:
    """Add minimize and maximize buttons to a secondary top-level window (e.g. ``QDialog``)."""
    flags = widget.windowFlags()
    flags |= Qt.WindowMinimizeButtonHint | Qt.WindowMaximizeButtonHint
    widget.setWindowFlags(flags)


_WHEEL_STEALERS = (QAbstractSpinBox, QComboBox, QSlider, QDial)
_WHEEL_FILTER_NAME = "molmanager_unfocused_wheel_passthrough"
_WHEEL_CLICK_ARMED = "molmanager_wheel_click_armed"


def _is_wheel_stealing_control(obj: object) -> bool:
    return isinstance(obj, _WHEEL_STEALERS)


def _disable_wheel_focus(widget: QWidget) -> None:
    """Wheel must not focus spin boxes / combos; click (or Tab) still can."""
    if widget.focusPolicy() == Qt.WheelFocus:
        widget.setFocusPolicy(Qt.StrongFocus)


def _wheel_stealer_for(widget: QWidget) -> QWidget | None:
    """Spin box / combo under *widget*, including events that hit an inner line edit."""
    current: QWidget | None = widget
    while current is not None:
        if _is_wheel_stealing_control(current):
            return current
        current = current.parentWidget()
    return None


def _combo_popup_open(widget: QWidget) -> bool:
    if not isinstance(widget, QComboBox):
        return False
    view = widget.view()
    if view is None:
        return False
    if view.isVisible():
        return True
    container = view.parentWidget()
    return bool(container is not None and container is not widget and container.isVisible())


def _focus_is_within(stealer: QWidget) -> bool:
    fw = QApplication.focusWidget()
    if fw is None:
        return False
    return fw is stealer or stealer.isAncestorOf(fw)


def _control_should_accept_wheel(stealer: QWidget) -> bool:
    if _combo_popup_open(stealer):
        return True
    if not _focus_is_within(stealer):
        return False
    return bool(stealer.property(_WHEEL_CLICK_ARMED))


def _arm_stealer_from_click(widget: QWidget) -> None:
    stealer = _wheel_stealer_for(widget)
    if stealer is None:
        return
    _disable_wheel_focus(stealer)
    stealer.setProperty(_WHEEL_CLICK_ARMED, True)


def _nearest_scroll_area(widget: QWidget) -> QAbstractScrollArea | None:
    parent = widget.parentWidget()
    while parent is not None:
        if isinstance(parent, QAbstractScrollArea):
            return parent
        parent = parent.parentWidget()
    return None


def _clone_wheel_event(target: QWidget, event: QWheelEvent) -> QWheelEvent:
    global_pos = event.globalPosition()
    local = QPointF(target.mapFromGlobal(global_pos.toPoint()))
    return QWheelEvent(
        local,
        global_pos,
        event.pixelDelta(),
        event.angleDelta(),
        event.buttons(),
        event.modifiers(),
        event.phase(),
        event.inverted(),
    )


class _UnfocusedWheelPassthroughFilter(QObject):
    """Let page scroll win over spin boxes / combos that the cursor happens to cover."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._forwarding = False

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:  # noqa: N802
        et = event.type()
        if et in (QEvent.Enter, QEvent.Show, QEvent.FocusIn) and isinstance(obj, QWidget):
            stealer = _wheel_stealer_for(obj)
            if stealer is not None:
                _disable_wheel_focus(stealer)
            return False
        if (
            et == QEvent.MouseButtonPress
            and isinstance(event, QMouseEvent)
            and event.button() == Qt.LeftButton
            and isinstance(obj, QWidget)
        ):
            _arm_stealer_from_click(obj)
            return False
        if self._forwarding or et != QEvent.Wheel:
            return False
        if not isinstance(obj, QWidget) or not isinstance(event, QWheelEvent):
            return False
        stealer = _wheel_stealer_for(obj)
        if stealer is None:
            return False
        _disable_wheel_focus(stealer)
        if _control_should_accept_wheel(stealer):
            if obj is stealer or _combo_popup_open(stealer):
                return False
            self._forwarding = True
            try:
                QApplication.sendEvent(stealer, event)
            finally:
                self._forwarding = False
            return True
        scroll = _nearest_scroll_area(stealer)
        if scroll is None:
            event.ignore()
            return True
        viewport = scroll.viewport()
        target = viewport if viewport is not None else scroll
        self._forwarding = True
        try:
            QApplication.sendEvent(target, _clone_wheel_event(target, event))
        finally:
            self._forwarding = False
        return True


def install_unfocused_wheel_passthrough(app: QApplication | None = None) -> QObject | None:
    """Stop hover-wheel from editing spin boxes and combo boxes; keep scrolling the page.

    Qt's ``QAbstractSpinBox`` and ``QComboBox`` accept wheel events on hover (even without
    focus), which traps scrolling in Prepare and other tall forms. The inner line edit also
    forwards wheel to the spin box, so hover over the number still stole the page. Wheel
    changes a field only after a click; Tab/auto-focus is not enough.
    """
    if app is None:
        app = QApplication.instance()
    if app is None:
        return None
    existing = app.findChild(_UnfocusedWheelPassthroughFilter, _WHEEL_FILTER_NAME)
    if existing is not None and not qobject_is_deleted(existing):
        return existing
    filt = _UnfocusedWheelPassthroughFilter(app)
    filt.setObjectName(_WHEEL_FILTER_NAME)
    app.installEventFilter(filt)
    return filt
