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


"""Compatibility re-exports for the protein viewer."""

from __future__ import annotations


from .protein_chain_manager import ProteinChainManager
from .protein_embed import ProteinEmbedView
from .protein_viewer_dialog import ProteinViewerDialog
from .protein_viewer_html import build_protein_viewer_html
from .protein_viewer_models import (
    COMPONENT_COLOR_CHOICES,
    COMPONENT_STYLE_CHOICES,
    LIGAND_STYLE_CHOICES,
    NamedManagerGroup,
    STRUCTURE_FILE_FILTER,
    STRUCTURE_SAVE_FILTER,
    USER_GROUP_KIND,
    _GROUP_ROLE,
    _ID_ROLE,
    _KIND_ROLE,
    _STRUCT_ROLE,
    _ComponentView,
    _LoadedSlot,
    _component_state_key,
)

__all__ = [
    "COMPONENT_COLOR_CHOICES",
    "COMPONENT_STYLE_CHOICES",
    "LIGAND_STYLE_CHOICES",
    "ProteinChainManager",
    "ProteinEmbedView",
    "ProteinViewerDialog",
    "STRUCTURE_FILE_FILTER",
    "STRUCTURE_SAVE_FILTER",
    "build_protein_viewer_html",
    "_ComponentView",
    "_GROUP_ROLE",
    "_ID_ROLE",
    "_KIND_ROLE",
    "_LoadedSlot",
    "_STRUCT_ROLE",
    "_component_state_key",
    "NamedManagerGroup",
    "USER_GROUP_KIND",
]
