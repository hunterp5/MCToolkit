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

"""RDKit 2D/3D coordinate preparation for the ligand viewer."""

from __future__ import annotations

import logging
import math

from rdkit import Chem
from rdkit.Chem import AllChem

from ..exception_policy import log_swallowed_exception

logger = logging.getLogger(__name__)

# Ideal pentafluorosulfanyl (–SF5) distances (Å). UFF has no S_6 type and can
# stretch S–F to ~4 Å; ETKDG alone also yields poor octahedral angles.
_SF5_S_F_ANGSTROM = 1.56
_SF5_S_C_ANGSTROM = 1.79


def _has_hypervalent_sulfur(mol: Chem.Mol) -> bool:
    """True when any sulfur has six heavy-atom neighbors (SF5 / SF6)."""
    for atom in mol.GetAtoms():
        if atom.GetAtomicNum() != 16:
            continue
        if sum(1 for nb in atom.GetNeighbors() if nb.GetAtomicNum() > 1) >= 6:
            return True
    return False


def _force_field_safe_for_3d(mol: Chem.Mol) -> bool:
    """
    False when MMFF/UFF are known to corrupt geometry.

    UFF reports success for ``S_6+6`` (SF5) while destroying bond lengths; skip it.
    """
    return not _has_hypervalent_sulfur(mol)


def _regularize_sf5_centers(mol: Chem.Mol) -> int:
    """
    Snap each –SF5 sulfur to octahedral geometry (organic + F axial, 4 F equatorial).

    Returns the number of SF5 centers adjusted. Safe no-op when no conformer / no SF5.
    """
    if mol is None or mol.GetNumConformers() == 0:
        return 0
    try:
        import numpy as np
        from rdkit.Geometry import Point3D
    except Exception:
        return 0

    conf = mol.GetConformer()
    n_fixed = 0
    for atom in mol.GetAtoms():
        if atom.GetAtomicNum() != 16:
            continue
        nbrs = list(atom.GetNeighbors())
        if len(nbrs) != 6:
            continue
        f_idxs = [nb.GetIdx() for nb in nbrs if nb.GetAtomicNum() == 9]
        other_idxs = [nb.GetIdx() for nb in nbrs if nb.GetAtomicNum() != 9]
        if len(f_idxs) != 5 or len(other_idxs) != 1:
            continue
        s_idx = atom.GetIdx()
        o_idx = other_idxs[0]
        s_pos = conf.GetAtomPosition(s_idx)
        o_pos = conf.GetAtomPosition(o_idx)
        axis = np.array([o_pos.x - s_pos.x, o_pos.y - s_pos.y, o_pos.z - s_pos.z], dtype=float)
        norm = float(np.linalg.norm(axis))
        if norm < 1e-6:
            axis = np.array([0.0, 0.0, 1.0])
        else:
            axis = axis / norm
        # Orthonormal equatorial basis.
        helper = np.array([1.0, 0.0, 0.0]) if abs(axis[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
        eq1 = np.cross(axis, helper)
        eq1 = eq1 / max(float(np.linalg.norm(eq1)), 1e-12)
        eq2 = np.cross(axis, eq1)
        eq2 = eq2 / max(float(np.linalg.norm(eq2)), 1e-12)

        other_el = mol.GetAtomWithIdx(o_idx).GetAtomicNum()
        r_ax = float(_SF5_S_C_ANGSTROM if other_el == 6 else _SF5_S_F_ANGSTROM)
        conf.SetAtomPosition(
            o_idx,
            Point3D(
                float(s_pos.x + axis[0] * r_ax),
                float(s_pos.y + axis[1] * r_ax),
                float(s_pos.z + axis[2] * r_ax),
            ),
        )
        # One F opposite the organic (axial); remaining four equatorial at 90°.
        axial_f, *eq_fs = f_idxs
        conf.SetAtomPosition(
            axial_f,
            Point3D(
                float(s_pos.x - axis[0] * _SF5_S_F_ANGSTROM),
                float(s_pos.y - axis[1] * _SF5_S_F_ANGSTROM),
                float(s_pos.z - axis[2] * _SF5_S_F_ANGSTROM),
            ),
        )
        for i, f_idx in enumerate(eq_fs):
            ang = (math.pi / 2.0) * i
            vec = math.cos(ang) * eq1 + math.sin(ang) * eq2
            conf.SetAtomPosition(
                f_idx,
                Point3D(
                    float(s_pos.x + vec[0] * _SF5_S_F_ANGSTROM),
                    float(s_pos.y + vec[1] * _SF5_S_F_ANGSTROM),
                    float(s_pos.z + vec[2] * _SF5_S_F_ANGSTROM),
                ),
            )
        n_fixed += 1
    return n_fixed


def _seed_crude_3d_coords(mol: Chem.Mol, *, bond_length: float = 1.5) -> bool:
    """
    Place a non-optimized 3D conformer when distance-geometry embed fails.

    Used for –SF5 (and similar) where ETKDG never converges; callers should
    regularize SF5 centers afterward.
    """
    if mol is None or mol.GetNumAtoms() == 0:
        return False
    try:
        from collections import deque

        from rdkit.Geometry import Point3D
    except Exception:
        return False
    n = mol.GetNumAtoms()
    conf = Chem.Conformer(n)
    start = 0
    for atom in mol.GetAtoms():
        if atom.GetAtomicNum() == 16 and atom.GetDegree() >= 6:
            start = atom.GetIdx()
            break
    conf.SetAtomPosition(start, Point3D(0.0, 0.0, 0.0))
    placed = {start}
    q: deque[int] = deque([start])
    while q:
        u = q.popleft()
        up = conf.GetAtomPosition(u)
        nbrs = [nb.GetIdx() for nb in mol.GetAtomWithIdx(u).GetNeighbors()]
        pending = [v for v in nbrs if v not in placed]
        for i, v in enumerate(pending):
            ang = (2.0 * math.pi * i) / max(len(pending), 1)
            conf.SetAtomPosition(
                v,
                Point3D(
                    float(up.x + bond_length * math.cos(ang)),
                    float(up.y + bond_length * math.sin(ang)),
                    float(up.z + 0.25 * ((i % 3) - 1)),
                ),
            )
            placed.add(v)
            q.append(v)
    for i in range(n):
        if i not in placed:
            conf.SetAtomPosition(i, Point3D(float(i) * bond_length, 0.0, 0.0))
    try:
        mol.RemoveAllConformers()
    except Exception:
        pass
    mol.AddConformer(conf, assignId=True)
    return mol.GetNumConformers() > 0


def prepare_mol_3d(mol: Chem.Mol) -> Chem.Mol | None:
    """
    Return a copy of *mol* with 3D coordinates (ETKDG embed + MMFF/UFF), or ``None`` on failure.

    Sketch-built molecules often carry Kekulé bond orders and a flat 2D conformer.
    Sanitize (aromatize) and clear conformers first so ETKDG uses aromatic ring
    templates — otherwise heterocycles can embed as non-planar.

    Hypervalent sulfur (–SF5) skips MMFF/UFF (UFF invents ``S_6+6`` and wrecks
    geometry) and is regularized to octahedral bond lengths/angles.
    """
    if mol is None or mol.GetNumAtoms() == 0:
        return None
    try:
        m = Chem.Mol(mol)
    except Exception:
        return None
    try:
        Chem.SanitizeMol(m)
    except Exception:
        try:
            m.UpdatePropertyCache(strict=False)
            Chem.GetSymmSSSR(m)
            Chem.SetAromaticity(m)
        except Exception:
            try:
                m.UpdatePropertyCache(strict=False)
            except Exception:
                pass
    try:
        m.RemoveAllConformers()
    except Exception:
        pass
    try:
        m = Chem.AddHs(m, addCoords=False)
    except TypeError:
        try:
            m = Chem.AddHs(m)
        except Exception:
            return None
    except Exception:
        return None
    params = None
    for name in ("ETKDGv3", "ETKDGv2", "ETKDG"):
        factory = getattr(AllChem, name, None)
        if factory is None:
            continue
        try:
            params = factory()
            break
        except Exception:
            continue
    if params is None:
        return None
    try:
        # Ignore any leftover coords; embed from distance geometry + ring templates.
        if hasattr(params, "clearConfs"):
            params.clearConfs = True
        if hasattr(params, "useRandomCoords"):
            params.useRandomCoords = True
    except Exception:
        pass
    try:
        cid = AllChem.EmbedMolecule(m, params)
    except Exception:
        cid = -1
    if cid != 0:
        try:
            cid = AllChem.EmbedMolecule(m, randomSeed=0xC0FFEE)
        except Exception:
            cid = -1
    if cid != 0 and _has_hypervalent_sulfur(m):
        # Small SF5 molecules sometimes fail ETKDG entirely; seed + regularize.
        try:
            cid = AllChem.EmbedMolecule(m, useRandomCoords=True, randomSeed=0x5F5)
        except Exception:
            cid = -1
        if cid != 0 and _seed_crude_3d_coords(m):
            cid = 0
    if cid != 0:
        logger.warning("RDKit could not embed a 3D conformer for this structure.")
        return None

    ff_safe = _force_field_safe_for_3d(m)
    if ff_safe:
        mmff_ok = False
        try:
            if AllChem.MMFFHasAllMoleculeParams(m):
                mmff_ok = AllChem.MMFFOptimizeMolecule(m, maxIters=200) == 0
        except Exception:
            mmff_ok = False
        if not mmff_ok:
            try:
                AllChem.UFFOptimizeMolecule(m, maxIters=200)
            except Exception:
                pass
    try:
        _regularize_sf5_centers(m)
    except Exception:
        log_swallowed_exception(logger, "SF5 octahedral regularization failed")
    try:
        m = Chem.RemoveHs(m)
    except Exception:
        pass
    return m


def prepare_mol_2d(mol: Chem.Mol) -> Chem.Mol | None:
    """Return a copy of *mol* with 2D coordinates for a flat depiction, or ``None`` on failure."""
    if mol is None or mol.GetNumAtoms() == 0:
        return None
    try:
        m = Chem.Mol(mol)
    except Exception:
        return None
    try:
        from rdkit.Chem import rdDepictor

        if rdDepictor.Compute2DCoords(m) != 0:
            raise RuntimeError("rdDepictor.Compute2DCoords failed")
    except Exception:
        try:
            if AllChem.Compute2DCoords(m) != 0:
                return None
        except Exception:
            return None
    return m
