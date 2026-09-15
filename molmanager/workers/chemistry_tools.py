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

"""Compatibility re-exports for chemistry tool workers.

Prefer importing from ``chemistry_descriptors``, ``chemistry_conformers``, or
``chemistry_calc`` in new code. This module remains stable for existing imports.
"""

from __future__ import annotations

from .chemistry_calc import CustomCalcWorker, describe_custom_calc_error
from .chemistry_conformers import (
    ConformerGenParams,
    ConformerGenerationWorker,
    RmsdParams,
    StrainEnergyParams,
    StrainEnergyWorker,
    SuperposeConformersWorker,
    SuperposeStructuresWorker,
    SuperposeParams,
    SuperposeStructuresParams,
    align_structure_onto_reference,
    run_conformer_generation,
    run_conformer_rmsd,
    run_strain_energy,
    run_superpose_conformers,
    run_superpose_structures,
    strain_overlay_for_blocks_b64,
    strain_overlay_for_mol,
    strain_overlay_for_mols,
)
from .chemistry_descriptors import CalcWorker, descriptor_callable_for_int_fn
from ..confs_codec import format_confs_table_cell, pack_confs_cell

# Re-export strain header constants if present
try:
    from .chemistry_conformers import STRAIN_ENERGY_HEADERS
except ImportError:  # pragma: no cover
    STRAIN_ENERGY_HEADERS = ()  # type: ignore[misc, assignment]

__all__ = [
    "CalcWorker",
    "CustomCalcWorker",
    "ConformerGenParams",
    "ConformerGenerationWorker",
    "SuperposeConformersWorker",
    "SuperposeStructuresWorker",
    "SuperposeParams",
    "SuperposeStructuresParams",
    "RmsdParams",
    "StrainEnergyParams",
    "StrainEnergyWorker",
    "STRAIN_ENERGY_HEADERS",
    "describe_custom_calc_error",
    "descriptor_callable_for_int_fn",
    "format_confs_table_cell",
    "pack_confs_cell",
    "run_conformer_generation",
    "run_superpose_conformers",
    "run_superpose_structures",
    "align_structure_onto_reference",
    "run_conformer_rmsd",
    "run_strain_energy",
    "strain_overlay_for_mol",
    "strain_overlay_for_mols",
    "strain_overlay_for_blocks_b64",
]
