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

"""Optional grouping of chemistry file-splits. ``ChemistryWorkspaceWindow`` does not inherit this."""

from __future__ import annotations

from ..workspace_activity_cliff import ActivityCliffTools
from ..workspace_mmp import MmpTools
from ..workspace_mmp_neighborhood import MmpNeighborhoodTools
from ..workspace_sali import SaliTools
from .conformers_descriptors_mixin import ConformersDescriptorsMixin
from .fragment_tools_mixin import FragmentToolsMixin
from .ingest_render_mixin import IngestRenderMixin
from .plot_tools_mixin import PlotToolsMixin
from .prepare_structures_mixin import PrepareStructuresMixin
from .reaction_tools_mixin import ReactionToolsMixin
from .tools_sql_predict_mixin import ToolsSqlPredictMixin


class ChemistryMixin(
    PlotToolsMixin,
    IngestRenderMixin,
    PrepareStructuresMixin,
    ConformersDescriptorsMixin,
    FragmentToolsMixin,
    MmpTools,
    ActivityCliffTools,
    MmpNeighborhoodTools,
    SaliTools,
    ReactionToolsMixin,
    ToolsSqlPredictMixin,
):
    """Compat grouping only — not a window base. Do not add new composite mixins."""
