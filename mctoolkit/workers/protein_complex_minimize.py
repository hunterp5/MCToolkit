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

"""OpenMM restrained minimization of a loaded protein–ligand complex."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .protein_openmm_holo import prepare_holo_work
from .protein_prepare_amber import _ligand_ff_tag
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
    _prepared_output_path,
    finalize_prepared_structure,
    log_prepare,
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


def _minimize_protein_complex(req: ProteinMinimizeRequest) -> str:
    work = prepare_holo_work(
        input_path=req.input_path,
        ligand_ff=req.ligand_ff,
        ligand_smiles=req.ligand_smiles,
        ligand_ref_path=req.ligand_ref_path,
        ligand_keys=req.ligand_keys,
        keep_water=req.keep_water,
        require_gaff=False,
    )
    out_path = Path(req.output_path).expanduser()
    minimized = work.work_dir / f"minimized{work.work_ext}"
    ligand_ff = work.ligand_ff
    ligand_keys = work.ligand_keys
    use_gaff = work.use_gaff
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
        work.structure_path,
        minimized,
        restrained_ca_keys=work.original_ca,
        k_kcal_per_ang2=float(req.restraint_k_kcal_per_ang2),
        max_iterations=int(req.max_iterations),
        keep_water=work.keep_water,
        remarks=remarks,
        chem_source=work.structure_text if _is_cif_fmt(work.work_fmt) else "",
        protein_ff=req.protein_ff,
        solvent=req.solvent,
        salt_m=float(req.salt_m),
        restraint_set=req.restraint_set,
        ligand_keys=ligand_keys if use_gaff else set(),
        ligand_ff=ligand_ff if use_gaff else _LIGAND_FF_NONE,
        ligand_mols=work.ligand_mols if use_gaff else None,
        work_dir=work.work_dir if use_gaff else None,
        openmm_platform=req.openmm_platform,
    )
    protein_min = minimized.read_text(encoding="utf-8")
    if use_gaff:
        final_text = protein_min
    elif ligand_keys:
        final_text = finalize_prepared_structure(
            protein_min,
            work.structure_text,
            ligand_keys=ligand_keys,
            keep_ligand=True,
            keep_water_keys=work.remaining_water,
            fmt=work.work_fmt,
        )
    else:
        final_text = protein_min
    chem_atoms, chem_bonds = _ligand_chem_tables(
        final_text,
        fmt=work.work_fmt,
        keep_ligand=True,
        ligand_keys=ligand_keys,
        input_text=work.input_text,
        input_fmt=work.input_fmt,
    )
    out_fmt = (req.output_format or "cif").lower()
    out_file = _prepared_output_path(out_path, out_fmt)
    log_prepare(f"Writing minimized {out_fmt.upper()}…")
    _write_prepared_output(
        final_text,
        out_file,
        fmt=work.work_fmt,
        remarks=remarks,
        chem_atoms=chem_atoms,
        chem_bonds=chem_bonds,
        output_format=out_fmt,
    )
    log_prepare("Minimize finished")
    return str(out_file)
