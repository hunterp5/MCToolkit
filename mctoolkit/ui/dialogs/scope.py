# This file is part of mctoolkit.
# Copyright (C) 2026 Hunter Picard
#
# mctoolkit is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# mctoolkit is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with mctoolkit.  If not, see <https://www.gnu.org/licenses/>.

"""Shared helpers for tool dialogs (selection scope, etc.)."""

from __future__ import annotations

from PySide6.QtWidgets import QDialog


def selection_scope_checked(dialog: QDialog) -> bool:
    """
    True when the dialog's “Selected Rows Only” scope checkbox is checked and the parent
    main window currently has at least one selected table row.
    """
    cb = getattr(dialog, "only_selected_cb", None)
    if cb is None or not cb.isChecked():
        return False
    host = getattr(dialog, "parent_app", None) or dialog.parent()
    if host is not None and hasattr(host, "_selected_logical_rows"):
        return len(host._selected_logical_rows()) > 0
    return bool(getattr(dialog, "_have_selection", False))
