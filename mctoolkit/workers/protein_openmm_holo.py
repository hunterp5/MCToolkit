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

"""Shared protein–ligand OpenMM setup for Minimize, MM-GBSA, and implicit MD."""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path

from .pdb_fixer_runtime import _configure_openmm_runtime
from .protein_prepare_amber import _ligand_ff_is_gaff, _normalize_ligand_ff
from .protein_prepare_constants import ResidueKey, _LIGAND_FF_NONE
from .protein_prepare_io import (
    _is_cif_fmt,
    _ligand_residue_names,
    _norm_key,
    _write_text,
    log_prepare,
    residue_kind_map,
)


@dataclass
class HoloOpenMMWork:
    """Scratch files and ligand chemistry for an OpenMM holo job."""

    work_dir: Path
    structure_path: Path
    structure_text: str
    work_fmt: str
    work_ext: str
    ligand_keys: set[ResidueKey]
    ligand_mols: list
    ligand_ff: str
    keep_water: bool
    original_ca: set[ResidueKey]
    input_text: str
    input_fmt: str
    remaining_water: set[ResidueKey]
    use_gaff: bool


def _drop_residues(text: str, fmt: str, keys: set[ResidueKey]) -> str:
    if not keys:
        return text
    if _is_cif_fmt(fmt):
        from ..protein.structure_components import delete_cif_residues

        return delete_cif_residues(text, keys)
    from ..protein.structure_components import delete_pdb_residues

    return delete_pdb_residues(text, keys)


def _ca_keys_from_text(text: str, fmt: str) -> set[ResidueKey]:
    from ..protein.structure_components import parse_structure_atoms

    keys: set[ResidueKey] = set()
    for atom in parse_structure_atoms(text or "", fmt):
        if (atom.name or "").strip() == "CA":
            keys.add(_norm_key(atom.chain, atom.resi, atom.icode))
    return keys


def prepare_holo_work(
    *,
    input_path: str,
    ligand_ff: str,
    ligand_smiles: str = "",
    ligand_ref_path: str = "",
    ligand_keys: tuple[ResidueKey, ...] = (),
    keep_water: bool = True,
    require_gaff: bool = False,
) -> HoloOpenMMWork:
    """Read a PDB/mmCIF complex, optional GAFF ligand prep, write a work-dir snapshot."""
    from ..protein.structure_components import sniff_structure_format

    _configure_openmm_runtime()
    in_path = Path(input_path).expanduser()
    if not in_path.is_file():
        raise RuntimeError(f"Input structure not found: {in_path}")

    log_prepare(f"Reading {in_path.name}…")
    input_text = in_path.read_text(encoding="utf-8", errors="replace")
    fmt = sniff_structure_format(in_path, input_text)
    work_cif = _is_cif_fmt(fmt)
    work_fmt = "cif" if work_cif else "pdb"
    work_ext = ".cif" if work_cif else ".pdb"
    kind_by_key = residue_kind_map(input_text, work_fmt)
    all_ligands = {key for key, kind in kind_by_key.items() if kind == "ligand"}
    waters = {key for key, kind in kind_by_key.items() if kind == "water"}
    requested = {_norm_key(*key) for key in ligand_keys}
    chosen_ligands = requested & all_ligands if requested else set(all_ligands)
    drop: set[ResidueKey] = set()
    if requested:
        drop |= all_ligands - chosen_ligands
    if not keep_water:
        drop |= waters
    text = _drop_residues(input_text, work_fmt, drop)
    remaining_water = waters - drop if keep_water else set()
    ff = _normalize_ligand_ff(ligand_ff)
    if not chosen_ligands:
        ff = _LIGAND_FF_NONE
    use_gaff = _ligand_ff_is_gaff(ff) and bool(chosen_ligands)
    if require_gaff and not use_gaff:
        raise RuntimeError("MM-GBSA and MD need a ligand parameterized with GAFF or GAFF2.")
    ligand_mols: list = []
    if use_gaff:
        from .protein_prepare_ligand import mols_from_cif_ligands, prepare_ligands_for_gaff

        ligand_resns = _ligand_residue_names(text, work_fmt, chosen_ligands)
        cif_parents = {}
        if work_cif and ligand_resns:
            cif_parents = mols_from_cif_ligands(text, ligand_resns)
        log_prepare("Parameterizing ligand(s) for OpenMM…")
        try:
            ligand_mols, text = prepare_ligands_for_gaff(
                text,
                chosen_ligands,
                smiles=ligand_smiles,
                ref_path=ligand_ref_path,
                templates_by_resn=cif_parents or None,
                fmt=work_fmt,
            )
        except ValueError as exc:
            raise RuntimeError(str(exc)) from exc
        if not ligand_mols:
            raise RuntimeError(
                "GAFF/GAFF2 needs ligand chemistry (SMILES, SDF/MOL2, or "
                "mmCIF _chem_comp_bond) so AmberTools can assign atom types."
            )

    work = Path(tempfile.mkdtemp(prefix="mctoolkit_openmm_"))
    structure_path = work / f"holo{work_ext}"
    min_text = text
    if chosen_ligands and not use_gaff:
        log_prepare("Holding ligand out of OpenMM (protein-only force field)")
        min_text = _drop_residues(text, work_fmt, chosen_ligands)
    _write_text(structure_path, min_text)
    return HoloOpenMMWork(
        work_dir=work,
        structure_path=structure_path,
        structure_text=text,
        work_fmt=work_fmt,
        work_ext=work_ext,
        ligand_keys=chosen_ligands,
        ligand_mols=ligand_mols if use_gaff else [],
        ligand_ff=ff if use_gaff else _LIGAND_FF_NONE,
        keep_water=bool(remaining_water),
        original_ca=_ca_keys_from_text(min_text, work_fmt),
        input_text=input_text,
        input_fmt=fmt,
        remaining_water=remaining_water,
        use_gaff=use_gaff,
    )
