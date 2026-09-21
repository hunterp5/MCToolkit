# This file is part of mctoolkit.
# Copyright (C) 2026 Hunter Picard
#
# mctoolkit is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# mctoolkit is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with mctoolkit. If not, see <https://www.gnu.org/licenses/>.

"""Crystal-ligand redock validation: extract a holo ligand and RMSD vs crystal."""

from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass
from pathlib import Path

from rdkit import Chem
from rdkit.Chem import rdMolAlign

logger = logging.getLogger(__name__)

CRYSTAL_RMSD_PROP = "crystalRMSD"
CRYSTAL_REF_PROP = "crystalRef"

_LIGAND_RESN = frozenset({"UNL", "LIG", "INH", "DRG", "MOL"})
_ROOT_LINE = re.compile(r"^ROOT\b")
_TORSDOF_LINE = re.compile(r"^TORSDOF\b", re.MULTILINE)


@dataclass(frozen=True)
class CrystalLigandPrep:
    """Apo receptor plus a crystal ligand file for an internal redock."""

    apo_receptor_path: str
    crystal_ligand_path: str
    stripped_from_receptor: bool


def _heavy(mol: Chem.Mol) -> Chem.Mol:
    try:
        return Chem.RemoveHs(Chem.Mol(mol), sanitize=False)
    except Exception:
        return Chem.Mol(mol)


def crystal_pose_rmsd(crystal: Chem.Mol, pose: Chem.Mol) -> float | None:
    """Heavy-atom RMSD (Å) in the receptor frame; no rigid superposition."""
    if crystal is None or pose is None:
        return None
    if crystal.GetNumConformers() < 1 or pose.GetNumConformers() < 1:
        return None
    ref = _heavy(crystal)
    prb = _heavy(pose)
    if int(ref.GetNumAtoms()) < 1 or int(prb.GetNumAtoms()) < 1:
        return None
    try:
        value = float(rdMolAlign.CalcRMS(prb, ref))
    except Exception:
        logger.debug("crystal RMSD CalcRMS failed", exc_info=True)
        value = _mapped_heavy_rmsd(ref, prb)
    if value is None or not math.isfinite(value):
        return None
    return value


def _mapped_heavy_rmsd(ref: Chem.Mol, pose: Chem.Mol) -> float | None:
    """RMSD from the first substructure match when graphs differ slightly."""
    try:
        matches = pose.GetSubstructMatches(ref, uniquify=True)
    except Exception:
        return None
    if not matches:
        try:
            matches = ref.GetSubstructMatches(pose, uniquify=True)
        except Exception:
            return None
        if not matches:
            return None
        return _coords_rmsd(pose, ref, matches[0])
    return _coords_rmsd(ref, pose, matches[0])


def _coords_rmsd(ref: Chem.Mol, pose: Chem.Mol, match: tuple[int, ...]) -> float | None:
    """RMSD of *pose* atoms in *match* onto *ref* atom order."""
    n = len(match)
    if n < 1 or n != int(ref.GetNumAtoms()):
        return None
    conf_r = ref.GetConformer()
    conf_p = pose.GetConformer()
    acc = 0.0
    for ref_i, pose_i in enumerate(match):
        a = conf_r.GetAtomPosition(ref_i)
        b = conf_p.GetAtomPosition(int(pose_i))
        dx = float(a.x) - float(b.x)
        dy = float(a.y) - float(b.y)
        dz = float(a.z) - float(b.z)
        acc += dx * dx + dy * dy + dz * dz
    return math.sqrt(acc / n)


def stamp_crystal_rmsd(mols: list[Chem.Mol], crystal: Chem.Mol | None) -> float | None:
    """Write ``crystalRMSD`` on each pose. Returns the top-ranked (first) RMSD."""
    if crystal is None or not mols:
        return None
    top: float | None = None
    for i, mol in enumerate(mols):
        if mol is None:
            continue
        rmsd = crystal_pose_rmsd(crystal, mol)
        if rmsd is None:
            continue
        mol.SetProp(CRYSTAL_RMSD_PROP, f"{rmsd:.3f}")
        if i == 0:
            top = rmsd
    return top


def _mol_display_name(mol: Chem.Mol | None) -> str:
    if mol is None:
        return ""
    for key in ("_Name", "Name"):
        if mol.HasProp(key):
            name = (mol.GetProp(key) or "").strip()
            if name:
                return name
    return ""


def _pdb_residue_label(mol: Chem.Mol | None) -> str:
    """First non-water PDB residue on *mol* (``AXI A 2000``)."""
    if mol is None:
        return ""
    seen: set[tuple[str, str, int, str]] = set()
    for atom in mol.GetAtoms():
        info = atom.GetPDBResidueInfo()
        if info is None:
            continue
        resn = (info.GetResidueName() or "").strip()
        if not resn or resn.upper() in {"HOH", "WAT", "DOD"}:
            continue
        chain = (info.GetChainId() or "").strip()
        try:
            resi = int(info.GetResidueNumber())
        except (TypeError, ValueError):
            continue
        icode = (info.GetInsertionCode() or "").strip()
        key = (resn, chain, resi, icode)
        if key in seen:
            continue
        seen.add(key)
        parts = [resn]
        if chain:
            parts.append(chain)
        parts.append(f"{resi}{icode}")
        return " ".join(parts)
    return ""


def crystal_ref_label(crystal: Chem.Mol | None, path: str | Path | None = None) -> str:
    """Human-readable id of the crystallographic ligand used for RMSD."""
    residue = _pdb_residue_label(crystal)
    if residue:
        return residue
    name = _mol_display_name(crystal)
    if name:
        return name
    text = str(path or "").strip()
    return Path(text).name if text else ""


def stamp_crystal_ref(mols: list[Chem.Mol], label: str) -> None:
    """Write ``crystalRef`` on crystal-redock poses naming the validation reference."""
    text = (label or "").strip()
    if not text:
        return
    for mol in mols:
        if mol is None:
            continue
        mol.SetProp(CRYSTAL_REF_PROP, text)


def load_crystal_mol(path: str | Path) -> Chem.Mol | None:
    """Load the crystallographic ligand pose from SDF, MOL, PDB, or PDBQT."""
    src = Path(path)
    if not src.is_file():
        return None
    suf = src.suffix.lower()
    try:
        if suf in {".sdf", ".sd"}:
            from .pose_file_io import load_sdf_mols

            mols = load_sdf_mols(src)
            return mols[0] if mols else None
        if suf == ".mol":
            mol = Chem.MolFromMolFile(str(src), removeHs=False)
            return mol
        text = src.read_text(encoding="utf-8", errors="replace")
        if suf == ".pdbqt":
            from .pose_file_io import mol_from_pdbqt_block, split_ligand_pdbqt_records

            records = split_ligand_pdbqt_records(text) or [text]
            for block in records:
                mol = mol_from_pdbqt_block(block)
                if mol is not None and mol.GetNumAtoms():
                    return mol
            return _mol_from_ligand_pdb(text)
        return _mol_from_ligand_pdb(text)
    except Exception:
        logger.debug("could not load crystal ligand %s", src, exc_info=True)
        return None


def _mol_from_ligand_pdb(pdb_text: str) -> Chem.Mol | None:
    from ..workers.protein_prepare_ligand import mol_from_ligand_pdb

    try:
        mol = mol_from_ligand_pdb(pdb_text)
    except ValueError:
        mol = Chem.MolFromPDBBlock(pdb_text, removeHs=False, sanitize=False)
    return mol if mol is not None and mol.GetNumAtoms() else None


def _write_ligand_sdf(mol: Chem.Mol, dest: Path) -> Path | None:
    from rdkit.Chem import SDWriter

    dest.parent.mkdir(parents=True, exist_ok=True)
    writer = SDWriter(str(dest))
    try:
        writer.write(mol)
    except Exception:
        logger.debug("could not write crystal SDF %s", dest, exc_info=True)
        try:
            dest.unlink(missing_ok=True)
        except OSError:
            pass
        return None
    finally:
        writer.close()
    return dest if dest.is_file() and dest.stat().st_size > 0 else None


def _atom_key(atom) -> tuple[str, str, str]:
    from ..workers.protein_prepare_io import _norm_key

    return _norm_key(atom.chain, atom.resi, atom.icode)


def split_pdbqt_holo(text: str) -> tuple[str, str] | None:
    """Split a receptor PDBQT that still has a ROOT…TORSDOF ligand."""
    raw = (text or "").replace("\r\n", "\n")
    if not _TORSDOF_LINE.search(raw):
        return None
    lines = raw.splitlines(keepends=True)
    root_i = next((i for i, ln in enumerate(lines) if _ROOT_LINE.match(ln)), None)
    if root_i is None:
        return None
    head = lines[:root_i]
    if not any(ln.startswith(("ATOM", "HETATM")) for ln in head):
        return None
    apo = "".join(head).rstrip() + "\n"
    ligand = "".join(lines[root_i:])
    if not ligand.strip():
        return None
    return apo, ligand if ligand.endswith("\n") else ligand + "\n"


def split_structure_holo(text: str, fmt: str) -> tuple[str, str] | None:
    """Apo PDB and ligand PDB when *text* still contains a non-water ligand."""
    from ..protein.structure_atoms import _pdb_from_atoms, parse_structure_atoms
    from ..protein.structure_component_types import AMINO_ACIDS, NUCLEIC_ACIDS
    from ..protein.structure_inventory import METAL_RESIDUES, WATER_RESIDUES
    from ..workers.protein_prepare_io import residue_kind_map
    from ..workers.protein_prepare_smina import ligand_keys_from_structure

    fmt_l = "pdb" if (fmt or "").lower() == "pdbqt" else (fmt or "pdb")
    atoms = parse_structure_atoms(text, fmt_l)
    if not atoms:
        return None
    kind_by_key = residue_kind_map(text, fmt_l)
    lig_keys = ligand_keys_from_structure(text, fmt_l)
    if not lig_keys:
        lig_keys = {key for key, kind in kind_by_key.items() if kind == "ligand"}
    if not lig_keys:
        skip = AMINO_ACIDS | NUCLEIC_ACIDS | WATER_RESIDUES | METAL_RESIDUES
        lig_keys = {
            _atom_key(atom)
            for atom in atoms
            if (atom.resn or "").strip().upper() in _LIGAND_RESN
            or ((atom.resn or "").strip().upper() not in skip and bool(getattr(atom, "het", False)))
        }
    if not lig_keys:
        return None
    apo_atoms = [a for a in atoms if _atom_key(a) not in lig_keys]
    lig_atoms = [a for a in atoms if _atom_key(a) in lig_keys]
    if not apo_atoms or not lig_atoms:
        return None
    apo_pdb = _pdb_from_atoms(apo_atoms)
    lig_pdb = _pdb_from_atoms(lig_atoms)
    if not (apo_pdb or "").strip() or not (lig_pdb or "").strip():
        return None
    return apo_pdb, lig_pdb


def split_holo_receptor(text: str, *, suffix: str) -> tuple[str, str, str] | None:
    """Return ``(apo_text, ligand_text, ligand_suffix)`` or ``None`` if apo."""
    suf = (suffix or "").lower()
    if suf == ".pdbqt":
        pdbqt = split_pdbqt_holo(text)
        if pdbqt is not None:
            return pdbqt[0], pdbqt[1], ".pdbqt"
    split = split_structure_holo(text, "pdbqt" if suf == ".pdbqt" else "pdb")
    if split is None:
        return None
    return split[0], split[1], ".pdb"


def write_ligand_file(ligand_text: str, dest: Path, *, ligand_suffix: str) -> Path | None:
    """Write an SDF when possible, otherwise the native ligand block."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    mol = None
    if ligand_suffix == ".pdbqt":
        from .pose_file_io import mol_from_pdbqt_block, split_ligand_pdbqt_records

        records = split_ligand_pdbqt_records(ligand_text) or [ligand_text]
        for block in records:
            mol = mol_from_pdbqt_block(block)
            if mol is not None and mol.GetNumAtoms():
                break
    if mol is None:
        mol = _mol_from_ligand_pdb(ligand_text)
    if mol is not None:
        sdf = dest.with_suffix(".sdf")
        written = _write_ligand_sdf(mol, sdf)
        if written is not None:
            return written
    native = dest.with_suffix(ligand_suffix if ligand_suffix in {".pdb", ".pdbqt"} else ".pdb")
    block = ligand_text if ligand_text.endswith("\n") else ligand_text + "\n"
    native.write_text(block, encoding="utf-8")
    return native


def existing_crystal_ligand_path(path: str | Path | None) -> str:
    """Return *path* when it is an existing file, else empty."""
    text = str(path or "").strip()
    if not text:
        return ""
    src = Path(text)
    return str(src) if src.is_file() else ""


def prepare_crystal_ligand(
    receptor_path: str | Path,
    dest_dir: Path,
    *,
    crystal_ligand_path: str = "",
) -> CrystalLigandPrep | None:
    """Apo receptor + crystal ligand for Gnina, extracting a holo ligand when present.

    Dock File / Fast Prepare already write an apo PDBQT and a crystal SDF sidecar.
    If the receptor still contains a ligand (user-supplied holo PDB/PDBQT), that
    ligand is stripped so Gnina docks into an empty pocket and the coordinates
    are kept for RMSD.
    """
    rec = Path(receptor_path)
    sidecar = existing_crystal_ligand_path(crystal_ligand_path)
    dest_dir.mkdir(parents=True, exist_ok=True)
    if rec.is_file():
        text = rec.read_text(encoding="utf-8", errors="replace")
        split = split_holo_receptor(text, suffix=rec.suffix.lower())
        if split is not None:
            apo_text, lig_text, lig_suf = split
            apo_suf = rec.suffix.lower() if rec.suffix.lower() in {".pdb", ".pdbqt"} else ".pdb"
            if lig_suf == ".pdb" and apo_suf == ".pdbqt":
                apo_suf = ".pdb"
            apo_path = dest_dir / f"{rec.stem}_apo{apo_suf}"
            apo_path.write_text(
                apo_text if apo_text.endswith("\n") else apo_text + "\n", encoding="utf-8"
            )
            lig_path = write_ligand_file(
                lig_text, dest_dir / f"{rec.stem}_crystal", ligand_suffix=lig_suf
            )
            if lig_path is None and sidecar:
                return CrystalLigandPrep(str(apo_path), sidecar, True)
            if lig_path is None:
                return None
            return CrystalLigandPrep(str(apo_path), str(lig_path), True)
    if sidecar:
        return CrystalLigandPrep(str(rec), sidecar, False)
    return None
