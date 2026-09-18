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


"""Coordinate atoms, ligand pocket plans, and polar-hydrogen overlays."""

from __future__ import annotations


import math
from dataclasses import replace
from typing import Any, Iterable

from .structure_cif import (
    _cif_cell,
    _cif_col,
    _cif_loop_index,
    _parse_cif_loops,
)
from .structure_component_types import (
    POCKET_CUTOFF_ANGSTROM,
    PocketViewPlan,
    StructureAtom,
    _HYDROGEN_ELEMENTS,
    _POLAR_H_BOND_ANGSTROM,
    is_hetero_heavy_element,
    _ResidueBucket,
    _norm_chain,
    _optional_float,
    _resi_selection_value,
)
from .structure_inventory import _classify_residue

_ATOM_CACHE_KEY: tuple | None = None
_ATOM_CACHE: tuple[StructureAtom, ...] | None = None


def parse_structure_atoms(
    text: str, fmt: str, *, include_altlocs: bool = False
) -> tuple[StructureAtom, ...]:
    """Coordinate atoms from the first model of a PDB-like or mmCIF file."""
    global _ATOM_CACHE_KEY, _ATOM_CACHE
    fmt_l = (fmt or "pdb").lower()
    key = (id(text), len(text), hash(text), fmt_l, bool(include_altlocs))
    cached = _ATOM_CACHE
    if cached is not None and key == _ATOM_CACHE_KEY:
        return cached
    if fmt_l in {"cif", "mmcif"}:
        atoms = tuple(_atoms_from_cif(text, include_altlocs=include_altlocs))
    else:
        atoms = tuple(_atoms_from_pdb(text, include_altlocs=include_altlocs))
    _ATOM_CACHE_KEY = key
    _ATOM_CACHE = atoms
    return atoms


def pocket_view_plan(
    text: str,
    fmt: str,
    *,
    ligand_keys: Iterable[tuple[str, str, str, str]] | None = None,
    cutoff: float = POCKET_CUTOFF_ANGSTROM,
    model: int | None = None,
) -> PocketViewPlan | None:
    """Zoom selections, nearby polymer residues, and a polar-H overlay for Pocket view.

    ``ligand_keys`` are ``(chain, resn, resi, icode)``. When omitted, every ligand
    residue in the file is used. Returns ``None`` when no ligand atoms are found.
    """
    atoms = parse_structure_atoms(text, fmt)
    if not atoms:
        return None
    kinds = _residue_kinds_from_atoms(atoms)
    if ligand_keys is None:
        lig_want = {key for key, kind in kinds.items() if kind == "ligand"}
    else:
        lig_want = {
            (
                _norm_chain(chain),
                (resn or "").strip().upper(),
                str(resi).strip(),
                (icode or "").strip(),
            )
            for chain, resn, resi, icode in ligand_keys
        }
    ligand_atoms = [a for a in atoms if _atom_residue_key(a) in lig_want and not _is_hydrogen(a)]
    if not ligand_atoms:
        return None
    cutoff_sq = float(cutoff) ** 2
    lig_have = {_atom_residue_key(a) for a in ligand_atoms}
    pocket_keys: set[tuple[str, str, str, str]] = set()
    for atom in atoms:
        key = _atom_residue_key(atom)
        if kinds.get(key) != "polymer" or _is_hydrogen(atom):
            continue
        if any(_dist_sq(atom, lig) <= cutoff_sq for lig in ligand_atoms):
            pocket_keys.add(key)
    ligand_sels = tuple(
        _residue_sel_from_key(key, model=model, hetflag=True) for key in sorted(lig_have)
    )
    residue_sels = tuple(_residue_sel_from_key(key, model=model) for key in sorted(pocket_keys))
    overlay_keys = lig_have | pocket_keys
    polar_h_pdb = _polar_hydrogen_overlay_pdb(
        [a for a in atoms if _atom_residue_key(a) in overlay_keys]
    )
    return PocketViewPlan(
        ligand_sels=ligand_sels,
        residue_sels=residue_sels,
        polar_h_pdb=polar_h_pdb,
    )


def _atom_residue_key(atom: StructureAtom) -> tuple[str, str, str, str]:
    return (atom.chain, atom.resn, atom.resi, atom.icode)


def _is_hydrogen(atom: StructureAtom) -> bool:
    return atom.elem in _HYDROGEN_ELEMENTS or atom.name.strip().upper() in {"H", "D"}


def _dist_sq(a: StructureAtom, b: StructureAtom) -> float:
    dx = a.x - b.x
    dy = a.y - b.y
    dz = a.z - b.z
    return dx * dx + dy * dy + dz * dz


def _residue_sel_from_key(
    key: tuple[str, str, str, str],
    *,
    model: int | None = None,
    hetflag: bool = False,
) -> dict[str, Any]:
    chain, resn, resi, icode = key
    sel: dict[str, Any] = {
        "chain": chain,
        "resn": resn,
        "resi": _resi_selection_value(resi),
    }
    if icode:
        sel["icode"] = icode
    if hetflag:
        sel["hetflag"] = True
    if model is not None:
        sel["model"] = int(model)
    return sel


def _residue_kinds_from_atoms(
    atoms: Iterable[StructureAtom],
) -> dict[tuple[str, str, str, str], str]:
    buckets: dict[tuple[str, str, str, str], _ResidueBucket] = {}
    for atom in atoms:
        key = _atom_residue_key(atom)
        bucket = buckets.get(key)
        if bucket is None:
            bucket = _ResidueBucket(
                chain=atom.chain, resn=atom.resn, resi=atom.resi, icode=atom.icode, het=atom.het
            )
            buckets[key] = bucket
        bucket.n_atoms += 1
        if atom.elem:
            bucket.elements.add(atom.elem)
        bucket.het = bucket.het or atom.het
    return {key: _classify_residue(bucket) for key, bucket in buckets.items()}


def _atoms_from_pdb(text: str, *, include_altlocs: bool = False) -> list[StructureAtom]:
    atoms: list[StructureAtom] = []
    saw_model = False
    for line in (text or "").splitlines():
        rec = line[:6].strip().upper() if line else ""
        if rec == "MODEL":
            if saw_model:
                break
            saw_model = True
            continue
        if rec == "ENDMDL" and atoms:
            break
        if rec not in {"ATOM", "HETATM"}:
            continue
        padded = line.ljust(80)
        alt = padded[16:17].strip()
        if alt and alt not in {"A", "1"} and not include_altlocs:
            continue
        name = padded[12:16].strip()
        resn = padded[17:20].strip() or name[:3]
        chain = _norm_chain(padded[21:22])
        resi = padded[22:26].strip() or "0"
        icode = padded[26:27].strip()
        try:
            x = float(padded[30:38])
            y = float(padded[38:46])
            z = float(padded[46:54])
        except ValueError:
            continue
        occ = _optional_float(padded[54:60], 1.0)
        bfac = _optional_float(padded[60:66], 0.0)
        elem = padded[76:78].strip() or "".join(ch for ch in name if ch.isalpha())[:2]
        atoms.append(
            StructureAtom(
                chain=chain,
                resn=resn.upper(),
                resi=resi,
                icode=icode,
                name=name,
                elem=elem.upper(),
                x=x,
                y=y,
                z=z,
                het=rec == "HETATM",
                altloc=alt,
                occupancy=occ,
                bfactor=bfac,
            )
        )
    return atoms


def _atoms_from_cif(text: str, *, include_altlocs: bool = False) -> list[StructureAtom]:
    atoms: list[StructureAtom] = []
    for tags, rows in _parse_cif_loops(text):
        if not any(t.lower().startswith("_atom_site.") for t in tags):
            continue
        index = _cif_loop_index(tags)
        i_group = _cif_col(index, "group_PDB")
        i_symbol = _cif_col(index, "type_symbol")
        i_atom = _cif_col(index, "auth_atom_id", "label_atom_id")
        i_comp = _cif_col(index, "auth_comp_id", "label_comp_id")
        i_asym = _cif_col(index, "auth_asym_id", "label_asym_id")
        i_seq = _cif_col(index, "auth_seq_id", "label_seq_id")
        i_icode = _cif_col(index, "pdbx_PDB_ins_code")
        i_model = _cif_col(index, "pdbx_PDB_model_num")
        i_x = _cif_col(index, "Cartn_x")
        i_y = _cif_col(index, "Cartn_y")
        i_z = _cif_col(index, "Cartn_z")
        i_alt = _cif_col(index, "label_alt_id")
        i_occ = _cif_col(index, "occupancy")
        i_b = _cif_col(index, "B_iso_or_equiv")
        if i_x is None or i_y is None or i_z is None:
            continue
        first_model = ""
        for row in rows:
            if i_model is not None:
                model = _cif_cell(row, i_model, "1") or "1"
                if not first_model:
                    first_model = model
                elif model != first_model:
                    continue
            alt_id = _cif_cell(row, i_alt)
            if alt_id and alt_id not in {".", "?", "A", "1"} and not include_altlocs:
                continue
            try:
                x = float(_cif_cell(row, i_x, "nan"))
                y = float(_cif_cell(row, i_y, "nan"))
                z = float(_cif_cell(row, i_z, "nan"))
            except ValueError:
                continue
            if not math.isfinite(x) or not math.isfinite(y) or not math.isfinite(z):
                continue
            name = _cif_cell(row, i_atom) or "X"
            resn = _cif_cell(row, i_comp, "UNK").upper() or "UNK"
            chain = _norm_chain(_cif_cell(row, i_asym, "?") or "?")
            resi = _cif_cell(row, i_seq, "0") or "0"
            icode = _cif_cell(row, i_icode)
            elem = _cif_cell(row, i_symbol) or "".join(ch for ch in name if ch.isalpha())[:2]
            group = _cif_cell(row, i_group, "ATOM")
            occ_raw = _cif_cell(row, i_occ, "1.0") if i_occ is not None else "1.0"
            b_raw = _cif_cell(row, i_b, "0.0") if i_b is not None else "0.0"
            alt = "" if alt_id in {".", "?", None} else str(alt_id)
            atoms.append(
                StructureAtom(
                    chain=chain,
                    resn=resn,
                    resi=str(resi),
                    icode=icode,
                    name=name,
                    elem=elem.upper(),
                    x=x,
                    y=y,
                    z=z,
                    het=str(group).upper().startswith("HET"),
                    altloc=alt,
                    occupancy=_optional_float(occ_raw, 1.0),
                    bfactor=_optional_float(b_raw, 0.0),
                )
            )
    return atoms


def _polar_hydrogen_overlay_pdb(atoms: list[StructureAtom]) -> str:
    """PDB of polar hydrogens plus their parent heteroatoms for a 3Dmol overlay."""
    if not atoms:
        return ""
    hydrogens = _existing_polar_hydrogens(atoms)
    if not hydrogens:
        hydrogens = _rdkit_polar_hydrogens(_pdb_from_atoms(atoms))
    hydrogens = _unique_atoms_by_xyz(hydrogens)
    if not hydrogens:
        return ""
    parents = [a for a in atoms if is_hetero_heavy_element(a.elem)]
    return _pdb_from_atoms(parents + hydrogens)


def _existing_polar_hydrogens(atoms: list[StructureAtom]) -> list[StructureAtom]:
    heavies = [a for a in atoms if not _is_hydrogen(a)]
    bond_sq = _POLAR_H_BOND_ANGSTROM**2
    out: list[StructureAtom] = []
    for atom in atoms:
        if not _is_hydrogen(atom):
            continue
        same = [
            heavy
            for heavy in heavies
            if (heavy.chain, heavy.resi, heavy.icode) == (atom.chain, atom.resi, atom.icode)
        ]
        if any(
            is_hetero_heavy_element(heavy.elem) and _dist_sq(atom, heavy) <= bond_sq
            for heavy in same
        ):
            out.append(replace(atom, elem="H", het=True))
    return out


def _rdkit_polar_hydrogens(pdb_block: str) -> list[StructureAtom]:
    if not pdb_block.strip():
        return []
    try:
        from rdkit import Chem
    except ImportError:
        return []
    try:
        mol = Chem.MolFromPDBBlock(pdb_block, removeHs=False, proximityBonding=True, sanitize=False)
    except TypeError:
        mol = Chem.MolFromPDBBlock(pdb_block, removeHs=False, sanitize=False)
    except Exception:
        return []
    if mol is None or mol.GetNumAtoms() == 0:
        return []
    try:
        Chem.SanitizeMol(mol)
    except Exception:
        pass
    try:
        mol_h = Chem.AddHs(mol, addCoords=True)
    except Exception:
        return []
    if mol_h is None or mol_h.GetNumConformers() == 0:
        return []
    conf = mol_h.GetConformer()
    out: list[StructureAtom] = []
    for atom in mol_h.GetAtoms():
        if atom.GetAtomicNum() != 1:
            continue
        neighbors = atom.GetNeighbors()
        if not neighbors or not is_hetero_heavy_element(neighbors[0].GetSymbol()):
            continue
        parent = neighbors[0]
        info = atom.GetPDBResidueInfo() or parent.GetPDBResidueInfo()
        pos = conf.GetAtomPosition(atom.GetIdx())
        chain = "?"
        resn = "UNK"
        resi = "0"
        icode = ""
        name = "H"
        het = True
        if info is not None:
            chain = _norm_chain(info.GetChainId())
            resn = (info.GetResidueName() or "UNK").strip().upper() or "UNK"
            resi = str(info.GetResidueNumber())
            icode = (info.GetInsertionCode() or "").strip()
            name = (info.GetName() or "H").strip() or "H"
            het = bool(info.GetIsHeteroAtom())
        out.append(
            StructureAtom(
                chain=chain,
                resn=resn,
                resi=resi,
                icode=icode,
                name=name,
                elem="H",
                x=float(pos.x),
                y=float(pos.y),
                z=float(pos.z),
                het=het,
            )
        )
    return out


def _unique_atoms_by_xyz(atoms: Iterable[StructureAtom]) -> list[StructureAtom]:
    seen: set[tuple[float, float, float]] = set()
    out: list[StructureAtom] = []
    for atom in atoms:
        key = (round(atom.x, 3), round(atom.y, 3), round(atom.z, 3))
        if key in seen:
            continue
        seen.add(key)
        out.append(atom)
    return out


def _pdb_from_atoms(atoms: Iterable[StructureAtom]) -> str:
    lines = [_format_pdb_atom(i, atom) for i, atom in enumerate(atoms, start=1)]
    if not lines:
        return ""
    return "\n".join(lines) + "\nEND\n"


def _format_pdb_atom(serial: int, atom: StructureAtom) -> str:
    rec = "HETATM" if atom.het else "ATOM  "
    raw_name = (atom.name or atom.elem or "X").strip()
    if len(raw_name) < 4 and len(atom.elem or "") <= 1:
        name_field = f" {raw_name:<3s}"[:4]
    else:
        name_field = f"{raw_name:<4s}"[:4]
    resn = (atom.resn or "UNK")[:3].rjust(3)
    chain = (atom.chain or " ")[:1] or " "
    try:
        resi_i = int(atom.resi)
    except (TypeError, ValueError):
        resi_i = 0
    icode = (atom.icode or " ")[:1] or " "
    elem = (atom.elem or "")[:2]
    return (
        f"{rec}{serial:5d} {name_field} {resn} {chain}{resi_i:4d}{icode}"
        f"   {atom.x:8.3f}{atom.y:8.3f}{atom.z:8.3f}  1.00  0.00          {elem:>2}"
    )
