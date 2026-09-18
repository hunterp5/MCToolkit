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

"""OpenMM restrained minimization of a loaded protein–ligand complex."""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path

from .pdb_fixer_runtime import _configure_openmm_runtime
from .protein_prepare_amber import _ligand_ff_is_gaff, _ligand_ff_tag, _normalize_ligand_ff
from .protein_prepare_constants import (
    _DEFAULT_CA_K_KCAL,
    _DEFAULT_MIN_ITERS,
    _GB_SALT_M,
    _LIGAND_FF_GAFF2,
    _LIGAND_FF_NONE,
    _OPENMM_PLATFORM_AUTO,
    _PROTEIN_FF_AMBER14,
    _RESTRAINT_BACKBONE_LIGAND,
    _SOLVENT_GBN2,
    ResidueKey,
)
from .protein_prepare_io import (
    _is_cif_fmt,
    _ligand_residue_names,
    _norm_key,
    _prepared_output_path,
    _write_text,
    finalize_prepared_structure,
    log_prepare,
    residue_kind_map,
)
from .protein_prepare_minimize import _ligand_chem_tables, _restrained_minimize_pdb
from .protein_prepare_runtime import _write_prepared_output


@dataclass(frozen=True)
class ProteinMinimizeRequest:
    input_path: str
    output_path: str
    protein_ff: str = _PROTEIN_FF_AMBER14
    ligand_ff: str = _LIGAND_FF_GAFF2
    solvent: str = _SOLVENT_GBN2
    salt_m: float = _GB_SALT_M
    restraint_set: str = _RESTRAINT_BACKBONE_LIGAND
    restraint_k_kcal_per_ang2: float = _DEFAULT_CA_K_KCAL
    max_iterations: int = _DEFAULT_MIN_ITERS
    openmm_platform: str = _OPENMM_PLATFORM_AUTO
    ligand_smiles: str = ""
    ligand_ref_path: str = ""
    ligand_keys: tuple[ResidueKey, ...] = ()
    keep_water: bool = True
    output_format: str = "cif"


def minimize_protein_complex(req: ProteinMinimizeRequest, on_log=None) -> str:
    """Minimize the current complex with OpenMM and write *req.output_path*."""
    from .protein_prepare_io import bind_prepare_log, unbind_prepare_log

    token = bind_prepare_log(on_log)
    try:
        return _minimize_protein_complex(req)
    finally:
        unbind_prepare_log(token)


def mp_minimize_protein_complex(req: ProteinMinimizeRequest) -> tuple[bool, object]:
    """Child-process entry: keep OpenMM/AmberTools out of the GUI process."""
    try:
        return True, minimize_protein_complex(req)
    except Exception as exc:
        return False, str(exc) or "Complex minimization failed."


def _drop_residues(text: str, fmt: str, keys: set[ResidueKey]) -> str:
    if not keys:
        return text
    if _is_cif_fmt(fmt):
        from ..structure_components import delete_cif_residues

        return delete_cif_residues(text, keys)
    from ..structure_components import delete_pdb_residues

    return delete_pdb_residues(text, keys)


def _ca_keys_from_text(text: str, fmt: str) -> set[ResidueKey]:
    from ..structure_components import parse_structure_atoms

    keys: set[ResidueKey] = set()
    for atom in parse_structure_atoms(text or "", fmt):
        if (atom.name or "").strip() == "CA":
            keys.add(_norm_key(atom.chain, atom.resi, atom.icode))
    return keys


def _minimize_protein_complex(req: ProteinMinimizeRequest) -> str:
    from ..structure_components import sniff_structure_format

    _configure_openmm_runtime()
    in_path = Path(req.input_path).expanduser()
    out_path = Path(req.output_path).expanduser()
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
    requested = {_norm_key(*key) for key in req.ligand_keys}
    ligand_keys = requested & all_ligands if requested else set(all_ligands)
    drop: set[ResidueKey] = set()
    if requested:
        drop |= all_ligands - ligand_keys
    if not req.keep_water:
        drop |= waters
    text = _drop_residues(input_text, work_fmt, drop)
    remaining_water = waters - drop if req.keep_water else set()
    ligand_ff = _normalize_ligand_ff(req.ligand_ff)
    if not ligand_keys:
        ligand_ff = _LIGAND_FF_NONE
    use_gaff = _ligand_ff_is_gaff(ligand_ff) and bool(ligand_keys)
    keep_water = bool(remaining_water)
    ligand_mols: list = []
    if use_gaff:
        from .protein_prepare_ligand import mols_from_cif_ligands, prepare_ligands_for_gaff

        ligand_resns = _ligand_residue_names(text, work_fmt, ligand_keys)
        cif_parents = {}
        if work_cif and ligand_resns:
            cif_parents = mols_from_cif_ligands(text, ligand_resns)
        log_prepare(f"Parameterizing ligand(s) for {_ligand_ff_tag(ligand_ff)}…")
        try:
            ligand_mols, text = prepare_ligands_for_gaff(
                text,
                ligand_keys,
                smiles=req.ligand_smiles,
                ref_path=req.ligand_ref_path,
                templates_by_resn=cif_parents or None,
                fmt=work_fmt,
            )
        except ValueError as exc:
            raise RuntimeError(str(exc)) from exc
        if not ligand_mols:
            raise RuntimeError(
                "GAFF/GAFF2 minimization needs ligand chemistry (SMILES, SDF/MOL2, or "
                "mmCIF _chem_comp_bond) so AmberTools can assign atom types."
            )

    work = Path(tempfile.mkdtemp(prefix="molmanager_minimize_"))
    min_in = work / f"min_in{work_ext}"
    minimized = work / f"minimized{work_ext}"
    min_text = text
    if ligand_keys and not use_gaff:
        log_prepare("Holding ligand out of OpenMM (protein-only force field)")
        min_text = _drop_residues(text, work_fmt, ligand_keys)
    _write_text(min_in, min_text)
    original_ca = _ca_keys_from_text(min_text, work_fmt)
    if use_gaff:
        log_prepare(
            f"OpenMM: holo minimization with {_ligand_ff_tag(ligand_ff)} "
            f"({req.protein_ff.upper()}, {req.solvent.upper()})"
        )
    else:
        held = " (ligand held out)" if ligand_keys else ""
        log_prepare(
            f"OpenMM: restrained protein minimization{held} "
            f"({req.protein_ff.upper()}, {req.solvent.upper()}, "
            f"{int(req.max_iterations)} iterations)"
        )
    remarks = ["4 OPENMM COMPLEX MIN"]
    _restrained_minimize_pdb(
        min_in,
        minimized,
        restrained_ca_keys=original_ca,
        k_kcal_per_ang2=float(req.restraint_k_kcal_per_ang2),
        max_iterations=int(req.max_iterations),
        keep_water=keep_water,
        remarks=remarks,
        chem_source=text if work_cif else "",
        protein_ff=req.protein_ff,
        solvent=req.solvent,
        salt_m=float(req.salt_m),
        restraint_set=req.restraint_set,
        ligand_keys=ligand_keys if use_gaff else set(),
        ligand_ff=ligand_ff if use_gaff else _LIGAND_FF_NONE,
        ligand_mols=ligand_mols if use_gaff else None,
        work_dir=work if use_gaff else None,
        openmm_platform=req.openmm_platform,
    )
    protein_min = minimized.read_text(encoding="utf-8")
    if use_gaff:
        final_text = protein_min
    elif ligand_keys:
        final_text = finalize_prepared_structure(
            protein_min,
            text,
            ligand_keys=ligand_keys,
            keep_ligand=True,
            keep_water_keys=remaining_water,
            fmt=work_fmt,
        )
    else:
        final_text = protein_min
    chem_atoms, chem_bonds = _ligand_chem_tables(
        final_text,
        fmt=work_fmt,
        keep_ligand=True,
        ligand_keys=ligand_keys,
        input_text=input_text,
        input_fmt=fmt,
    )
    out_fmt = (req.output_format or "cif").lower()
    out_file = _prepared_output_path(out_path, out_fmt)
    log_prepare(f"Writing minimized {out_fmt.upper()}…")
    _write_prepared_output(
        final_text,
        out_file,
        fmt=work_fmt,
        remarks=remarks,
        chem_atoms=chem_atoms,
        chem_bonds=chem_bonds,
        output_format=out_fmt,
    )
    log_prepare("Minimize finished")
    return str(out_file)
