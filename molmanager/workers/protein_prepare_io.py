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

"""File IO, PDBFixer helpers, and residue-key maps for Protein Prepare."""

from __future__ import annotations

import contextvars
import errno
import gc
import os
import time
from collections.abc import Callable
from io import StringIO
from pathlib import Path

from .protein_prepare_constants import ResidueKey

_prepare_log: contextvars.ContextVar[Callable[[str], None] | None] = contextvars.ContextVar(
    "protein_prepare_log", default=None
)


def bind_prepare_log(fn: Callable[[str], None] | None):
    """Install a Prepare log callback for this task (subprocess-safe via ContextVar)."""
    return _prepare_log.set(fn)


def unbind_prepare_log(token) -> None:
    _prepare_log.reset(token)


def log_prepare(message: str) -> None:
    """Send a user-facing progress line to the Prepare dialog log, if bound."""
    fn = _prepare_log.get()
    if fn is None:
        return
    text = (message or "").strip()
    if not text:
        return
    try:
        fn(text)
    except Exception:
        pass


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
