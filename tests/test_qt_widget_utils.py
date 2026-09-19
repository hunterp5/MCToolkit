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

"""Shared Qt widget helpers."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDoubleSpinBox,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from molmanager.ui.qt_widget_utils import (
    append_viewer_log,
    install_unfocused_wheel_passthrough,
)


def _wheel_event(widget: QWidget, *, delta: int = 120) -> QWheelEvent:
    pos = QPointF(widget.rect().center())
    global_pos = QPointF(widget.mapToGlobal(widget.rect().center()))
    return QWheelEvent(
        pos,
        global_pos,
        QPoint(0, 0),
        QPoint(0, delta),
        Qt.NoButton,
        Qt.NoModifier,
        Qt.ScrollUpdate,
        False,
    )


def _scroll_host(qapp: QApplication) -> tuple[QScrollArea, QDoubleSpinBox, QComboBox]:
    install_unfocused_wheel_passthrough(qapp)
    scroll = QScrollArea()
    inner = QWidget()
    inner.setMinimumHeight(2000)
    layout = QVBoxLayout(inner)
    spin = QDoubleSpinBox()
    spin.setRange(0.0, 14.0)
    spin.setSingleStep(1.0)
    spin.setValue(7.4)
    combo = QComboBox()
    combo.addItems(["one", "two", "three"])
    layout.addWidget(spin)
    layout.addWidget(combo)
    scroll.setWidget(inner)
    scroll.resize(360, 240)
    scroll.show()
    qapp.processEvents()
    return scroll, spin, combo


def _click(widget: QWidget) -> None:
    pos = QPointF(widget.rect().center())
    global_pos = QPointF(widget.mapToGlobal(widget.rect().center()))
    press = QMouseEvent(
        QEvent.MouseButtonPress,
        pos,
        global_pos,
        Qt.LeftButton,
        Qt.LeftButton,
        Qt.NoModifier,
    )
    QApplication.sendEvent(widget, press)
    widget.setFocus(Qt.MouseFocusReason)


def test_install_unfocused_wheel_passthrough_is_idempotent(qapp):
    first = install_unfocused_wheel_passthrough(qapp)
    second = install_unfocused_wheel_passthrough(qapp)
    assert first is not None
    assert first is second


def test_append_viewer_log_forwards_when_present():
    seen: list[str] = []

    class _Host:
        def append_log(self, text: str) -> None:
            seen.append(text)

    append_viewer_log(_Host(), "line")
    append_viewer_log(object(), "ignored")
    append_viewer_log(None, "ignored")
    assert seen == ["line"]


def test_append_viewer_log_records_session_log_without_viewer():
    from molmanager.platform_support.session_log import session_log_buffer

    session_log_buffer().clear()
    append_viewer_log(None, "no viewer")
    entries, _seq, _gen = session_log_buffer().snapshot()
    assert [e.message for e in entries] == ["no viewer"]
    assert entries[0].source == "ui"


def test_unfocused_spin_and_combo_do_not_eat_wheel(qapp):
    scroll, spin, combo = _scroll_host(qapp)
    spin.clearFocus()
    combo.clearFocus()
    qapp.processEvents()
    bar = scroll.verticalScrollBar()
    bar.setValue(0)

    QApplication.sendEvent(spin, _wheel_event(spin, delta=-120))
    qapp.processEvents()
    assert spin.value() == 7.4
    assert bar.value() > 0

    bar.setValue(0)
    QApplication.sendEvent(combo, _wheel_event(combo, delta=-120))
    qapp.processEvents()
    assert combo.currentText() == "one"
    assert bar.value() > 0
    scroll.close()


def test_unfocused_spin_line_edit_does_not_eat_wheel(qapp):
    scroll, spin, _combo = _scroll_host(qapp)
    edit = spin.lineEdit()
    assert edit is not None
    spin.clearFocus()
    edit.clearFocus()
    qapp.processEvents()
    bar = scroll.verticalScrollBar()
    bar.setValue(0)

    QApplication.sendEvent(edit, _wheel_event(edit, delta=-120))
    qapp.processEvents()
    assert spin.value() == 7.4
    assert bar.value() > 0
    scroll.close()


def test_auto_focused_spin_does_not_eat_wheel(qapp):
    scroll, spin, _combo = _scroll_host(qapp)
    spin.setFocus(Qt.OtherFocusReason)
    qapp.processEvents()
    bar = scroll.verticalScrollBar()
    bar.setValue(0)

    QApplication.sendEvent(spin, _wheel_event(spin, delta=-120))
    qapp.processEvents()
    assert spin.value() == 7.4
    assert bar.value() > 0
    scroll.close()


def test_clicked_spin_still_accepts_wheel(qapp):
    scroll, spin, _combo = _scroll_host(qapp)
    _click(spin)
    qapp.processEvents()
    bar = scroll.verticalScrollBar()
    bar.setValue(0)

    QApplication.sendEvent(spin, _wheel_event(spin))
    qapp.processEvents()
    assert spin.value() == 8.4
    assert bar.value() == 0
    scroll.close()


def test_clicked_spin_line_edit_accepts_wheel(qapp):
    scroll, spin, _combo = _scroll_host(qapp)
    edit = spin.lineEdit()
    assert edit is not None
    _click(edit)
    qapp.processEvents()

    QApplication.sendEvent(edit, _wheel_event(edit))
    qapp.processEvents()
    assert spin.value() == 8.4
    scroll.close()


def test_unipka_cuda_hint_shows_once(qapp, monkeypatch):  # noqa: ARG001
    from PySide6.QtWidgets import QMessageBox, QWidget

    from molmanager.ui.pka_gpu_hint import maybe_remind_unipka_cuda_wheel

    shown: list[int] = []

    def _info(*_a, **_k):
        shown.append(1)
        return QMessageBox.Ok

    monkeypatch.setattr("molmanager.ui.pka_gpu_hint.cpu_torch_with_nvidia_gpu", lambda: True)
    monkeypatch.setattr(QMessageBox, "information", _info)
    host = QWidget()
    maybe_remind_unipka_cuda_wheel(host)
    maybe_remind_unipka_cuda_wheel(host)
    assert shown == [1]
    host.close()
