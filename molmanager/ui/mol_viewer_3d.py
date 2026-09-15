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

"""Compatibility re-exports for the ligand 3D viewer.

Prefer ``mol_3d_html``, ``mol_3d_prepare``, ``mol_3d_embed``, ``mol_3d_strain``,
``mol_3d_conf_mixin``, ``mol_3d_chrome_mixin``, ``mol_3d_widget``, and ``mol_3d_dialog``.
"""

from __future__ import annotations

from .mol_3d_dialog import (
    Molecule3DViewerDialog,
    open_conformation_viewer_from_blocks_payload,
    open_molecule_2d_viewer,
    open_molecule_3d_viewer,
)
from .mol_3d_html import (
    _BUNDLED_3DMOL,
    _RESET_STRUCTURE_JS,
    _SUPERPOSE_PALETTE,
    _js_console_is_benign,
    _mol_block_b64,
    _offline_index_html,
    _offline_index_html_multiconf,
    _reset_structure_menu_html,
    _wire_webengine_console_logger,
    build_3dmol_html,
    bundled_3dmol_available,
    conf_legend_entries,
    distinct_superpose_colors,
    superpose_color_for_conf,
)
from .mol_3d_prepare import prepare_mol_2d, prepare_mol_3d
from .mol_3d_widget import (
    Molecule3DEmbedView,
    Molecule3DViewerWidget,
    populate_strain_energy_table,
)

__all__ = [
    "Molecule3DEmbedView",
    "Molecule3DViewerDialog",
    "Molecule3DViewerWidget",
    "build_3dmol_html",
    "bundled_3dmol_available",
    "conf_legend_entries",
    "distinct_superpose_colors",
    "open_conformation_viewer_from_blocks_payload",
    "open_molecule_2d_viewer",
    "open_molecule_3d_viewer",
    "populate_strain_energy_table",
    "prepare_mol_2d",
    "prepare_mol_3d",
    "superpose_color_for_conf",
    "_BUNDLED_3DMOL",
    "_RESET_STRUCTURE_JS",
    "_SUPERPOSE_PALETTE",
    "_js_console_is_benign",
    "_mol_block_b64",
    "_offline_index_html",
    "_offline_index_html_multiconf",
    "_reset_structure_menu_html",
    "_wire_webengine_console_logger",
]
