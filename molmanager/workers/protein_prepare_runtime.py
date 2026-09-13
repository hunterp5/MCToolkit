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

import errno
import gc
import math
import os
import tempfile
import time
from dataclasses import dataclass
from io import StringIO
from pathlib import Path

from .pdb_fixer_runtime import _configure_openmm_runtime, _drop_internal_missing_residues

# 10 kcal mol⁻¹ Å⁻² is a typical heavy-atom restraint for clash relief.
_DEFAULT_CA_K_KCAL = 10.0
_DEFAULT_MIN_ITERS = 400
_PDB2PQR_FF = "AMBER"
# Physiological salt for GB screening (Onufriev/Simmerling GB; OpenMM kappa conversion).
_GB_SALT_M = 0.15
_GB_TEMPERATURE_K = 298.15
_GB_SOLVENT_DIELECTRIC = 78.5
_PROTEIN_FF_AMBER14 = "amber14"
_PROTEIN_FF_AMBER99 = "amber99sbildn"
_LIGAND_FF_GAFF2 = "gaff2"
_LIGAND_FF_OPENFF = "openff-2.2.0"
_SOLVENT_GBN2 = "gbn2"
_SOLVENT_OBC2 = "obc2"
_SOLVENT_VACUUM = "vacuum"
_RESTRAINT_CA = "ca"
_RESTRAINT_BACKBONE = "backbone"
_RESTRAINT_BACKBONE_LIGAND = "backbone_ligand"

ResidueKey = tuple[str, str, str]


@dataclass(frozen=True)
class ProteinPrepareRequest:
    input_path: str
    output_pdb_path: str
    ph: float = 7.4
    rebuild_missing_loops: bool = True
    replace_nonstandard: bool = True
    include_ligand: bool = True
    keep_ligand: bool = False
    keep_water_keys: tuple[ResidueKey, ...] = ()
    keep_bridging_waters: bool = False
    remove_other_heterogens: bool = True
    minimize: bool = True
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


def _norm_key(chain: str, resi: str, icode: str) -> ResidueKey:
    from ..structure_components import _norm_chain

    return (_norm_chain(chain), str(resi or "").strip() or "0", str(icode or "").strip())


def _residue_key(residue) -> ResidueKey:
    chain = residue.chain.id if getattr(residue, "chain", None) is not None else ""
    resid = str(getattr(residue, "id", "") or "").strip()
    icode = str(getattr(residue, "insertionCode", "") or "").strip()
    return _norm_key(chain, resid, icode)


def _ca_residue_keys(topology) -> set[ResidueKey]:
    keys: set[ResidueKey] = set()
    for atom in topology.atoms():
        if atom.name == "CA":
            keys.add(_residue_key(atom.residue))
    return keys


def _is_file_lock_error(exc: BaseException) -> bool:
    if not isinstance(exc, OSError):
        return False
    if getattr(exc, "winerror", None) == 32:
        return True
    return exc.errno in {errno.EACCES, errno.EPERM, errno.EBUSY}


def _retry_file_op(fn, *, attempts: int = 8, delay_s: float = 0.05):
    """Retry *fn* when Windows still holds a temp-file lock."""
    last: OSError | None = None
    for i in range(max(1, attempts)):
        try:
            return fn()
        except OSError as exc:
            last = exc
            if not _is_file_lock_error(exc) or i + 1 >= attempts:
                raise
            gc.collect()
            time.sleep(delay_s * (2**i))
    assert last is not None
    raise last


def _write_text(path: Path, text: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")

    def _do() -> None:
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)

    try:
        _retry_file_op(_do)
    finally:
        _unlink_quiet(tmp)


def _unlink_quiet(path: Path | None) -> None:
    if path is None:
        return
    rec = Path(path)
    try:
        _retry_file_op(lambda: rec.unlink(missing_ok=True), attempts=4, delay_s=0.05)
    except OSError:
        pass


def _open_fixer(path: Path):
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    fmt = "cif" if _is_cif_path(path) else "pdb"
    return _open_fixer_from_text(text, fmt)


def _open_fixer_from_text(text: str, fmt: str):
    try:
        import openmm
        from pdbfixer import PDBFixer
    except Exception as exc:
        raise RuntimeError(
            "PDBFixer and OpenMM are required to prepare structures. "
            'Install with: pip install -e ".[docking]"'
        ) from exc

    buf = StringIO(text or "")
    if _is_cif_fmt(fmt):
        fixer = PDBFixer(pdbxfile=buf)
    else:
        fixer = PDBFixer(pdbfile=buf)
    try:
        fixer.platform = openmm.Platform.getPlatformByName("CPU")
    except Exception:
        pass
    return fixer


def _write_fixer_pdb(fixer, path: Path) -> None:
    _write_openmm_structure(fixer.topology, fixer.positions, path)


def _prepared_output_path(path: Path, output_format: str) -> Path:
    fmt = (output_format or "cif").lower()
    if fmt == "pdb":
        if path.suffix.lower() == ".pdb":
            return path
        return path.with_suffix(".pdb")
    if path.suffix.lower() in {".cif", ".mmcif", ".mcif"}:
        return path
    return path.with_suffix(".cif")


def _is_cif_fmt(fmt: str) -> bool:
    return (fmt or "").lower() in {"cif", "mmcif"}


def _is_cif_path(path: Path) -> bool:
    return path.suffix.lower() in {".cif", ".mmcif", ".mcif"}


def _open_openmm_structure(path: Path):
    from openmm.app import PDBFile, PDBxFile

    text = Path(path).read_text(encoding="utf-8", errors="replace")
    buf = StringIO(text)
    if _is_cif_path(path):
        return PDBxFile(buf)
    return PDBFile(buf)


def _write_openmm_structure(
    topology,
    positions,
    path: Path,
    remarks: list[str] | None = None,
    *,
    chem_source: str = "",
) -> None:
    if not _is_cif_path(path):
        _write_openmm_pdb(topology, positions, path, remarks=remarks)
        return
    from openmm.app import PDBxFile

    buf = StringIO()
    PDBxFile.writeFile(topology, positions, buf, keepIds=True, entry=path.stem)
    header = "".join(f"# {line}\n" for line in (remarks or []) if line)
    text = header + buf.getvalue()
    if chem_source:
        from ..structure_components import (
            attach_cif_chem_comp,
            parse_cif_chem_comp_atoms,
            parse_cif_chem_comp_bonds,
        )

        text = attach_cif_chem_comp(
            text,
            parse_cif_chem_comp_atoms(chem_source),
            parse_cif_chem_comp_bonds(chem_source),
        )
    _write_text(path, text)


def _write_openmm_pdb(topology, positions, path: Path, remarks: list[str] | None = None) -> None:
    from io import StringIO

    from openmm.app import PDBFile

    buf = StringIO()
    PDBFile.writeFile(topology, positions, buf, keepIds=True)
    body = buf.getvalue()
    header = "".join(f"REMARK   4 {line}\n" for line in (remarks or []) if line)
    _write_text(path, header + body)


def residue_kind_map(text: str, fmt: str) -> dict[ResidueKey, str]:
    """Map ``(chain, resi, icode)`` to Manager kind for residues in *text*."""
    from ..structure_components import parse_polymer_sequences

    out: dict[ResidueKey, str] = {}
    for poly in parse_polymer_sequences(text or "", fmt):
        for res in poly.residues:
            if res.kind == "missing":
                continue
            out[_norm_key(res.chain, res.resi, res.icode)] = res.kind
    return out


def _ligand_residue_names(text: str, fmt: str, ligand_keys: set[ResidueKey]) -> set[str]:
    """Residue names for ligand keys in *text*."""
    from ..structure_components import parse_polymer_sequences

    wanted = {_norm_key(*key) for key in ligand_keys}
    names: set[str] = set()
    for poly in parse_polymer_sequences(text or "", fmt):
        for res in poly.residues:
            if _norm_key(res.chain, res.resi, res.icode) in wanted and res.resn:
                if res.kind == "missing":
                    continue
                names.add(res.resn.upper())
    return names


def residue_names_by_key(text: str, fmt: str) -> dict[ResidueKey, str]:
    """Map ``(chain, resi, icode)`` to residue name in *text*."""
    from ..structure_components import parse_polymer_sequences

    out: dict[ResidueKey, str] = {}
    for poly in parse_polymer_sequences(text or "", fmt):
        for res in poly.residues:
            name = (res.resn or "").strip().upper()
            if name and res.kind != "missing":
                out[_norm_key(res.chain, res.resi, res.icode)] = name
    return out


def _residue_names_from_topology(topology) -> dict[ResidueKey, str]:
    out: dict[ResidueKey, str] = {}
    for residue in topology.residues():
        name = (getattr(residue, "name", "") or "").strip().upper()
        if name:
            out[_residue_key(residue)] = name
    return out


def remap_residue_keys(
    keys: set[ResidueKey],
    source_names: dict[ResidueKey, str],
    dest_names: dict[ResidueKey, str],
) -> set[ResidueKey]:
    """Map residue keys across mmCIF auth vs label chain IDs.

    PDB-style auth IDs (chain A, AXI 2000) often become a separate mmCIF
    ``label_asym_id`` after PDBFixer/OpenMM rewrite (chain B, AXI 2000).
    Match exact keys first, then ``(resn, resi, icode)`` ignoring chain.
    """
    wanted = {_norm_key(*key) for key in keys}
    if not dest_names:
        return wanted
    dest_keys = set(dest_names)
    by_comp: dict[tuple[str, str, str], list[ResidueKey]] = {}
    by_resn: dict[str, list[ResidueKey]] = {}
    for key, resn in dest_names.items():
        name = (resn or "").strip().upper()
        if not name:
            continue
        ident = (name, key[1], key[2])
        by_comp.setdefault(ident, []).append(key)
        by_resn.setdefault(name, []).append(key)

    out: set[ResidueKey] = set()
    for key in wanted:
        if key in dest_keys:
            out.add(key)
            continue
        resn = (source_names.get(key) or "").strip().upper()
        if not resn:
            continue
        cands = by_comp.get((resn, key[1], key[2]), [])
        if len(cands) == 1:
            out.add(cands[0])
            continue
        if len(cands) > 1:
            same_chain = [cand for cand in cands if cand[0] == key[0]]
            out.add(same_chain[0] if len(same_chain) == 1 else sorted(cands)[0])
            continue
        resn_hits = by_resn.get(resn, [])
        if len(resn_hits) == 1:
            out.add(resn_hits[0])
    return out


def remap_kind_map(
    kind_by_key: dict[ResidueKey, str],
    source_names: dict[ResidueKey, str],
    dest_names: dict[ResidueKey, str],
) -> dict[ResidueKey, str]:
    """Copy residue kinds onto destination keys (auth → OpenMM label chains)."""
    out: dict[ResidueKey, str] = {}
    for old_key, kind in kind_by_key.items():
        for new_key in remap_residue_keys({old_key}, source_names, dest_names):
            out[new_key] = kind
    return out


def residues_to_drop(
    kind_by_key: dict[ResidueKey, str],
    *,
    include_ligand: bool,
    keep_water_keys: set[ResidueKey],
    remove_other_heterogens: bool,
) -> set[ResidueKey]:
    """Residue keys to delete before pdb2pqr (unwanted waters and heteros)."""
    keep_water = {_norm_key(*key) for key in keep_water_keys}
    drop: set[ResidueKey] = set()
    for key, kind in kind_by_key.items():
        if kind == "water" and key not in keep_water:
            drop.add(key)
        elif kind == "ligand" and not include_ligand:
            drop.add(key)
        elif kind in {"metal", "other"} and remove_other_heterogens:
            drop.add(key)
    return drop


def _topology_residue_kind(residue) -> str:
    from ..structure_components import AMINO_ACIDS, METAL_RESIDUES, NUCLEIC_ACIDS, WATER_RESIDUES

    name = (getattr(residue, "name", "") or "").strip().upper()
    if name in WATER_RESIDUES:
        return "water"
    if name in AMINO_ACIDS or name in NUCLEIC_ACIDS:
        return "polymer"
    if name in METAL_RESIDUES:
        return "metal"
    return "ligand"


def _prune_fixer_residues(
    fixer,
    *,
    include_ligand: bool,
    keep_water_keys: set[ResidueKey],
    remove_other_heterogens: bool,
    kind_by_key: dict[ResidueKey, str],
) -> None:
    from openmm.app import Modeller

    keep_water = {_norm_key(*key) for key in keep_water_keys}
    modeller = Modeller(fixer.topology, fixer.positions)
    to_delete = []
    for residue in modeller.topology.residues():
        key = _residue_key(residue)
        kind = kind_by_key.get(key) or _topology_residue_kind(residue)
        if kind == "water" and key not in keep_water:
            to_delete.append(residue)
        elif kind == "ligand" and not include_ligand:
            to_delete.append(residue)
        elif kind in {"metal", "other"} and remove_other_heterogens:
            to_delete.append(residue)
    if to_delete:
        modeller.delete(to_delete)
        fixer.topology = modeller.topology
        fixer.positions = modeller.positions


def append_missing_pdb_residues(dest: str, source: str, keys: set[ResidueKey]) -> str:
    """Copy ATOM/HETATM records from *source* when *dest* is missing those residues."""
    from ..structure_components import _pdb_residue_key

    if not keys:
        return dest
    wanted = {_norm_key(*key) for key in keys}
    present: set[ResidueKey] = set()
    for line in (dest or "").splitlines():
        raw = _pdb_residue_key(line)
        if raw:
            present.add(_norm_key(*raw))
    extra: list[str] = []
    for line in (source or "").splitlines():
        raw = _pdb_residue_key(line)
        if raw is None:
            continue
        key = _norm_key(*raw)
        if key in wanted and key not in present:
            extra.append(line.rstrip())
    if not extra:
        return dest or ""
    lines = [line.rstrip() for line in (dest or "").splitlines()]
    end_i = next((i for i, line in enumerate(lines) if line.startswith("END")), len(lines))
    merged = lines[:end_i] + extra + lines[end_i:]
    return "\n".join(merged) + "\n"


def finalize_prepared_structure(
    protonated_text: str,
    repaired_text: str,
    *,
    ligand_keys: set[ResidueKey],
    keep_ligand: bool,
    keep_water_keys: set[ResidueKey],
    fmt: str = "pdb",
) -> str:
    """Strip or restore ligand/water records after pdb2pqr."""
    if _is_cif_fmt(fmt):
        from ..structure_components import append_missing_cif_residues, delete_cif_residues

        text = protonated_text or ""
        ligands = {_norm_key(*key) for key in ligand_keys}
        waters = {_norm_key(*key) for key in keep_water_keys}
        if not keep_ligand and ligands:
            text = delete_cif_residues(text, ligands)
        restore: set[ResidueKey] = set(waters)
        if keep_ligand:
            restore |= ligands
        return append_missing_cif_residues(text, repaired_text, restore)
    return finalize_prepared_pdb(
        protonated_text,
        repaired_text,
        ligand_keys=ligand_keys,
        keep_ligand=keep_ligand,
        keep_water_keys=keep_water_keys,
    )


def finalize_prepared_pdb(
    protonated_text: str,
    repaired_text: str,
    *,
    ligand_keys: set[ResidueKey],
    keep_ligand: bool,
    keep_water_keys: set[ResidueKey],
) -> str:
    """Strip or restore ligand/water records after pdb2pqr."""
    from ..structure_components import delete_pdb_residues

    text = protonated_text or ""
    ligands = {_norm_key(*key) for key in ligand_keys}
    waters = {_norm_key(*key) for key in keep_water_keys}
    if not keep_ligand and ligands:
        text = delete_pdb_residues(text, ligands)
    restore: set[ResidueKey] = set(waters)
    if keep_ligand:
        restore |= ligands
    return append_missing_pdb_residues(text, repaired_text, restore)


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


def pdb2pqr_argv(
    input_pdb: Path,
    output_pqr: Path,
    output_pdb: Path,
    *,
    ph: float,
    drop_water: bool = True,
    ligand_mol2: Path | None = None,
) -> list[str]:
    """CLI argv for pdb2pqr (AMBER names + PROPKA titration at *ph*)."""
    argv = [
        f"--ff={_PDB2PQR_FF}",
        f"--ffout={_PDB2PQR_FF}",
        "--keep-chain",
    ]
    if drop_water:
        argv.append("--drop-water")
    if ligand_mol2 is not None:
        argv.extend(["--ligand", str(ligand_mol2)])
    argv.extend(
        [
            "--titration-state-method=propka",
            f"--with-ph={float(ph):.1f}",
            "--pdb-output",
            str(output_pdb),
            "--log-level=ERROR",
            str(input_pdb),
            str(output_pqr),
        ]
    )
    return argv


def _run_pdb2pqr(
    input_pdb: Path,
    output_pqr: Path,
    output_pdb: Path,
    *,
    ph: float,
    drop_water: bool = True,
    ligand_mol2: Path | None = None,
) -> None:
    try:
        from pdb2pqr.main import run_pdb2pqr
    except Exception as exc:
        raise RuntimeError(
            "pdb2pqr is required for pH-based protonation. Install with: pip install pdb2pqr"
        ) from exc

    write_cif = _is_cif_path(output_pdb)
    write_cif_in = _is_cif_path(input_pdb)
    pdb_in = input_pdb
    pdb_out = output_pdb
    scratch_in: Path | None = None
    if write_cif:
        pdb_out = output_pdb.with_name(output_pdb.stem + ".pdb2pqr.pdb")
    if write_cif_in:
        from ..structure_components import _pdb_from_atoms, parse_structure_atoms

        scratch_in = input_pdb.with_name(input_pdb.stem + ".pdb2pqr_in.pdb")
        _write_text(
            scratch_in,
            _pdb_from_atoms(
                parse_structure_atoms(
                    input_pdb.read_text(encoding="utf-8", errors="replace"), "cif"
                )
            ),
        )
        pdb_in = scratch_in
    argv = pdb2pqr_argv(
        pdb_in,
        output_pqr,
        pdb_out,
        ph=ph,
        drop_water=drop_water,
        ligand_mol2=ligand_mol2,
    )
    try:
        run_pdb2pqr(argv)
    except SystemExit as exc:
        raise RuntimeError(f"pdb2pqr failed: {exc}") from exc
    except Exception as exc:
        raise RuntimeError(f"pdb2pqr failed: {exc}") from exc
    finally:
        _unlink_quiet(scratch_in)
    if not pdb_out.is_file() or pdb_out.stat().st_size < 32:
        raise RuntimeError("pdb2pqr did not write a protonated structure file.")
    if write_cif:
        from ..structure_components import (
            parse_cif_chem_comp_atoms,
            parse_cif_chem_comp_bonds,
            pdb_to_mmcif,
        )

        src = ""
        if write_cif_in and input_pdb.is_file():
            src = input_pdb.read_text(encoding="utf-8", errors="replace")
        output_pdb.parent.mkdir(parents=True, exist_ok=True)
        _write_text(
            output_pdb,
            pdb_to_mmcif(
                pdb_out.read_text(encoding="utf-8", errors="replace"),
                data_name=output_pdb.stem,
                chem_atoms=parse_cif_chem_comp_atoms(src) if src else None,
                chem_bonds=parse_cif_chem_comp_bonds(src) if src else None,
            ),
        )
        _unlink_quiet(pdb_out)


def _gb_kappa_per_nm(
    *,
    salt_m: float = _GB_SALT_M,
    temperature_k: float = _GB_TEMPERATURE_K,
    solvent_dielectric: float = _GB_SOLVENT_DIELECTRIC,
) -> float:
    """Debye κ (nm⁻¹) from 1:1 salt molarity. OpenMM's 50.33355 conversion at *temperature_k*."""
    if salt_m <= 0:
        return 0.0
    return 50.33355 * math.sqrt(float(salt_m) / float(solvent_dielectric) / float(temperature_k))


def _normalize_protein_ff(name: str) -> str:
    raw = (name or _PROTEIN_FF_AMBER14).strip().lower()
    if raw in {_PROTEIN_FF_AMBER99, "amber99", "ff99sbildn"}:
        return _PROTEIN_FF_AMBER99
    return _PROTEIN_FF_AMBER14


def _normalize_ligand_ff(name: str) -> str:
    raw = (name or _LIGAND_FF_GAFF2).strip().lower()
    if raw in {_LIGAND_FF_OPENFF, "sage", "openff", "openff-2.1.0", "openff-2.0.0"}:
        return _LIGAND_FF_OPENFF
    return _LIGAND_FF_GAFF2


def _normalize_solvent(name: str) -> str:
    raw = (name or _SOLVENT_GBN2).strip().lower()
    if raw in {_SOLVENT_VACUUM, "none", "vac"}:
        return _SOLVENT_VACUUM
    if raw in {_SOLVENT_OBC2, "obc", "gbsa-obc"}:
        return _SOLVENT_OBC2
    return _SOLVENT_GBN2


def _normalize_restraint_set(name: str) -> str:
    raw = (name or _RESTRAINT_BACKBONE).strip().lower()
    if raw in {_RESTRAINT_CA, "c-alpha", "calpha"}:
        return _RESTRAINT_CA
    if raw in {_RESTRAINT_BACKBONE_LIGAND, "backbone+ligand", "all_heavy"}:
        return _RESTRAINT_BACKBONE_LIGAND
    return _RESTRAINT_BACKBONE


def _protein_ff_xmls(
    *,
    keep_water: bool,
    solvent: str = _SOLVENT_GBN2,
    protein_ff: str = _PROTEIN_FF_AMBER14,
    gbsa: bool | None = None,
) -> tuple[tuple[str, ...], ...]:
    """Force-field XML combinations, preferred first."""
    ff = _normalize_protein_ff(protein_ff)
    if gbsa is False:
        sol = _SOLVENT_VACUUM
    elif gbsa is True and not solvent:
        sol = _SOLVENT_GBN2
    else:
        sol = _normalize_solvent(solvent)
    if ff == _PROTEIN_FF_AMBER99:
        protein_xml = "amber99sbildn.xml"
        water_xml = "tip3p.xml"
        gb_fallback = "implicit/obc2.xml"
    else:
        protein_xml = "amber14-all.xml"
        water_xml = "amber14/tip3pfb.xml"
        gb_fallback = "implicit/gbn2.xml"
    gb_xml = None
    if sol == _SOLVENT_GBN2:
        gb_xml = "implicit/gbn2.xml"
    elif sol == _SOLVENT_OBC2:
        gb_xml = "implicit/obc2.xml"
    primary: list[str] = [protein_xml]
    if keep_water:
        primary.append(water_xml)
    if gb_xml:
        primary.append(gb_xml)
    out: list[tuple[str, ...]] = [tuple(primary)]
    if gb_xml and gb_xml != gb_fallback:
        alt = [protein_xml]
        if keep_water:
            alt.append(water_xml)
        alt.append(gb_fallback)
        out.append(tuple(alt))
    return tuple(out)


def _solvent_label(
    xmls: tuple[str, ...],
    *,
    used_gb: bool,
    used_salt: bool,
    salt_m: float = _GB_SALT_M,
) -> str:
    if not used_gb:
        return "VACUUM"
    model = "GBN2" if any("gbn2" in x for x in xmls) else "OBC2"
    if used_salt:
        return f"{model} I={float(salt_m):.2f}M"
    return model


def _assign_ligand_charges(molecule) -> str:
    last_exc: Exception | None = None
    for method in ("am1bcc", "gasteiger", "mmff94"):
        try:
            molecule.assign_partial_charges(method)
            return method
        except Exception as exc:
            last_exc = exc
    raise RuntimeError(
        "Could not assign partial charges for GAFF2. "
        f"{last_exc} Install AmberTools for AM1-BCC, or provide a simpler ligand."
    ) from last_exc


def _ligand_ff_names(ligand_ff: str) -> tuple[str, ...]:
    if _normalize_ligand_ff(ligand_ff) == _LIGAND_FF_OPENFF:
        return ("openff-2.2.0", "openff-2.1.0", "openff-2.0.0")
    return ("gaff-2.11", "gaff-2.2.1")


def _ligand_ff_tag(ligand_ff: str) -> str:
    return "OPENFF-SAGE" if _normalize_ligand_ff(ligand_ff) == _LIGAND_FF_OPENFF else "GAFF2"


def _ff_attempts(
    *, keep_water: bool, solvent: str, protein_ff: str
) -> list[tuple[tuple[str, ...], bool, bool]]:
    sol = _normalize_solvent(solvent)
    attempts: list[tuple[tuple[str, ...], bool, bool]] = []
    if sol != _SOLVENT_VACUUM:
        for xmls in _protein_ff_xmls(keep_water=keep_water, solvent=sol, protein_ff=protein_ff):
            attempts.append((xmls, True, True))
            attempts.append((xmls, True, False))
    for xmls in _protein_ff_xmls(
        keep_water=keep_water, solvent=_SOLVENT_VACUUM, protein_ff=protein_ff
    ):
        attempts.append((xmls, False, False))
    return attempts


def _gaff2_system(
    pdb,
    rdkit_ligands: list,
    *,
    keep_water: bool,
    protein_ff: str = _PROTEIN_FF_AMBER14,
    ligand_ff: str = _LIGAND_FF_GAFF2,
    solvent: str = _SOLVENT_GBN2,
    salt_m: float = _GB_SALT_M,
) -> tuple[object, str]:
    """Build an OpenMM System with protein FF, small-molecule FF, and optional GBSA."""
    try:
        from openmm.app import HBonds, NoCutoff
        from openmmforcefields.generators import SystemGenerator
        from openff.toolkit import Molecule
    except Exception as exc:
        raise RuntimeError(
            "Ligand minimization requires openmmforcefields and OpenFF Toolkit. "
            "OpenFF is not installable from PyPI (the only upload was yanked). "
            "On Linux, macOS, or WSL: conda install -c conda-forge openff-toolkit. "
            "Native Windows is not supported by OpenFF — uncheck Include ligand in "
            "PROPKA protonation to minimize with AMBER only, or skip minimization."
        ) from exc

    molecules = []
    for mol in rdkit_ligands:
        off = Molecule.from_rdkit(mol, allow_undefined_stereo=True)
        if mol.HasProp("_Name"):
            off.name = mol.GetProp("_Name")
        _assign_ligand_charges(off)
        molecules.append(off)

    last_exc: Exception | None = None
    for xmls, gbsa, with_salt in _ff_attempts(
        keep_water=keep_water, solvent=solvent, protein_ff=protein_ff
    ):
        for ff_name in _ligand_ff_names(ligand_ff):
            try:
                ff_kwargs = {"constraints": HBonds, "rigidWater": True}
                if gbsa and with_salt:
                    ff_kwargs["implicitSolventKappa"] = _gb_kappa_per_nm(salt_m=salt_m)
                generator = SystemGenerator(
                    forcefields=list(xmls),
                    small_molecule_forcefield=ff_name,
                    molecules=molecules,
                    forcefield_kwargs=ff_kwargs,
                    nonperiodic_forcefield_kwargs={"nonbondedMethod": NoCutoff},
                )
                system = generator.create_system(pdb.topology)
                return system, _solvent_label(
                    xmls, used_gb=gbsa, used_salt=with_salt, salt_m=salt_m
                )
            except TypeError as exc:
                last_exc = exc
                continue
            except Exception as exc:
                last_exc = exc
    raise RuntimeError(
        "OpenMM could not parameterize the ligand with the chosen small-molecule force field. "
        f"{last_exc} Provide ligand SMILES or an SDF/MOL2 with correct bond orders."
    ) from last_exc


def _protein_only_system(
    pdb,
    *,
    keep_water: bool,
    protein_ff: str = _PROTEIN_FF_AMBER14,
    solvent: str = _SOLVENT_GBN2,
    salt_m: float = _GB_SALT_M,
) -> tuple[object, str]:
    from openmm.app import ForceField, HBonds, NoCutoff

    last_exc: Exception | None = None
    for xmls, gbsa, with_salt in _ff_attempts(
        keep_water=keep_water, solvent=solvent, protein_ff=protein_ff
    ):
        try:
            forcefield = ForceField(*xmls)
        except Exception as exc:
            last_exc = exc
            continue
        kwargs = {"constraints": HBonds, "nonbondedMethod": NoCutoff}
        if gbsa and with_salt:
            kwargs["implicitSolventKappa"] = _gb_kappa_per_nm(salt_m=salt_m)
        try:
            system = forcefield.createSystem(pdb.topology, **kwargs)
            return system, _solvent_label(xmls, used_gb=gbsa, used_salt=with_salt, salt_m=salt_m)
        except Exception as exc:
            last_exc = exc
    raise RuntimeError(
        "OpenMM could not parameterize the protonated structure. "
        f"{last_exc} Uncheck restrained minimization to keep the pdb2pqr hydrogens."
    ) from last_exc


def _rmsd_angstrom(ref_positions, new_positions, indices: list[int]) -> float | None:
    if not indices:
        return None
    from openmm import unit

    acc = 0.0
    for i in indices:
        a = ref_positions[i].value_in_unit(unit.angstrom)
        b = new_positions[i].value_in_unit(unit.angstrom)
        dx = float(a[0] - b[0])
        dy = float(a[1] - b[1])
        dz = float(a[2] - b[2])
        acc += dx * dx + dy * dy + dz * dz
    return (acc / len(indices)) ** 0.5


def _pocket_heavy_indices(topology, positions, ligand_keys: set[ResidueKey], cutoff: float = 5.0):
    from openmm import unit

    from ..structure_components import AMINO_ACIDS, NUCLEIC_ACIDS

    lig_xyz = []
    polymer_idx: list[int] = []
    cutoff_sq = float(cutoff) ** 2
    for atom in topology.atoms():
        key = _residue_key(atom.residue)
        name = (atom.name or "").strip()
        elem = ""
        element = getattr(atom, "element", None)
        if element is not None:
            elem = (getattr(element, "symbol", "") or "").upper()
        is_h = elem in {"H", "D"} or name.startswith("H")
        pos = positions[atom.index].value_in_unit(unit.angstrom)
        xyz = (float(pos[0]), float(pos[1]), float(pos[2]))
        if key in ligand_keys and not is_h:
            lig_xyz.append(xyz)
        resn = (getattr(atom.residue, "name", "") or "").strip().upper()
        if not is_h and (resn in AMINO_ACIDS or resn in NUCLEIC_ACIDS):
            polymer_idx.append((atom.index, xyz))
    if not lig_xyz:
        return []
    out: list[int] = []
    for idx, xyz in polymer_idx:
        x, y, z = xyz
        if any(
            (x - lx) ** 2 + (y - ly) ** 2 + (z - lz) ** 2 <= cutoff_sq for lx, ly, lz in lig_xyz
        ):
            out.append(idx)
    return out


def _restrained_minimize_pdb(
    input_pdb: Path,
    output_pdb: Path,
    *,
    restrained_ca_keys: set[ResidueKey],
    k_kcal_per_ang2: float,
    max_iterations: int,
    keep_water: bool,
    remarks: list[str],
    ligand_mols: list | None = None,
    chem_source: str = "",
    protein_ff: str = _PROTEIN_FF_AMBER14,
    ligand_ff: str = _LIGAND_FF_GAFF2,
    solvent: str = _SOLVENT_GBN2,
    salt_m: float = _GB_SALT_M,
    restraint_set: str = _RESTRAINT_BACKBONE,
    ligand_keys: set[ResidueKey] | None = None,
) -> None:
    import openmm
    from openmm import CustomExternalForce, LangevinMiddleIntegrator, unit
    from openmm.app import Simulation

    from .protein_prepare_qc import restrain_atom

    pdb = _open_openmm_structure(input_pdb)
    protein_ff = _normalize_protein_ff(protein_ff)
    ligand_ff = _normalize_ligand_ff(ligand_ff)
    restraint_set = _normalize_restraint_set(restraint_set)
    ligand_keys = ligand_keys or set()
    if ligand_mols:
        system, solvent_lbl = _gaff2_system(
            pdb,
            ligand_mols,
            keep_water=keep_water,
            protein_ff=protein_ff,
            ligand_ff=ligand_ff,
            solvent=solvent,
            salt_m=salt_m,
        )
        min_tag = f"{protein_ff.upper()} {_ligand_ff_tag(ligand_ff)} {solvent_lbl}"
    else:
        system, solvent_lbl = _protein_only_system(
            pdb,
            keep_water=keep_water,
            protein_ff=protein_ff,
            solvent=solvent,
            salt_m=salt_m,
        )
        min_tag = f"{protein_ff.upper()} {solvent_lbl}"
    scheme_tag = {
        _RESTRAINT_CA: "CA-RESTRAINED",
        _RESTRAINT_BACKBONE_LIGAND: "BACKBONE+LIGAND-RESTRAINED",
        _RESTRAINT_BACKBONE: "BACKBONE-RESTRAINED",
    }.get(restraint_set, "BACKBONE-RESTRAINED")
    for i, line in enumerate(remarks):
        if str(line).startswith("4 OPENMM "):
            remarks[i] = (
                f"4 OPENMM {scheme_tag} MIN {min_tag} K={float(k_kcal_per_ang2):.1f} KCAL/MOL/A**2"
            )
            break

    restraint = CustomExternalForce("0.5*k*((x-x0)^2+(y-y0)^2+(z-z0)^2)")
    restraint.addGlobalParameter(
        "k", float(k_kcal_per_ang2) * unit.kilocalories_per_mole / unit.angstroms**2
    )
    restraint.addPerParticleParameter("x0")
    restraint.addPerParticleParameter("y0")
    restraint.addPerParticleParameter("z0")

    original_keys = restrained_ca_keys or _ca_residue_keys(pdb.topology)
    n_restrained = 0
    for atom in pdb.topology.atoms():
        if not restrain_atom(
            atom, scheme=restraint_set, original_keys=original_keys, ligand_keys=ligand_keys
        ):
            continue
        pos = pdb.positions[atom.index]
        xyz = pos.value_in_unit(unit.nanometer)
        restraint.addParticle(atom.index, [float(xyz[0]), float(xyz[1]), float(xyz[2])])
        n_restrained += 1
    if n_restrained == 0:
        for atom in pdb.topology.atoms():
            if atom.name != "CA":
                continue
            pos = pdb.positions[atom.index]
            xyz = pos.value_in_unit(unit.nanometer)
            restraint.addParticle(atom.index, [float(xyz[0]), float(xyz[1]), float(xyz[2])])
            n_restrained += 1
    if n_restrained:
        system.addForce(restraint)

    try:
        platform = openmm.Platform.getPlatformByName("CPU")
    except Exception:
        platform = None
    integrator = LangevinMiddleIntegrator(
        300 * unit.kelvin, 1.0 / unit.picosecond, 0.002 * unit.picoseconds
    )
    if platform is None:
        simulation = Simulation(pdb.topology, system, integrator)
    else:
        simulation = Simulation(pdb.topology, system, integrator, platform)
    simulation.context.setPositions(pdb.positions)
    simulation.minimizeEnergy(maxIterations=int(max_iterations))
    positions = simulation.context.getState(getPositions=True).getPositions()
    ca_idx = [atom.index for atom in pdb.topology.atoms() if atom.name == "CA"]
    pocket_idx = _pocket_heavy_indices(pdb.topology, pdb.positions, ligand_keys)
    ca_rmsd = _rmsd_angstrom(pdb.positions, positions, ca_idx)
    pocket_rmsd = _rmsd_angstrom(pdb.positions, positions, pocket_idx)
    rmsd_bits = []
    if ca_rmsd is not None:
        rmsd_bits.append(f"CA={ca_rmsd:.2f}A")
    if pocket_rmsd is not None:
        rmsd_bits.append(f"POCKET={pocket_rmsd:.2f}A")
    if rmsd_bits:
        remarks.append("5 RMSD " + " ".join(rmsd_bits))
    _write_openmm_structure(
        pdb.topology,
        positions,
        output_pdb,
        remarks=remarks,
        chem_source=chem_source,
    )


def _ligand_chem_tables(
    text: str,
    *,
    fmt: str,
    keep_ligand: bool,
    ligand_keys: set[ResidueKey],
    input_text: str,
    input_fmt: str,
) -> tuple[dict, dict]:
    """Copy original mmCIF ``_chem_comp_*`` tables for ligands still in the file."""
    if not keep_ligand or not ligand_keys:
        return {}, {}
    remaining = _ligand_residue_names(text, fmt, ligand_keys)
    if not remaining:
        remaining = _ligand_residue_names(input_text, input_fmt, ligand_keys)
    if not remaining:
        return {}, {}
    from ..structure_components import parse_cif_chem_comp_atoms, parse_cif_chem_comp_bonds

    atoms: dict = {}
    bonds: dict = {}

    def _take(src: str, src_fmt: str, *, overwrite: bool) -> None:
        if not _is_cif_fmt(src_fmt):
            return
        parsed_atoms = parse_cif_chem_comp_atoms(src)
        parsed_bonds = parse_cif_chem_comp_bonds(src)
        for key, val in parsed_atoms.items():
            if key not in remaining:
                continue
            if overwrite or key not in atoms:
                atoms[key] = val
        for key, val in parsed_bonds.items():
            if key not in remaining:
                continue
            if overwrite or key not in bonds:
                bonds[key] = val

    _take(text, fmt, overwrite=True)
    _take(input_text, input_fmt, overwrite=True)
    return atoms, bonds


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
