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

"""RDKit mol helpers used by the sketcher (stereo, rings, kekulize)."""

from __future__ import annotations

from typing import Any

from rdkit import Chem
from rdkit.Chem.rdchem import BondDir


def mol_net_formal_charge(mol: Chem.Mol) -> int:
    return sum(mol.GetAtomWithIdx(i).GetFormalCharge() for i in range(mol.GetNumAtoms()))


def conformer_is_3d(conf, *, z_eps: float = 1e-3) -> bool:
    try:
        n = conf.GetNumAtoms()
    except Exception:
        return False
    for i in range(n):
        if abs(float(conf.GetAtomPosition(i).z)) > z_eps:
            return True
    return False


def capture_tetrahedral_chiral_tags(mol: Chem.Mol) -> dict[int, Any]:
    tags: dict[int, Any] = {}
    for atom in mol.GetAtoms():
        ct = atom.GetChiralTag()
        if ct != Chem.ChiralType.CHI_UNSPECIFIED:
            tags[int(atom.GetIdx())] = ct
    return tags


def restore_tetrahedral_chiral_tags(mol: Chem.Mol, tags: dict[int, Any]) -> None:
    for idx, ct in tags.items():
        try:
            mol.GetAtomWithIdx(int(idx)).SetChiralTag(ct)
        except Exception:
            pass


def clear_bond_dirs(mol: Chem.Mol) -> None:
    for bond in mol.GetBonds():
        try:
            bond.SetBondDir(BondDir.NONE)
        except Exception:
            pass


def atom_in_macrocycle(mol: Chem.Mol, idx: int, *, min_size: int = 9) -> bool:
    """True when *idx* belongs to a simple cycle of at least *min_size* atoms."""
    try:
        ri = mol.GetRingInfo()
        if ri.NumRings() == 0:
            Chem.GetSymmSSSR(mol)
            ri = mol.GetRingInfo()
        for ring in ri.AtomRings():
            if len(ring) >= min_size and int(idx) in ring:
                return True
    except Exception:
        return False
    return False


def has_wedgeable_stereo_substituent(mol: Chem.Mol, idx: int) -> bool:
    """ST-1.2 / ST-1.3 / ST-0.5: a ligand other than H can carry wedge/hash."""
    try:
        atom = mol.GetAtomWithIdx(int(idx))
    except Exception:
        return False
    in_ring = False
    try:
        in_ring = bool(atom.IsInRing())
    except Exception:
        in_ring = False
    for nb in atom.GetNeighbors():
        if nb.GetAtomicNum() == 1:
            continue
        bond = mol.GetBondBetweenAtoms(int(idx), int(nb.GetIdx()))
        if bond is None:
            continue
        bt = bond.GetBondType()
        if bt not in (Chem.BondType.SINGLE, Chem.BondType.UNSPECIFIED):
            continue
        if in_ring and bond.IsInRing():
            continue
        if nb.GetChiralTag() != Chem.ChiralType.CHI_UNSPECIFIED:
            continue
        return True
    return False


def stereocenter_indices_needing_explicit_h(mol: Chem.Mol) -> list[int]:
    """Tetrahedral centers that need an explicit stereo-H (ST-1.2)."""
    need: set[int] = set()
    try:
        mol.UpdatePropertyCache(strict=False)
    except Exception:
        pass
    try:
        if mol.GetRingInfo().NumRings() == 0:
            Chem.GetSymmSSSR(mol)
    except Exception:
        pass

    def _needs_stereo_h(atom: Chem.Atom) -> bool:
        try:
            if any(nb.GetAtomicNum() == 1 for nb in atom.GetNeighbors()):
                return False
            if int(atom.GetTotalNumHs()) <= 0:
                return False
            idx = int(atom.GetIdx())
            if has_wedgeable_stereo_substituent(mol, idx):
                return False
            return True
        except Exception:
            return False

    for atom in mol.GetAtoms():
        try:
            if atom.GetChiralTag() == Chem.ChiralType.CHI_UNSPECIFIED:
                continue
            if _needs_stereo_h(atom):
                need.add(int(atom.GetIdx()))
        except Exception:
            continue
    for legacy in (False, True):
        try:
            for cen in Chem.FindMolChiralCenters(
                mol,
                includeUnassigned=True,
                includeCIP=True,
                useLegacyImplementation=legacy,
            ):
                idx = int(cen[0])
                if _needs_stereo_h(mol.GetAtomWithIdx(idx)):
                    need.add(idx)
        except Exception:
            pass
    try:
        for si in Chem.FindPotentialStereo(mol):
            type_name = str(getattr(si, "type", "") or "")
            if "Tetrahedral" not in type_name and "Atom_Tetrahedral" not in type_name:
                continue
            idx = int(si.centeredOn)
            if _needs_stereo_h(mol.GetAtomWithIdx(idx)):
                need.add(idx)
    except Exception:
        pass
    return sorted(need)


def kekulize_for_sketch_orders(mol: Chem.Mol) -> None:
    """Localize aromatic bonds to single/double for sketcher bond orders."""
    if mol is None or mol.GetNumAtoms() == 0:
        return
    try:
        Chem.Kekulize(mol, clearAromaticFlags=True)
        return
    except Exception:
        pass
    try:
        tmp = Chem.Mol(mol)
        Chem.Kekulize(tmp, clearAromaticFlags=True)
    except Exception:
        return
    try:
        for b_src, b_dst in zip(tmp.GetBonds(), mol.GetBonds()):
            b_dst.SetBondType(b_src.GetBondType())
            b_dst.SetIsAromatic(False)
        for a_src, a_dst in zip(tmp.GetAtoms(), mol.GetAtoms()):
            a_dst.SetIsAromatic(False)
    except Exception:
        pass


def sanitize_mol_for_sketch_cip(mol: Chem.Mol) -> None:
    """Looser sanitize so CIP ranking can run on a sketched mol."""
    try:
        mol.UpdatePropertyCache(strict=False)
    except Exception:
        pass
    try:
        Chem.SanitizeMol(
            mol,
            sanitizeOps=Chem.SanitizeFlags.SANITIZE_PROPERTIES
            | Chem.SanitizeFlags.SANITIZE_SYMMRINGS,
        )
    except Exception:
        pass
