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

"""Scalar 3D descriptors for Calculate Descriptors (shape, SASA, volume).

Coordinates come from packed ``confs`` / ``superpose`` cells or from a molecule that
already has a 3D conformer. No embedding is performed; missing 3D yields ``N/A``.
Values use the lowest-energy 3D conformer (MMFF94, UFF fallback; lowest id on ties).
If scoring fails, the first 3D conformer is used. Hydrogens are added with coordinates
when possible.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable

from rdkit import Chem
from rdkit.Chem import AllChem, Descriptors3D, rdMolDescriptors

from molmanager.conformers.conformer_column_codec import (
    conformer_is_3d,
    mol_from_packed_confs_cell,
    mol_has_3d_coordinates,
)

# Display label → internal key. Order is the Calculate Descriptors 3D tab order.
DESCRIPTOR_3D_ITEMS: tuple[tuple[str, str], ...] = (
    ("PMI 1", "PMI1"),
    ("PMI 2", "PMI2"),
    ("PMI 3", "PMI3"),
    ("NPR 1", "NPR1"),
    ("NPR 2", "NPR2"),
    ("Asphericity", "Asphericity"),
    ("Eccentricity", "Eccentricity"),
    ("Inertial shape factor", "InertialShapeFactor"),
    ("Radius of gyration", "RadiusOfGyration"),
    ("Spherocity index", "SpherocityIndex"),
    ("Plane of best fit (PBF)", "PBF"),
    ("SASA", "SASA"),
    ("Molecular volume", "MolVolume"),
)

DESCRIPTOR_3D_KEYS: frozenset[str] = frozenset(key for _disp, key in DESCRIPTOR_3D_ITEMS)


def int_fns_need_3d(int_fns: Iterable[str] | None) -> bool:
    """True when any selected descriptor requires 3D coordinates."""
    return any(isinstance(f, str) and f in DESCRIPTOR_3D_KEYS for f in (int_fns or ()))


def _3d_conformer_ids(mol: Chem.Mol) -> list[int]:
    ids: list[int] = []
    try:
        confs = list(mol.GetConformers())
    except Exception:
        return ids
    for conf in confs:
        try:
            if conformer_is_3d(conf):
                ids.append(int(conf.GetId()))
        except Exception:
            continue
    return ids


def _first_3d_conformer_id(mol: Chem.Mol) -> int | None:
    ids = _3d_conformer_ids(mol)
    return ids[0] if ids else None


def _single_point_energies_kcal(mol: Chem.Mol, cids: list[int]) -> dict[int, float] | None:
    """MMFF94 single-point energies, with UFF fallback. ``None`` if neither force field applies."""
    if not cids:
        return None
    try:
        mp = AllChem.MMFFGetMoleculeProperties(mol, mmffVariant="MMFF94")
    except Exception:
        mp = None
    if mp is not None:
        out: dict[int, float] = {}
        ok = True
        for cid in cids:
            ff = AllChem.MMFFGetMoleculeForceField(mol, mp, confId=int(cid))
            if ff is None:
                ok = False
                break
            out[int(cid)] = float(ff.CalcEnergy())
        if ok and len(out) == len(cids):
            return out
    out = {}
    for cid in cids:
        ff = AllChem.UFFGetMoleculeForceField(mol, confId=int(cid))
        if ff is None:
            return None
        out[int(cid)] = float(ff.CalcEnergy())
    return out


def _lowest_energy_3d_conformer_id(mol: Chem.Mol) -> int | None:
    """Lowest-energy 3D conformer id; lowest id on ties; first 3D id if scoring fails."""
    cids = _3d_conformer_ids(mol)
    if not cids:
        return None
    if len(cids) == 1:
        return cids[0]
    energies = _single_point_energies_kcal(mol, cids)
    if not energies:
        return cids[0]
    best_e = min(energies.values())
    tied = [cid for cid, e in energies.items() if e == best_e]
    return min(tied)


def _keep_single_conformer(mol: Chem.Mol, cid: int) -> Chem.Mol:
    work = Chem.Mol(mol)
    try:
        keep = Chem.Conformer(work.GetConformer(int(cid)))
        work.RemoveAllConformers()
        work.AddConformer(keep, assignId=True)
    except Exception:
        return work
    return work


def mol_for_3d_descriptors(
    mol: Chem.Mol | None,
    packed_cell: str | None = None,
) -> Chem.Mol | None:
    """
    Return a copy with one 3D conformer and (when possible) explicit H coordinates.

    Prefers *packed_cell* (``confs`` / ``superpose`` payload) over *mol*, because the
    Structure column is stored as a 2D depiction. The kept pose is the lowest-energy
    3D conformer (MMFF94, UFF fallback).
    """
    src: Chem.Mol | None = None
    cell = (packed_cell or "").strip()
    if cell:
        src = mol_from_packed_confs_cell(cell, min_conformers=1)
    if src is None and mol is not None and mol_has_3d_coordinates(mol):
        try:
            src = Chem.Mol(mol)
        except Exception:
            src = None
    if src is None or not mol_has_3d_coordinates(src):
        return None
    try:
        scored = Chem.AddHs(src, addCoords=True)
    except Exception:
        scored = src
    if scored is None or not mol_has_3d_coordinates(scored):
        scored = src
    cid = _lowest_energy_3d_conformer_id(scored)
    if cid is None:
        cid = _first_3d_conformer_id(scored)
    if cid is None:
        return None
    work = _keep_single_conformer(scored, cid)
    if work is not None and mol_has_3d_coordinates(work):
        return work
    return None


def _calc_sasa(mol: Chem.Mol) -> float:
    from rdkit.Chem import rdFreeSASA

    radii = rdFreeSASA.classifyAtoms(mol)
    return float(rdFreeSASA.CalcSASA(mol, radii))


def _calc_mol_volume(mol: Chem.Mol) -> float:
    return float(AllChem.ComputeMolVolume(mol))


DESCRIPTOR_3D_FNS: dict[str, Callable[[Chem.Mol], float]] = {
    "PMI1": lambda m: float(Descriptors3D.PMI1(m)),
    "PMI2": lambda m: float(Descriptors3D.PMI2(m)),
    "PMI3": lambda m: float(Descriptors3D.PMI3(m)),
    "NPR1": lambda m: float(Descriptors3D.NPR1(m)),
    "NPR2": lambda m: float(Descriptors3D.NPR2(m)),
    "Asphericity": lambda m: float(Descriptors3D.Asphericity(m)),
    "Eccentricity": lambda m: float(Descriptors3D.Eccentricity(m)),
    "InertialShapeFactor": lambda m: float(Descriptors3D.InertialShapeFactor(m)),
    "RadiusOfGyration": lambda m: float(Descriptors3D.RadiusOfGyration(m)),
    "SpherocityIndex": lambda m: float(Descriptors3D.SpherocityIndex(m)),
    "PBF": lambda m: float(rdMolDescriptors.CalcPBF(m)),
    "SASA": _calc_sasa,
    "MolVolume": _calc_mol_volume,
}
