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

import logging
import weakref
from collections.abc import Callable
from typing import Any

from PyQt5.QtWidgets import QWidget

from .qt_widget_utils import qobject_is_deleted

logger = logging.getLogger(__name__)


def reuse_or_show_modeless_singleton(
    host: Any,
    attr_name: str,
    factory: Callable[[], QWidget],
    on_destroyed: Callable[[], None] | None = None,
    *,
    on_reused_visible: Callable[[QWidget], None] | None = None,
    show: bool = True,
) -> QWidget:
    """
    If ``getattr(host, attr_name)`` is a live widget, ``show()`` / ``raise_()`` / ``activateWindow()``
    and optionally ``on_reused_visible(dlg)``. Otherwise create with ``factory()``, assign it,
    connect ``destroyed`` so the attribute is cleared, and ``show()``.

    Reuses the same instance even when it is **not visible** (e.g. minimized or hidden after
    ``close()`` without ``WA_DeleteOnClose``), so a long-running tool job is not orphaned when
    the user reopens the menu action.

    The helper always sets ``host.attr_name`` to ``None`` when the tracked widget is destroyed,
    and ignores a ``destroyed`` signal from a widget it no longer tracks. Pass *on_destroyed*
    only for extra teardown (for example clearing a docked pose). A one-line
    ``self._foo = None`` callback is redundant.

    Pass ``show=False`` to create or reuse without raising the window.

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
            if show:
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

    host_ref = weakref.ref(host)

    def _on_destroyed(
        *_args, obj=w, host_ref=host_ref, attr_name=attr_name, on_destroyed=on_destroyed
    ) -> None:
        """Forget the tracked widget, and never raise while doing it.

        PyQt turns an exception escaping a slot into ``qFatal``, which aborts the process. This
        slot runs at the worst possible moment: host, dialog, and this very closure form a
        reference cycle, so the collector is what frees them, and destroying the host is what
        emits ``destroyed`` in the first place. Holding the host weakly keeps it out of that
        cycle, and binding the rest as defaults keeps them off closure cells the collector can
        empty before this runs.
        """
        try:
            host = host_ref()
            if host is None or qobject_is_deleted(host):
                return
            if getattr(host, attr_name, None) is not obj:
                return
            setattr(host, attr_name, None)
            if on_destroyed is not None:
                on_destroyed()
        except Exception:
            logger.debug("Modeless singleton teardown slot failed", exc_info=True)

    w.destroyed.connect(_on_destroyed)
    if show:
        w.show()
    return w
