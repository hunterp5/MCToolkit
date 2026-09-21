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
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with MCToolkit.  If not, see <https://www.gnu.org/licenses/>.

"""selection_scope_checked respects parent_app on docked tool panels."""

from __future__ import annotations

from types import SimpleNamespace

from mctoolkit.ui.dialogs.scope import selection_scope_checked


def test_selection_scope_checked_uses_parent_app_not_dock_parent() -> None:
    host = SimpleNamespace(_rows=[0, 1])
    host._selected_logical_rows = lambda: list(host._rows)
    dock = object()
    dlg = SimpleNamespace(
        parent_app=host,
        parent=lambda: dock,
        only_selected_cb=SimpleNamespace(isChecked=lambda: True),
        _have_selection=False,
    )
    assert selection_scope_checked(dlg) is True
    host._rows = []
    assert selection_scope_checked(dlg) is False
