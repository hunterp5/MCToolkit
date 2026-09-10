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

"""Shared helpers for one-at-a-time modeless tool windows (plotter, sketcher, etc.)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PyQt5.QtWidgets import QWidget

from .qt_widget_utils import qobject_is_deleted


def reuse_or_show_modeless_singleton(
    host: Any,
    attr_name: str,
    factory: Callable[[], QWidget],
    on_destroyed: Callable[[], None],
    *,
    on_reused_visible: Callable[[QWidget], None] | None = None,
) -> QWidget:
    """
    If ``getattr(host, attr_name)`` is a live widget, ``show()`` / ``raise_()`` / ``activateWindow()``
    and optionally ``on_reused_visible(dlg)``. Otherwise create with ``factory()``, assign it,
    connect ``destroyed`` to ``on_destroyed``, and ``show()``.

    Reuses the same instance even when it is **not visible** (e.g. minimized or hidden after
    ``close()`` without ``WA_DeleteOnClose``), so a long-running tool job is not orphaned when
    the user reopens the menu action.

    ``factory`` should return a fully configured dialog (modal flags, signals, etc.) before show.
    """
    dlg = getattr(host, attr_name, None)
    if dlg is not None:
        try:
            from PyQt5 import sip

            if sip.isdeleted(dlg):
                setattr(host, attr_name, None)
                dlg = None
        except Exception:
            pass
    if dlg is not None:
        try:
            dlg.show()
            dlg.raise_()
            dlg.activateWindow()
            if on_reused_visible is not None:
                on_reused_visible(dlg)
            return dlg
        except RuntimeError:
            setattr(host, attr_name, None)
    w = factory()
    setattr(host, attr_name, w)

    def _on_destroyed(*_args, obj=w) -> None:
        if qobject_is_deleted(host):
            return
        try:
            if getattr(host, attr_name, None) is not obj:
                return
            on_destroyed()
        except RuntimeError:
            pass

    w.destroyed.connect(_on_destroyed)
    w.show()
    return w
