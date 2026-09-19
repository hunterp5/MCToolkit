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

"""Parameter dataclasses for conformer/structure superposition and RMSD."""

from __future__ import annotations

from dataclasses import dataclass

# Combo keys and labels for SuperposeDialog. Worker params use the keys, not the text.
SUPERPOSE_TARGET_LABELS: tuple[tuple[str, str], ...] = (
    ("conformers", "Conformers in each row"),
    ("structures", "Structures across rows"),
)
SUPERPOSE_GEOMETRY_LABELS: tuple[tuple[str, str], ...] = (
    ("3d", "3D spatial"),
    ("2d", "2D topological"),
)
SUPERPOSE_ALIGN_ON_LABELS: tuple[tuple[str, str], ...] = (
    ("", "Whole molecule"),
    ("largest_ring", "Largest ring system"),
    ("central_ring", "Most central ring"),
    ("pattern", "Custom pattern"),
)


@dataclass(frozen=True)
class SuperposeParams:
    """Options for :func:`run_superpose_conformers` / :class:`SuperposeConformersWorker`."""

    reference_conformer_index: int = 0
    heavy_atoms_only: bool = True
    reflect: bool = False
    max_align_iters: int = 50
    # When non-empty, RMS alignment uses only atoms matching this pattern (SMILES or SMARTS).
    align_pattern: str = ""
    align_pattern_is_smarts: bool = False
    # ``3d``: rigid AlignMol. ``2d``: topological 2D depiction matching.
    geometry: str = "3d"
    # ``largest_ring`` / ``central_ring`` when no custom pattern is set.
    align_mode: str = ""


@dataclass(frozen=True)
class SuperposeStructuresParams:
    """Options for aligning distinct table structures onto a reference molecule."""

    heavy_atoms_only: bool = True
    reflect: bool = False
    max_align_iters: int = 50
    align_pattern: str = ""
    align_pattern_is_smarts: bool = False
    use_mcs: bool = True
    # ``3d``: AlignMol / O3A. ``2d``: topological 2D depiction matching.
    geometry: str = "3d"
    # 3D only: Crippen/MMFF O3A (then index-map) when pattern and MCS yield no atom map.
    use_o3a: bool = True
    # ``largest_ring`` / ``central_ring`` when no custom pattern is set.
    align_mode: str = ""


@dataclass(frozen=True)
class RmsdParams:
    """Options for :func:`run_conformer_rmsd`."""

    reference_conformer_index: int = 0
    heavy_atoms_only: bool = True
    reflect: bool = False
    max_align_iters: int = 50
    align_pattern: str = ""
    align_pattern_is_smarts: bool = False
    source_column: str = "confs"
