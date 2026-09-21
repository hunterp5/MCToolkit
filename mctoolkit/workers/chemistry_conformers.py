# This file is part of MCToolkit.
# Copyright (C) 2026 Hunter Picard
#
# MCToolkit is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# MCToolkit is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with MCToolkit. If not, see <https://www.gnu.org/licenses/>.

"""Compatibility re-exports for conformer generation, superposition, RMSD, and strain.

Prefer importing from ``conformer_generation``, ``superpose``, or ``strain_energy``.
This module remains stable for existing imports.
"""

from __future__ import annotations

from .conformer_generation import (
    ConformerGenParams,
    ConformerGenerationWorker,
    run_conformer_generation,
)
from .strain_energy import (
    STRAIN_ENERGY_HEADERS,
    StrainEnergyParams,
    StrainEnergyWorker,
    run_strain_energy,
    strain_overlay_for_blocks_b64,
    strain_overlay_for_mol,
    strain_overlay_for_mols,
)
from .superpose import (
    RmsdParams,
    SuperposeConformersWorker,
    SuperposeParams,
    SuperposeStructuresParams,
    SuperposeStructuresWorker,
    align_structure_onto_reference,
    run_conformer_rmsd,
    run_superpose_conformers,
    run_superpose_structures,
)

__all__ = [
    "ConformerGenParams",
    "ConformerGenerationWorker",
    "RmsdParams",
    "STRAIN_ENERGY_HEADERS",
    "StrainEnergyParams",
    "StrainEnergyWorker",
    "SuperposeConformersWorker",
    "SuperposeParams",
    "SuperposeStructuresParams",
    "SuperposeStructuresWorker",
    "align_structure_onto_reference",
    "run_conformer_generation",
    "run_conformer_rmsd",
    "run_strain_energy",
    "run_superpose_conformers",
    "run_superpose_structures",
    "strain_overlay_for_blocks_b64",
    "strain_overlay_for_mol",
    "strain_overlay_for_mols",
]
