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

"""Modeless singleton helper (Tools dialogs depend on correct reuse)."""

from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QWidget

from molmanager.ui.singleton_modeless_dialog import reuse_or_show_modeless_singleton


def test_reuse_or_show_modeless_singleton_reuses_hidden_widget(qapp):  # noqa: ARG001
    """Opening the menu again must not replace the singleton while the widget still exists (hidden)."""
    destroyed = []

    class Host:
        def __init__(self) -> None:
            self._dlg = None

    host = Host()
    created: list[QWidget] = []

    def factory() -> QWidget:
        w = QWidget()
        w.setWindowFlags(Qt.Window)
        created.append(w)
        return w

    def on_destroyed() -> None:
        destroyed.append(True)

    w1 = reuse_or_show_modeless_singleton(host, "_dlg", factory, on_destroyed)
    assert len(created) == 1
    w1.hide()
    qapp.processEvents()

    w2 = reuse_or_show_modeless_singleton(host, "_dlg", factory, on_destroyed)
    assert w2 is w1
    assert len(created) == 1
    assert not destroyed


def test_destroyed_callback_does_not_clear_replaced_singleton(qapp) -> None:
    class Host:
        def __init__(self) -> None:
            self._dlg = None

    host = Host()
    created: list[QWidget] = []

    def factory() -> QWidget:
        w = QWidget()
        w.setWindowFlags(Qt.Window)
        created.append(w)
        return w

    def on_destroyed() -> None:
        host._dlg = None

    w1 = reuse_or_show_modeless_singleton(host, "_dlg", factory, on_destroyed)
    host._dlg = None
    w2 = reuse_or_show_modeless_singleton(host, "_dlg", factory, on_destroyed)
    assert w2 is not w1
    w1.deleteLater()
    qapp.processEvents()
    assert host._dlg is w2
    w2.close()
    w2.deleteLater()
    qapp.processEvents()


def test_destroyed_callback_skips_deleted_qobject_host(qapp) -> None:
    """Quit must not call QObject methods on a host that Qt already destroyed."""
    from PyQt5.QtWidgets import QDialog

    host = QWidget()
    host._dlg = None

    def factory() -> QWidget:
        return QDialog(host)

    def on_destroyed() -> None:
        host.sender()

    reuse_or_show_modeless_singleton(host, "_dlg", factory, on_destroyed)
    host.deleteLater()
    qapp.processEvents()
    qapp.processEvents()


def test_qobject_is_deleted_for_live_and_missing() -> None:
    from molmanager.ui.qt_widget_utils import qobject_is_deleted

    assert qobject_is_deleted(None) is True
    w = QWidget()
    assert qobject_is_deleted(w) is False
    w.deleteLater()
