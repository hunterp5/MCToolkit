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

"""Qt test helpers (PySide6 ownership quirks)."""

from __future__ import annotations

from typing import Any


def qt_submenu(parent: Any, title: str | None = None):
    """Return a QMenu from *parent*'s actions without dropping the owning QAction.

    ``next(a.menu() for a in parent.actions() ...)`` lets PySide6 collect the QAction
    wrapper and destroy the C++ QMenu.
    """
    actions = list(parent.actions())
    if title is None:
        action = next(a for a in actions if a.menu() is not None)
    else:
        want = title.replace("&", "")
        action = next(a for a in actions if a.text().replace("&", "") == want)
    menu = action.menu()
    if menu is None:
        raise AssertionError(f"no submenu named {title!r}")
    kept = getattr(parent, "_qt_kept_actions", None)
    if kept is None:
        kept = []
        parent._qt_kept_actions = kept
    kept.append(action)
    return menu
