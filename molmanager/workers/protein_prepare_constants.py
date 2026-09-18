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


"""Shared constants for the Protein Prepare pipeline."""

from __future__ import annotations

# 10 kcal mol⁻¹ Å⁻² is a typical heavy-atom restraint for clash relief.
_DEFAULT_CA_K_KCAL = 10.0
_DEFAULT_MIN_ITERS = 400
_OPENMM_PLATFORM_AUTO = "auto"
_PDB2PQR_FF = "AMBER"
# Physiological salt for GB screening (Onufriev/Simmerling GB; OpenMM kappa conversion).
_GB_SALT_M = 0.15
_GB_TEMPERATURE_K = 298.15
_GB_SOLVENT_DIELECTRIC = 78.5
_PROTEIN_FF_AMBER14 = "amber14"
_PROTEIN_FF_AMBER99 = "amber99sbildn"
_LIGAND_FF_NONE = "none"
_LIGAND_FF_GAFF2 = "gaff2"
_LIGAND_FF_GAFF = "gaff"
_SOLVENT_GBN2 = "gbn2"
_SOLVENT_OBC2 = "obc2"
_SOLVENT_VACUUM = "vacuum"
_RESTRAINT_CA = "ca"
_RESTRAINT_BACKBONE = "backbone"
_RESTRAINT_BACKBONE_LIGAND = "backbone_ligand"
_DEFAULT_MAX_MISSING_GAP = 8
_DEFAULT_WATER_CUTOFF = 3.5

# Crystallization/buffer leftovers commonly stripped before docking.
CRYSTAL_ADDITIVE_RESIDUES = frozenset(
    {
        "EDO",
        "GOL",
        "PEG",
        "PGE",
        "PG4",
        "PE8",
        "1PE",
        "2PE",
        "P6G",
        "CME",
        "MPD",
        "MRD",
        "ACT",
        "ACY",
        "FMT",
        "SO4",
        "PO4",
        "NO3",
        "CO3",
        "CIT",
        "FLC",
        "TAR",
        "LAC",
        "BME",
        "DTT",
        "DMS",
        "IPA",
        "MOH",
        "EOH",
        "MES",
        "TRS",
        "EPE",
        "HEP",
        "IMD",
        "NAG",
        "BMA",
        "MAN",
        "FUC",
        "GAL",
        "GLC",
        "SIA",
        "NDG",
    }
)
COFACTOR_RESIDUES = frozenset(
    {
        "HEM",
        "HEC",
        "HEA",
        "HEB",
        "NAD",
        "NAP",
        "NDP",
        "FAD",
        "FMN",
        "SAM",
        "SAH",
        "ATP",
        "ADP",
        "AMP",
        "GTP",
        "GDP",
        "COA",
        "PLP",
        "TPP",
        "THF",
        "FES",
        "SF4",
        "F3S",
    }
)

ResidueKey = tuple[str, str, str]
