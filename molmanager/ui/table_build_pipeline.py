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

"""Ingest chunks, SQLite mirror rebuild, and Render 2D batch/result flush."""

from __future__ import annotations

from PyQt5.QtCore import QObject

from .app_kernel import AppKernel, bind_mixin_methods
from .main_window.ingest_load_mixin import IngestLoadMixin
from .main_window.render_2d_mixin import Render2DMixin
from .main_window.render2d_results_mixin import Render2DResultsMixin
from .main_window.sqlite_rebuild_mixin import SqliteRebuildMixin
from .main_window.structure_layout_mixin import StructureLayoutMixin


class TableBuildPipeline(QObject):
    """GUI-thread table-build owner. Timers and generation counters stay on the kernel.

    Legacy ``bind_mixin_methods`` still supplies ingest/render bodies. New methods: ``self._app``.
    """

    def __init__(self, app: AppKernel) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self._app = app
        bind_mixin_methods(
            self,
            app,
            IngestLoadMixin,
            SqliteRebuildMixin,
            StructureLayoutMixin,
            Render2DMixin,
            Render2DResultsMixin,
        )
