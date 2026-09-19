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

"""Composite grouping of chemistry mixins (not on ChemicalTableApp MRO)."""

from __future__ import annotations

from .activity_cliff_mixin import ActivityCliffMixin
from .conformers_descriptors_mixin import ConformersDescriptorsMixin
from .fragment_tools_mixin import FragmentToolsMixin
from .ingest_render_mixin import IngestRenderMixin
from .mmp_mixin import MmpMixin
from .mmp_neighborhood_mixin import MmpNeighborhoodMixin
from .plot_tools_mixin import PlotToolsMixin
from .prepare_structures_mixin import PrepareStructuresMixin
from .reaction_tools_mixin import ReactionToolsMixin
from .sali_mixin import SaliMixin
from .tools_sql_predict_mixin import ToolsSqlPredictMixin


class ChemistryMixin(
    PlotToolsMixin,
    IngestRenderMixin,
    PrepareStructuresMixin,
    ConformersDescriptorsMixin,
    FragmentToolsMixin,
    MmpMixin,
    ActivityCliffMixin,
    MmpNeighborhoodMixin,
    SaliMixin,
    ReactionToolsMixin,
    ToolsSqlPredictMixin,
):
    """Optional grouping of chemistry mixins. ``ChemicalTableApp`` no longer inherits this."""
