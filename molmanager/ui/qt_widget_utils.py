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

"""Small Qt widget helpers shared across dialogs (keep dependency-free beyond PyQt5)."""

from __future__ import annotations

from typing import Any

from PyQt5.QtCore import QObject, Qt
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import QTextEdit, QWidget


def qobject_is_deleted(obj: Any) -> bool:
    """Return True when *obj* is missing or its C++ QObject has already been destroyed."""
    if obj is None:
        return True
    try:
        from PyQt5 import sip

        if isinstance(obj, QObject) and sip.isdeleted(obj):
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


def make_window_minimizable(widget: QWidget) -> None:
    """Add minimize and maximize buttons to a secondary top-level window (e.g. ``QDialog``)."""
    flags = widget.windowFlags()
    flags |= Qt.WindowMinimizeButtonHint | Qt.WindowMaximizeButtonHint
    widget.setWindowFlags(flags)
