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

"""Selection, chemistry-column lookup, and the sticky visible-row cache."""

from __future__ import annotations

from .app_kernel import AppKernel, bind_mixin_methods
from .main_window.table_chemistry_access_mixin import TableChemistryAccessMixin
from .main_window.table_selection_mixin import TableSelectionMixin


class TableSession:
    """Table selection + molecule access. Owns ``_visible_source_rows_cache`` via the kernel.

    Legacy ``bind_mixin_methods`` still supplies the mixin body. New methods: ``self._app``.
    """

    def __init__(self, app: AppKernel) -> None:
        self._app = app
        bind_mixin_methods(self, app, TableSelectionMixin, TableChemistryAccessMixin)
        self._invalidate_visible_source_rows_cache()
