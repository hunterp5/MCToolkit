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

"""Write Smina receptor PDBQT, crystal ligand, and search-box files after Prepare."""

from __future__ import annotations

import logging
import tempfile
from dataclasses import dataclass
from pathlib import Path

from rdkit import Chem

from ..docking.pose_file_io import write_protein_setup
from ..docking.search_box import (
    DEFAULT_BOX_PADDING_A,
    DockingBox,
    box_from_points,
    smina_artifact_paths,
)
from ..protein.structure_components import _pdb_from_atoms, parse_structure_atoms
from .protein_prepare_constants import ResidueKey
from .protein_prepare_io import _norm_key, residue_kind_map

logger = logging.getLogger(__name__)

_RDKIT_LIGAND_SUFFIXES = {".sdf", ".sd", ".mol", ".mol2", ".ml2"}


@dataclass(frozen=True)
class ProteinPrepareResult:
    """Prepared structure path plus optional Smina sidecars."""

    output_path: str
    receptor_pdbqt: str = ""
    ligand_sdf: str = ""
    ligand_pdb: str = ""
    box_path: str = ""
    box: DockingBox | None = None
    warning: str = ""

    def can_open_smina(self) -> bool:
        """True when Open Gnina can prefill receptor, ligand, or search box."""
        return bool(
            self.receptor_pdbqt_path()
            or self.ligand_sdf
            or self.ligand_pdb
            or self.box_path
            or self.box is not None
        )

    def receptor_pdbqt_path(self) -> str:
        """Apo receptor PDBQT for Gnina, or empty if none was written."""
        rec = (self.receptor_pdbqt or "").strip()
        if rec.lower().endswith(".pdbqt"):
            return rec
        out = (self.output_path or "").strip()
        if out.lower().endswith(".pdbqt") and Path(out).is_file():
            return out
        return ""


def _atom_key(atom) -> ResidueKey:
    return _norm_key(atom.chain, atom.resi, atom.icode)


def _write_ligand_sdf(mols: list[Chem.Mol], path: Path) -> str:
    usable = [m for m in mols if m is not None and m.GetNumAtoms()]
    if not usable:
        return ""
    path.parent.mkdir(parents=True, exist_ok=True)
    writer = Chem.SDWriter(str(path))
    try:
        for mol in usable:
            writer.write(mol)
    finally:
        writer.close()
    return str(path)


def _mols_from_ligand_pdb(pdb_text: str) -> list[Chem.Mol]:
    from .protein_prepare_ligand import mol_from_ligand_pdb

    try:
        mol = mol_from_ligand_pdb(pdb_text)
    except ValueError:
        return []
    return [mol] if mol is not None else []


def _xyz_from_mol(mol: Chem.Mol) -> list[tuple[float, float, float]]:
    if mol is None or mol.GetNumConformers() == 0:
        return []
    conf = mol.GetConformer()
    return [
        (
            float(conf.GetAtomPosition(i).x),
            float(conf.GetAtomPosition(i).y),
            float(conf.GetAtomPosition(i).z),
        )
        for i in range(mol.GetNumAtoms())
    ]


def _mols_from_rdkit_ligand_file(path: Path) -> list[Chem.Mol]:
    suffix = path.suffix.lower()
    if suffix in {".sdf", ".sd", ".mol"}:
        mol = Chem.MolFromMolFile(str(path), removeHs=False, sanitize=False)
        if mol is not None and mol.GetNumAtoms():
            return [mol]
        if suffix in {".sdf", ".sd"}:
            suppl = Chem.SDMolSupplier(str(path), removeHs=False, sanitize=False)
            return [m for m in suppl if m is not None and m.GetNumAtoms()]
        return []
    if suffix in {".mol2", ".ml2"}:
        mol = Chem.MolFromMol2File(str(path), removeHs=False, sanitize=False)
        return [mol] if mol is not None and mol.GetNumAtoms() else []
    return []


def _pdb_block_from_mols(mols: list[Chem.Mol]) -> str:
    chunks: list[str] = []
    for mol in mols:
        if mol is None or mol.GetNumAtoms() == 0:
            continue
        try:
            block = Chem.MolToPDBBlock(mol) or ""
        except Exception:
            continue
        if block.strip():
            chunks.append(block)
    return "\n".join(chunks)


def _atoms_matching_keys(atoms, keys: set[ResidueKey], kind_by_key: dict[ResidueKey, str]):
    """Atoms whose residue matches *keys* exactly, then the same resi/icode any chain."""
    if not keys:
        return []
    exact = [a for a in atoms if _atom_key(a) in keys]
    if exact:
        return exact
    loose = {(key[1], key[2]) for key in keys}
    matched = [a for a in atoms if (_atom_key(a)[1], _atom_key(a)[2]) in loose]
    if not matched:
        return []
    lig_only = [a for a in matched if kind_by_key.get(_atom_key(a)) == "ligand"]
    return lig_only or matched


def _ligand_atoms(atoms, kind_by_key: dict[ResidueKey, str]):
    lig_keys = {key for key, kind in kind_by_key.items() if kind == "ligand"}
    return [a for a in atoms if _atom_key(a) in lig_keys]


def _box_payload_from_structure(
    text: str,
    fmt: str,
    keys: set[ResidueKey],
    *,
    all_ligands: bool = False,
) -> tuple[list, list[tuple[float, float, float]], str]:
    if not (text or "").strip():
        return [], [], ""
    atoms = parse_structure_atoms(text, fmt)
    if not atoms:
        return [], [], ""
    kind_by_key = residue_kind_map(text, fmt)
    box_atoms = _atoms_matching_keys(atoms, keys, kind_by_key)
    if not box_atoms and all_ligands:
        box_atoms = _ligand_atoms(atoms, kind_by_key)
    if not box_atoms:
        return [], [], ""
    xyz = [(a.x, a.y, a.z) for a in box_atoms]
    return box_atoms, xyz, _pdb_from_atoms(box_atoms)


def load_box_ligand_file(
    path: str | Path,
) -> tuple[list[tuple[float, float, float]], str, list[Chem.Mol]]:
    """Coordinates, a PDB block, and RDKit mols from a ligand or holo file."""
    src = Path(path).expanduser()
    if not src.is_file():
        raise ValueError(f"Ligand file not found: {src}")
    mols: list[Chem.Mol] = []
    if src.suffix.lower() in _RDKIT_LIGAND_SUFFIXES:
        mols = _mols_from_rdkit_ligand_file(src)
        xyz: list[tuple[float, float, float]] = []
        for mol in mols:
            xyz.extend(_xyz_from_mol(mol))
        if xyz:
            return xyz, _pdb_block_from_mols(mols), mols
    text = src.read_text(encoding="utf-8", errors="replace")
    from ..protein.structure_inventory import sniff_structure_format

    fmt = sniff_structure_format(src, text)
    if fmt == "pdbqt":
        fmt = "pdb"
    _, xyz, pdb_text = _box_payload_from_structure(text, fmt, set(), all_ligands=True)
    if not xyz:
        atoms = parse_structure_atoms(text, fmt)
        if atoms:
            xyz = [(a.x, a.y, a.z) for a in atoms]
            pdb_text = _pdb_from_atoms(atoms)
    if not xyz:
        raise ValueError(f"No coordinates in ligand file: {src}")
    if not mols:
        mols = _mols_from_ligand_pdb(pdb_text)
    return xyz, pdb_text, mols


def _emit_box_files(
    paths: dict[str, Path],
    *,
    xyz: list[tuple[float, float, float]],
    padding: float,
    pdb_text: str,
    mols: list[Chem.Mol],
) -> tuple[DockingBox, str, str]:
    box = box_from_points(xyz, padding=padding)
    ligand_pdb = ""
    if (pdb_text or "").strip():
        paths["ligand_pdb"].write_text(pdb_text, encoding="utf-8")
        ligand_pdb = str(paths["ligand_pdb"])
    write_protein_setup(
        paths["box"],
        center_x=box.center_x,
        center_y=box.center_y,
        center_z=box.center_z,
        size_x=box.size_x,
        size_y=box.size_y,
        size_z=box.size_z,
    )
    ligand_sdf = _write_ligand_sdf(mols, paths["ligand_sdf"])
    return box, ligand_pdb, ligand_sdf


def ligand_keys_from_structure(text: str, fmt: str) -> set[ResidueKey]:
    """Residue keys for every ligand component in a PDB/mmCIF string."""
    from ..protein.structure_components import parse_structure_components

    keys: set[ResidueKey] = set()
    try:
        comps = parse_structure_components(text or "", fmt or "pdb")
    except Exception:
        return keys
    for spec in comps:
        if spec.kind != "ligand":
            continue
        keys.add(_norm_key(spec.chain, spec.resi, spec.icode))
    return keys


def write_dock_file_artifacts(
    *,
    text: str,
    fmt: str,
    output_path: Path,
    box_ligand_keys: set[ResidueKey] | None = None,
    box_ligand_path: str = "",
    padding: float = DEFAULT_BOX_PADDING_A,
    source_text: str = "",
    source_fmt: str = "",
) -> ProteinPrepareResult:
    """Write Smina sidecars from an already-ready structure (no chemistry pipeline)."""
    ligands = ligand_keys_from_structure(text, fmt)
    return write_smina_prepare_artifacts(
        holo_text=text,
        fmt=fmt,
        output_path=output_path,
        ligand_keys=ligands,
        box_ligand_keys=box_ligand_keys,
        orig_box_ligand_keys=box_ligand_keys,
        padding=padding,
        box_ligand_path=box_ligand_path,
        source_text=source_text,
        source_fmt=source_fmt,
    )


def write_smina_prepare_artifacts(
    *,
    holo_text: str,
    fmt: str,
    output_path: Path,
    ligand_keys: set[ResidueKey],
    box_ligand_keys: set[ResidueKey] | None = None,
    orig_box_ligand_keys: set[ResidueKey] | None = None,
    ligand_mols: list[Chem.Mol] | None = None,
    padding: float = DEFAULT_BOX_PADDING_A,
    box_ligand_path: str = "",
    source_text: str = "",
    source_fmt: str = "",
) -> ProteinPrepareResult:
    """
    Write apo receptor PDBQT, crystal ligand PDB/SDF, and a Smina box file.

    The search box can come from an external ligand file, residue keys in the
    prepared (holo) coordinates, or the original loaded structure when PDBFixer
    remaps chain IDs. Ligand and water residues are stripped before Meeko
    receptor export.
    """
    paths = smina_artifact_paths(output_path)
    warnings: list[str] = []
    atoms = parse_structure_atoms(holo_text, fmt)
    kind_by_key = residue_kind_map(holo_text, fmt)
    water_keys = {key for key, kind in kind_by_key.items() if kind == "water"}
    ligands = {_norm_key(*key) for key in ligand_keys}
    remapped_keys = {_norm_key(*key) for key in (box_ligand_keys or ())}
    orig_keys = {_norm_key(*key) for key in (orig_box_ligand_keys or remapped_keys)}
    if not remapped_keys:
        remapped_keys = set(orig_keys or ligands)

    box: DockingBox | None = None
    ligand_pdb = ""
    ligand_sdf = ""
    box_from_file = bool((box_ligand_path or "").strip())
    if box_from_file:
        try:
            xyz, pdb_text, file_mols = load_box_ligand_file(box_ligand_path)
            mols = list(file_mols)
            if not mols:
                mols = _mols_from_ligand_pdb(pdb_text)
            box, ligand_pdb, ligand_sdf = _emit_box_files(
                paths, xyz=xyz, padding=padding, pdb_text=pdb_text, mols=mols
            )
        except (OSError, ValueError) as exc:
            warnings.append(str(exc) or "Could not read the ligand file for the docking box.")
    else:
        _, xyz, pdb_text = _box_payload_from_structure(holo_text, fmt, remapped_keys)
        used_source = False
        if not xyz and (source_text or "").strip():
            src_fmt = source_fmt or fmt
            _, xyz, pdb_text = _box_payload_from_structure(source_text, src_fmt, orig_keys)
            used_source = bool(xyz)
        if not xyz:
            _, xyz, pdb_text = _box_payload_from_structure(holo_text, fmt, set(), all_ligands=True)
        if not xyz and (source_text or "").strip():
            src_fmt = source_fmt or fmt
            _, xyz, pdb_text = _box_payload_from_structure(
                source_text, src_fmt, set(), all_ligands=True
            )
            used_source = bool(xyz)
        if xyz:
            mols = list(ligand_mols or [])
            use_prepared_mols = (not used_source) and (
                remapped_keys == ligands or not remapped_keys
            )
            if not mols or not use_prepared_mols:
                mols = _mols_from_ligand_pdb(pdb_text)
            box, ligand_pdb, ligand_sdf = _emit_box_files(
                paths, xyz=xyz, padding=padding, pdb_text=pdb_text, mols=mols
            )
        else:
            warnings.append(
                "No ligand atoms were found for the docking box. Choose a ligand "
                "in the loaded structure or a ligand file."
            )

    skip = ligands | water_keys
    apo_atoms = [a for a in atoms if _atom_key(a) not in skip]
    receptor_pdbqt = ""
    if apo_atoms:
        apo_pdb = _pdb_from_atoms(apo_atoms)
        tmp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                suffix=".pdb", prefix="mctoolkit_smina_rec_", delete=False
            ) as handle:
                tmp_path = Path(handle.name)
                handle.write(apo_pdb.encode("utf-8"))
            from .pdbqt_generator import _write_receptor_pdbqt_file

            err, ignored = _write_receptor_pdbqt_file(tmp_path, paths["receptor_pdbqt"])
            if err:
                warnings.append(err)
            else:
                receptor_pdbqt = str(paths["receptor_pdbqt"])
                if ignored:
                    warnings.append("Meeko skipped incomplete residues: " + ", ".join(ignored[:12]))
        except ImportError as exc:
            from .pdbqt_generator import meeko_import_error

            warnings.append(meeko_import_error(exc))
        except Exception as exc:
            logger.exception("Gnina receptor PDBQT export failed")
            warnings.append(str(exc) or "Meeko could not write receptor PDBQT.")
        finally:
            if tmp_path is not None:
                try:
                    tmp_path.unlink(missing_ok=True)
                except OSError:
                    pass
    else:
        warnings.append("No protein atoms remained for the receptor PDBQT.")

    return ProteinPrepareResult(
        output_path=str(output_path),
        receptor_pdbqt=receptor_pdbqt,
        ligand_sdf=ligand_sdf,
        ligand_pdb=ligand_pdb,
        box_path=str(paths["box"]) if box is not None and paths["box"].is_file() else "",
        box=box,
        warning="; ".join(warnings),
    )
