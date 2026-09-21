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
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with MCToolkit.  If not, see <https://www.gnu.org/licenses/>.

"""PDBFixer preparation logic without PyQt (safe for subprocess import on Windows)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PdbFixerRequest:
    input_pdb_path: str
    output_pdb_path: str
    remove_heterogens: bool = True
    keep_water: bool = False
    replace_nonstandard: bool = True
    add_missing_atoms: bool = True
    add_hydrogens: bool = True
    ph: float = 7.0
    skip_long_gaps: bool = True
    max_missing_gap: int = 8


def _configure_openmm_runtime() -> None:
    """Reduce OpenMM threading/GPU contention before native libraries load."""
    os.environ.setdefault("OPENMM_CPU_THREADS", "1")
    os.environ.setdefault("OPENMM_DEFAULT_PLATFORM", "CPU")


def _drop_internal_missing_residues(fixer) -> None:
    """Keep only terminal gaps; skip speculative internal loop modeling."""
    chains = list(fixer.topology.chains())
    for key in list(fixer.missingResidues.keys()):
        chain = chains[key[0]]
        n_res = len(list(chain.residues()))
        if key[1] != 0 and key[1] != n_res:
            del fixer.missingResidues[key]


def prepare_pdb_for_docking(req: PdbFixerRequest) -> None:
    """
    Clean a receptor PDB with PDBFixer for rigid docking (Gnina / Meeko).

    Raises RuntimeError when PDBFixer/OpenMM is missing or preparation fails.
    """
    _configure_openmm_runtime()
    try:
        import openmm
        from openmm.app import PDBFile
        from pdbfixer import PDBFixer
    except Exception as exc:
        raise RuntimeError(
            "PDBFixer is required to prepare receptor PDB files. Install with: pip install pdbfixer"
        ) from exc

    in_path = Path(req.input_pdb_path).expanduser()
    out_path = Path(req.output_pdb_path).expanduser()
    if not in_path.is_file():
        raise RuntimeError(f"Input PDB not found: {in_path}")

    fixer = PDBFixer(filename=str(in_path))
    try:
        fixer.platform = openmm.Platform.getPlatformByName("CPU")
    except Exception:
        pass

    if req.add_missing_atoms or req.replace_nonstandard:
        fixer.findMissingResidues()
        _drop_internal_missing_residues(fixer)
        if req.skip_long_gaps:
            from .protein_prepare_qc import drop_long_missing_gaps

            drop_long_missing_gaps(fixer, int(req.max_missing_gap))

    if req.replace_nonstandard:
        fixer.findNonstandardResidues()
        fixer.replaceNonstandardResidues()

    if req.remove_heterogens:
        fixer.removeHeterogens(keepWater=bool(req.keep_water))

    if req.add_missing_atoms:
        fixer.findMissingAtoms()
        fixer.addMissingAtoms()

    if req.add_hydrogens:
        fixer.addMissingHydrogens(float(req.ph))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as fh:
        PDBFile.writeFile(fixer.topology, fixer.positions, fh)


def mp_prepare_pdb_for_docking(req: PdbFixerRequest) -> tuple[bool, str]:
    """Child-process entry: run PDBFixer without loading OpenMM in the GUI process."""
    try:
        prepare_pdb_for_docking(req)
        return True, str(Path(req.output_pdb_path).expanduser())
    except Exception as exc:
        return False, str(exc) or "PDB preparation failed."
