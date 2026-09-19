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

"""Status chrome and tool-progress owner for the main window."""

from __future__ import annotations

from .app_kernel import AppKernel, bind_mixin_methods
from .main_window.app_progress_mixin import AppProgressMixin


class ProgressController:
    """Owns tool-progress / status-chrome behavior; state stays on the kernel.

    Legacy ``bind_mixin_methods`` still supplies the mixin body. New methods: ``self._app``.
    """

    def __init__(self, app: AppKernel) -> None:
        self._app = app
        bind_mixin_methods(self, app, AppProgressMixin)
