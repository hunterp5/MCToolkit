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

"""Protein Viewer Prepare pipeline (PDBFixer repair/clean, pdb2pqr, OpenMM min)."""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path

from .pdb_fixer_runtime import _configure_openmm_runtime, _drop_internal_missing_residues
from .protein_prepare_constants import (
    _DEFAULT_CA_K_KCAL,
    _DEFAULT_MIN_ITERS,
    _GB_SALT_M,
    _LIGAND_FF_GAFF2,
    _PDB2PQR_FF,
    _PROTEIN_FF_AMBER14,
    _RESTRAINT_BACKBONE,
    _SOLVENT_GBN2,
    ResidueKey,
)
from .protein_prepare_io import (
    _ca_residue_keys,
    _is_cif_fmt,
    _ligand_residue_names,
    _norm_key,
    _open_fixer,
    _prepared_output_path,
    _prune_fixer_residues,
    _residue_names_from_topology,
    _unlink_quiet,
    _write_fixer_pdb,
    _write_text,
    finalize_prepared_structure,
    remap_kind_map,
    remap_residue_keys,
    residue_kind_map,
    residue_names_by_key,
)
from .protein_prepare_minimize import (
    _ligand_chem_tables,
    _ligand_ff_tag,
    _normalize_ligand_ff,
    _normalize_protein_ff,
    _normalize_restraint_set,
    _normalize_solvent,
    _restrained_minimize_pdb,
)
from .protein_prepare_pdb2pqr import _run_pdb2pqr
from .protein_prepare_pdb2pqr import pdb2pqr_argv  # noqa: F401

# Re-exports so existing tests can patch this module.
from .protein_prepare_io import (  # noqa: F401,E402
    _is_file_lock_error,
    _open_fixer_from_text,
    _open_openmm_structure,
    _retry_file_op,
    _write_openmm_pdb,
    _write_openmm_structure,
    append_missing_pdb_residues,
    finalize_prepared_pdb,
    residues_to_drop,
)
from .protein_prepare_minimize import (  # noqa: F401,E402
    _assign_ligand_charges,
    _ff_attempts,
    _gaff2_system,
    _gb_kappa_per_nm,
    _pocket_heavy_indices,
    _protein_ff_xmls,
    _protein_only_system,
    _rmsd_angstrom,
    _solvent_label,
)


@dataclass(frozen=True)
class ProteinPrepareRequest:
    input_path: str
    output_pdb_path: str
    ph: float = 7.4
    rebuild_missing_loops: bool = True
    replace_nonstandard: bool = True
    include_ligand: bool = True
    keep_ligand: bool = True
    keep_water_keys: tuple[ResidueKey, ...] = ()
    keep_bridging_waters: bool = False
    remove_other_heterogens: bool = True
    minimize: bool = False
    ligand_smiles: str = ""
    ligand_ref_path: str = ""
    protonate_ligand: bool = True
    pocket_ligand_protonation: bool = True
    restraint_k_kcal_per_ang2: float = _DEFAULT_CA_K_KCAL
    max_minimize_iterations: int = _DEFAULT_MIN_ITERS
    protein_ff: str = _PROTEIN_FF_AMBER14
    ligand_ff: str = _LIGAND_FF_GAFF2
    solvent: str = _SOLVENT_GBN2
    salt_m: float = _GB_SALT_M
    restraint_set: str = _RESTRAINT_BACKBONE
    skip_pocket_loops: bool = True
    output_format: str = "cif"


def _repair_and_clean(
    fixer,
    req: ProteinPrepareRequest,
    *,
    kind_by_key: dict[ResidueKey, str],
    ligand_keys: set[ResidueKey],
    keep_water_keys: set[ResidueKey],
    source_text: str = "",
    source_fmt: str = "pdb",
) -> tuple[set[ResidueKey], int, int]:
    """Rebuild missing protein atoms/loops and prune unwanted solvent/heterogens."""
    fixer.findMissingResidues()
    skipped_pocket_gaps = 0
    if source_text:
        from .protein_prepare_qc import apply_sequence_missing_residues

        apply_sequence_missing_residues(fixer, source_text, source_fmt)
    if not req.rebuild_missing_loops:
        _drop_internal_missing_residues(fixer)
    elif req.skip_pocket_loops and ligand_keys:
        from .protein_prepare_qc import drop_missing_residues_near_ligand

        skipped_pocket_gaps = drop_missing_residues_near_ligand(fixer, ligand_keys)
    n_missing = 0
    missing_map = getattr(fixer, "missingResidues", None)
    if isinstance(missing_map, dict):
        n_missing = sum(len(vals) for vals in missing_map.values())
    if req.replace_nonstandard:
        fixer.findNonstandardResidues()
        fixer.replaceNonstandardResidues()
    _prune_fixer_residues(
        fixer,
        include_ligand=bool(req.include_ligand),
        keep_water_keys=keep_water_keys,
        remove_other_heterogens=bool(req.remove_other_heterogens),
        kind_by_key=kind_by_key,
    )
    original_ca = _ca_residue_keys(fixer.topology)
    fixer.findMissingAtoms()
    fixer.addMissingAtoms()
    return original_ca, skipped_pocket_gaps, n_missing


def _write_prepared_output(
    text: str,
    path: Path,
    *,
    fmt: str,
    remarks: list[str],
    chem_atoms: dict,
    chem_bonds: dict,
    output_format: str = "cif",
) -> None:
    """Write the prepared receptor as mmCIF or PDB."""
    from ..structure_components import (
        _pdb_from_atoms,
        atoms_to_mmcif,
        parse_structure_atoms,
        pdb_to_mmcif,
    )

    path.parent.mkdir(parents=True, exist_ok=True)
    if (output_format or "cif").lower() == "pdb":
        header = "".join(f"REMARK   4 {line}\n" for line in remarks if line)
        if _is_cif_fmt(fmt):
            body = _pdb_from_atoms(parse_structure_atoms(text, "cif"))
        else:
            body = "\n".join(
                line
                for line in (text or "").splitlines()
                if line[:6].strip().upper() in {"ATOM", "HETATM", "TER", "END"}
            )
            if body and not body.endswith("\n"):
                body += "\n"
        _write_text(path, header + body)
        return
    if _is_cif_fmt(fmt):
        _write_text(
            path,
            atoms_to_mmcif(
                parse_structure_atoms(text, "cif"),
                data_name=path.stem,
                remarks=remarks,
                chem_atoms=chem_atoms,
                chem_bonds=chem_bonds,
            ),
        )
        return
    _write_text(
        path,
        pdb_to_mmcif(
            text,
            data_name=path.stem,
            remarks=remarks,
            chem_atoms=chem_atoms,
            chem_bonds=chem_bonds,
        ),
    )


def prepare_protein_structure(req: ProteinPrepareRequest) -> str:
    """
    Repair missing protein atoms/loops, protonate at pH with pdb2pqr/PROPKA
    (optionally holo, with selected waters), then optionally minimize.

    Raises RuntimeError when a required extra is missing or a step fails.
    """
    from ..structure_components import sniff_structure_format
    from .protein_prepare_qc import (
        apply_highest_occupancy_altlocs,
        bridging_water_keys,
        occupancy_warning_remarks,
        pocket_titration_remarks,
    )

    _configure_openmm_runtime()
    in_path = Path(req.input_path).expanduser()
    out_path = Path(req.output_pdb_path).expanduser()
    if not in_path.is_file():
        raise RuntimeError(f"Input structure not found: {in_path}")

    input_text = in_path.read_text(encoding="utf-8", errors="replace")
    fmt = sniff_structure_format(in_path, input_text)
    work_cif = _is_cif_fmt(fmt)
    work_fmt = "cif" if work_cif else "pdb"
    work_ext = ".cif" if work_cif else ".pdb"
    input_text, altloc_notes = apply_highest_occupancy_altlocs(input_text, fmt)
    kind_by_key = residue_kind_map(input_text, fmt)
    ligand_keys = {key for key, kind in kind_by_key.items() if kind == "ligand"}
    orig_names = residue_names_by_key(input_text, fmt)
    orig_ligand_keys = set(ligand_keys)
    keep_water = {_norm_key(*key) for key in req.keep_water_keys}
    if req.keep_bridging_waters and ligand_keys:
        keep_water |= set(bridging_water_keys(input_text, fmt, ligand_keys))
    orig_keep_water = set(keep_water)
    keep_ligand_out = bool(req.include_ligand) and bool(req.keep_ligand)
    run_min = bool(req.minimize)
    ligand_during_min = bool(req.include_ligand) and bool(ligand_keys) and run_min
    keep_ligand_in_merged = bool(req.include_ligand) and (run_min or keep_ligand_out)
    protonate_lig = bool(req.include_ligand) and bool(req.protonate_ligand) and bool(ligand_keys)
    ligand_resns = _ligand_residue_names(input_text, fmt, ligand_keys)
    cif_parents: dict = {}
    if fmt in {"cif", "mmcif"} and ligand_resns:
        from .protein_prepare_ligand import mols_from_cif_ligands

        cif_parents = mols_from_cif_ligands(input_text, ligand_resns)
    if protonate_lig:
        from .protein_prepare_ligand import load_bond_order_template

        try:
            early_template = load_bond_order_template(
                smiles=req.ligand_smiles, ref_path=req.ligand_ref_path
            )
        except ValueError as exc:
            raise RuntimeError(str(exc)) from exc
        if early_template is None:
            early_template = next(iter(cif_parents.values()), None)
        if early_template is None:
            raise RuntimeError(
                "Ligand protonation needs SMILES, an SDF/MOL2, or mmCIF _chem_comp_bond "
                "for the ligand. Uncheck Protonate ligand (Uni-pKa) to guess bond orders "
                "from coordinates."
            )

    work_in = in_path
    tmp_alt: Path | None = None
    if altloc_notes:
        tmp_alt = Path(tempfile.mkdtemp(prefix="molmanager_prepare_alt_")) / f"input{work_ext}"
        _write_text(tmp_alt, input_text)
        work_in = tmp_alt
    fixer = _open_fixer(work_in)
    if tmp_alt is not None:
        _unlink_quiet(tmp_alt)
        try:
            tmp_alt.parent.rmdir()
        except OSError:
            pass
    topo_names = _residue_names_from_topology(fixer.topology)
    kind_by_key = remap_kind_map(kind_by_key, orig_names, topo_names)
    original_ca, skipped_pocket_gaps, n_missing_modeled = _repair_and_clean(
        fixer,
        req,
        kind_by_key=kind_by_key,
        ligand_keys=remap_residue_keys(orig_ligand_keys, orig_names, topo_names),
        keep_water_keys=remap_residue_keys(orig_keep_water, orig_names, topo_names),
        source_text=input_text,
        source_fmt=fmt,
    )
    protein_ff = _normalize_protein_ff(req.protein_ff)
    ligand_ff = _normalize_ligand_ff(req.ligand_ff)
    solvent = _normalize_solvent(req.solvent)
    restraint_set = _normalize_restraint_set(req.restraint_set)
    het_bits = []
    if req.include_ligand:
        het_bits.append("KEEP LIGAND FOR PROPKA")
    else:
        het_bits.append("STRIP LIGAND")
    if keep_water:
        het_bits.append(f"KEEP {len(keep_water)} WATER")
    else:
        het_bits.append("STRIP WATER")
    if req.remove_other_heterogens:
        het_bits.append("STRIP OTHER HETATM")
    if skipped_pocket_gaps:
        het_bits.append(f"SKIP {skipped_pocket_gaps} POCKET LOOP GAP")
    if n_missing_modeled:
        het_bits.append(f"MODEL {n_missing_modeled} SEQRES GAP RESIDUES")
    if run_min and ligand_during_min:
        min_remark = (
            f"4 OPENMM {restraint_set.upper()}-RESTRAINED MIN {protein_ff.upper()} "
            f"{_ligand_ff_tag(ligand_ff)} {solvent.upper()} "
            f"K={float(req.restraint_k_kcal_per_ang2):.1f} KCAL/MOL/A**2"
        )
    elif run_min:
        min_remark = (
            f"4 OPENMM {restraint_set.upper()}-RESTRAINED MIN {protein_ff.upper()} "
            f"{solvent.upper()} K={float(req.restraint_k_kcal_per_ang2):.1f} KCAL/MOL/A**2"
        )
    else:
        min_remark = "4 OPENMM MINIMIZATION SKIPPED"
    remarks = [
        "MOLMANAGER PROTEIN PREPARE",
        "1 PDBFIXER REPAIR MISSING RESIDUES AND SIDE CHAINS",
        "2 PDBFIXER " + "; ".join(het_bits),
        f"3 PDB2PQR {_PDB2PQR_FF} PROPKA PH={float(req.ph):.1f}",
        "3B KEEP LIGAND IN OUTPUT" if keep_ligand_out else "3B STRIP LIGAND FROM OUTPUT",
        min_remark,
    ]
    if altloc_notes:
        remarks.append("6 ALTLOC " + "; ".join(altloc_notes[:8]))
    occ_notes = occupancy_warning_remarks(input_text, fmt, ligand_keys)
    if occ_notes:
        remarks.append("6 OCC<1 " + "; ".join(occ_notes[:8]))

    with tempfile.TemporaryDirectory(
        prefix="molmanager_prepare_",
        ignore_cleanup_errors=True,
    ) as td:
        work = Path(td)
        repaired = work / f"repaired{work_ext}"
        protonated = work / f"protonated{work_ext}"
        pqr = work / "protonated.pqr"
        finalized = work / f"finalized{work_ext}"
        minimized = work / f"minimized{work_ext}"
        ligand_mol2: Path | None = work / "ligand.mol2"
        _write_fixer_pdb(fixer, repaired)
        dest_names = residue_names_by_key(repaired.read_text(encoding="utf-8"), work_fmt)
        ligand_keys = remap_residue_keys(orig_ligand_keys, orig_names, dest_names)
        keep_water = remap_residue_keys(orig_keep_water, orig_names, dest_names)
        if req.include_ligand and orig_ligand_keys and not ligand_keys:
            raise RuntimeError(
                "The ligand residue was not found after PDBFixer repair. "
                "mmCIF files often store ligands on a different chain ID than the "
                "PDB auth chain; if this persists, provide ligand SMILES or an SDF/MOL2."
            )
        parent_mol = None
        protomer_template = None
        protomer_choice = None
        ensemble = None
        if protonate_lig or (
            req.include_ligand
            and ligand_keys
            and (req.ligand_smiles or req.ligand_ref_path or cif_parents)
        ):
            from .protein_prepare_ligand import (
                choose_ligand_protomer,
                ligand_ionization_ensemble,
                ligand_residue_blocks,
                load_bond_order_template,
                prepare_ligands_for_gaff,
                write_ligand_mol2,
            )

            try:
                parent_mol = load_bond_order_template(
                    smiles=req.ligand_smiles, ref_path=req.ligand_ref_path
                )
            except ValueError as exc:
                raise RuntimeError(str(exc)) from exc
            used_cif_bonds = False
            if parent_mol is None and cif_parents:
                parent_mol = next(iter(cif_parents.values()), None)
                used_cif_bonds = parent_mol is not None
            if protonate_lig and parent_mol is None:
                raise RuntimeError(
                    "Ligand protonation needs SMILES, an SDF/MOL2, or mmCIF _chem_comp_bond "
                    "for the ligand. Uncheck Protonate ligand (Uni-pKa) to guess bond orders "
                    "from coordinates."
                )
            if used_cif_bonds:
                remarks.insert(-1, "3C CIF LIGAND BONDS " + ",".join(sorted(cif_parents)))
            if protonate_lig and parent_mol is not None:
                try:
                    ensemble = ligand_ionization_ensemble(parent_mol)
                    protomer_choice = choose_ligand_protomer(
                        parent_mol, ph=float(req.ph), ensemble=ensemble
                    )
                except ValueError as exc:
                    raise RuntimeError(str(exc)) from exc
                protomer_template = protomer_choice.mol
                remarks.insert(-1, protomer_choice.remark_line())
                try:
                    _mols, repaired_text = prepare_ligands_for_gaff(
                        repaired.read_text(encoding="utf-8"),
                        ligand_keys,
                        template=protomer_template,
                        fmt=work_fmt,
                    )
                except ValueError as exc:
                    raise RuntimeError(str(exc)) from exc
                _write_text(repaired, repaired_text)
                residues = ligand_residue_blocks(repaired_text, ligand_keys, fmt=work_fmt)
                if _mols and residues:
                    key, resn, _block = residues[0]
                    try:
                        write_ligand_mol2(_mols[0], ligand_mol2, resn=resn, resi=key[1])
                    except Exception:
                        ligand_mol2 = None
                else:
                    ligand_mol2 = None
            else:
                protomer_template = parent_mol
                ligand_mol2 = None
        else:
            ligand_mol2 = None

        def _pqr_once(mol2: Path | None) -> None:
            try:
                _run_pdb2pqr(
                    repaired,
                    pqr,
                    protonated,
                    ph=float(req.ph),
                    drop_water=not bool(keep_water),
                    ligand_mol2=mol2 if mol2 is not None and mol2.is_file() else None,
                )
            except RuntimeError:
                if mol2 is None:
                    raise
                _run_pdb2pqr(
                    repaired,
                    pqr,
                    protonated,
                    ph=float(req.ph),
                    drop_water=not bool(keep_water),
                    ligand_mol2=None,
                )

        _pqr_once(ligand_mol2)

        if (
            protonate_lig
            and parent_mol is not None
            and ensemble is not None
            and bool(req.pocket_ligand_protonation)
        ):
            from .protein_prepare_ligand import (
                choose_ligand_protomer,
                ligand_residue_blocks,
                prepare_ligands_for_gaff,
                write_ligand_mol2,
            )

            def _replace_protomer_remark(choice) -> None:
                remarks[:] = [
                    line if not str(line).startswith("3C UNIPKA") else choice.remark_line()
                    for line in remarks
                ]

            repaired_text = repaired.read_text(encoding="utf-8")
            residues = ligand_residue_blocks(repaired_text, ligand_keys, fmt=work_fmt)
            pdb_block = residues[0][2] if residues else ""
            try:
                pocket_choice = choose_ligand_protomer(
                    parent_mol,
                    ph=float(req.ph),
                    pdb_block=pdb_block,
                    pqr_text=pqr.read_text(encoding="utf-8", errors="replace")
                    if pqr.is_file()
                    else "",
                    ligand_keys=ligand_keys,
                    ensemble=ensemble,
                )
            except ValueError as exc:
                raise RuntimeError(str(exc)) from exc
            if pocket_choice.used_pocket:
                _replace_protomer_remark(pocket_choice)
            if pocket_choice.used_pocket and pocket_choice.smiles != (
                protomer_choice.smiles if protomer_choice is not None else ""
            ):
                protomer_choice = pocket_choice
                protomer_template = pocket_choice.mol
                try:
                    _mols, repaired_text = prepare_ligands_for_gaff(
                        repaired_text,
                        ligand_keys,
                        template=protomer_template,
                        fmt=work_fmt,
                    )
                except ValueError as exc:
                    raise RuntimeError(str(exc)) from exc
                _write_text(repaired, repaired_text)
                residues = ligand_residue_blocks(repaired_text, ligand_keys, fmt=work_fmt)
                mol2_retry: Path | None = work / "ligand_pocket.mol2"
                if _mols and residues:
                    key, resn, _block = residues[0]
                    try:
                        write_ligand_mol2(_mols[0], mol2_retry, resn=resn, resi=key[1])
                    except Exception:
                        mol2_retry = None
                else:
                    mol2_retry = None
                _pqr_once(mol2_retry)
            elif pocket_choice.used_pocket:
                protomer_choice = pocket_choice

        repaired_text = repaired.read_text(encoding="utf-8")
        protonated_text = protonated.read_text(encoding="utf-8")
        titr = pocket_titration_remarks(
            protonated_text, work_fmt, repaired_text, work_fmt, ligand_keys
        )
        if titr:
            remarks.append("6 POCKET " + "; ".join(titr))
        merged = finalize_prepared_structure(
            protonated_text,
            repaired_text,
            ligand_keys=ligand_keys,
            keep_ligand=keep_ligand_in_merged,
            keep_water_keys=keep_water,
            fmt=work_fmt,
        )
        ligand_mols: list | None = None
        if keep_ligand_in_merged and ligand_keys:
            from .protein_prepare_ligand import prepare_ligands_for_gaff

            try:
                ligand_mols, merged = prepare_ligands_for_gaff(
                    merged,
                    ligand_keys,
                    smiles=req.ligand_smiles,
                    ref_path=req.ligand_ref_path,
                    template=protomer_template,
                    templates_by_resn=cif_parents or None,
                    fmt=work_fmt,
                )
            except ValueError as exc:
                raise RuntimeError(str(exc)) from exc
            if ligand_during_min and not ligand_mols:
                raise RuntimeError(
                    "Include ligand in minimization could not build a ligand molecule "
                    "from the repaired structure. Provide SMILES or an SDF/MOL2 if "
                    "bond orders could not be assigned from mmCIF _chem_comp_bond."
                )
        _write_text(finalized, merged)
        if run_min:
            _restrained_minimize_pdb(
                finalized,
                minimized,
                restrained_ca_keys=original_ca,
                k_kcal_per_ang2=float(req.restraint_k_kcal_per_ang2),
                max_iterations=int(req.max_minimize_iterations),
                keep_water=bool(keep_water),
                remarks=remarks,
                ligand_mols=ligand_mols,
                chem_source=merged if work_cif else "",
                protein_ff=protein_ff,
                ligand_ff=ligand_ff,
                solvent=solvent,
                salt_m=float(req.salt_m),
                restraint_set=restraint_set,
                ligand_keys=ligand_keys if ligand_during_min else set(),
            )
            final_text = minimized.read_text(encoding="utf-8")
            dest_names = residue_names_by_key(final_text, work_fmt)
            ligand_keys = remap_residue_keys(orig_ligand_keys, orig_names, dest_names)
            if ligand_keys and not keep_ligand_out:
                if work_cif:
                    from ..structure_components import delete_cif_residues

                    final_text = delete_cif_residues(final_text, ligand_keys)
                else:
                    from ..structure_components import delete_pdb_residues

                    final_text = delete_pdb_residues(final_text, ligand_keys)
        else:
            final_text = merged
        chem_atoms, chem_bonds = _ligand_chem_tables(
            final_text,
            fmt=work_fmt,
            keep_ligand=keep_ligand_out,
            ligand_keys=ligand_keys,
            input_text=input_text,
            input_fmt=fmt,
        )
        out_fmt = (req.output_format or "cif").lower()
        out_file = _prepared_output_path(out_path, out_fmt)
        _write_prepared_output(
            final_text,
            out_file,
            fmt=work_fmt,
            remarks=remarks,
            chem_atoms=chem_atoms,
            chem_bonds=chem_bonds,
            output_format=out_fmt,
        )
    return str(out_file)


def mp_prepare_protein_structure(req: ProteinPrepareRequest) -> tuple[bool, str]:
    """Child-process entry: keep OpenMM/pdb2pqr out of the GUI process."""
    try:
        return True, prepare_protein_structure(req)
    except Exception as exc:
        return False, str(exc) or "Structure preparation failed."
