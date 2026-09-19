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

"""Optional grouping (not a window base). Prep tools live on ``WorkspaceTools``."""

from __future__ import annotations

from ..table_build_render import TableBuildRender
from ..workspace_fast_prepare import FastPrepareTools
from ..workspace_protonate import ProtonateTools
from ..workspace_structure_edit import StructureEditTools
from ..workspace_structure_writeback import StructureWritebackTools


class PrepareStructuresMixin(
    ProtonateTools,
    FastPrepareTools,
    StructureEditTools,
    TableBuildRender,
    StructureWritebackTools,
):
    """Compat grouping only. Render 2D is ``TableBuildPipeline``; prep tools are ``WorkspaceTools``."""
