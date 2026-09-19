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

"""Chunked chemistry-tool column writeback and unique header naming."""

from __future__ import annotations

from .app_kernel import AppKernel, bind_mixin_methods
from .main_window.column_write_mixin import ColumnWriteMixin


class TableWriteService:
    """Owns ``on_calc_finished`` / column insert naming; mutates the kernel table.

    Bodies are still bound via legacy ``bind_mixin_methods`` (window as ``self``).
    New methods on this class should use ``self._app`` instead of binding another mixin.
    """

    def __init__(self, app: AppKernel) -> None:
        self._app = app
        bind_mixin_methods(self, app, ColumnWriteMixin)
