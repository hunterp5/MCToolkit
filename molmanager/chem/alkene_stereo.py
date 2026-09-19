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
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with MolManager.  If not, see <https://www.gnu.org/licenses/>.

"""2D alkene E/Z (and cis/trans layout) inference for the sketcher.

IUPAC **E/Z** compares the *higher-priority* substituent on each alkene carbon (Cahn–Ingold–Prelog
rules). **Cis/trans** is an older label for disubstituted alkenes: *cis* = higher-priority groups on
the same side of the double bond in a drawing (often aligns with **Z** when hydrogens are involved,
but cis is geometric while E/Z is priority-based).

This module uses RDKit ``CanonicalRankAtoms`` on a hydrogen-supplemented copy of the molecule (with
coordinates) to pick the highest-priority ligand at each end of each non-aromatic double bond, then
compares which side of the C=C axis those ligands lie on in 2D (cross product sign). It is a
practical match to textbook E/Z for typical organic sketches; exotic stereochemistry may be
skipped when priorities are tied or atoms are collinear.
"""

from __future__ import annotations

from rdkit import Chem


def _cross_z(ux: float, uy: float, wx: float, wy: float) -> float:
    return ux * wy - uy * wx


def _best_ligand_index(mol: Chem.Mol, ranks: list[int], ca: int, partner: int) -> int | None:
    """Neighbor of ``ca`` other than ``partner`` with best (lowest) canonical rank."""
    cand = [n.GetIdx() for n in mol.GetAtomWithIdx(ca).GetNeighbors() if n.GetIdx() != partner]
    if not cand:
        return None
    r_best = min(ranks[c] for c in cand)
    winners = [c for c in cand if ranks[c] == r_best]
    if len(winners) != 1:
        return None
    return winners[0]


def infer_alkene_ez_for_sketch_mol(mol: Chem.Mol, conf_id: int = 0) -> dict[tuple[int, int], str]:
    """
    Map each stereogenic non-aromatic C=C (or general double bond) to ``'E'`` or ``'Z'``.

    Keys are ``(min(i,j), max(i,j))`` using **heavy-atom indices** from ``mol`` (``AddHs`` preserves
    these indices). Returns only bonds where geometry and ranking yield an unambiguous label.
    """
    out: dict[tuple[int, int], str] = {}
    if mol.GetNumConformers() == 0 or mol.GetNumAtoms() < 2:
        return out
    try:
        mh = Chem.Mol(mol)
        Chem.SanitizeMol(mh)
        mh = Chem.AddHs(mh, addCoords=True)
        Chem.SanitizeMol(mh)
    except Exception:
        return out
    try:
        ranks = list(Chem.CanonicalRankAtoms(mh, breakTies=True))
    except Exception:
        return out
    try:
        conf = mh.GetConformer(conf_id)
    except Exception:
        return out

    for b in mh.GetBonds():
        if b.GetBondType() != Chem.BondType.DOUBLE:
            continue
        if b.GetIsAromatic():
            continue
        i, j = b.GetBeginAtomIdx(), b.GetEndAtomIdx()
        key = (min(i, j), max(i, j))
        if key in out:
            continue
        li = _best_ligand_index(mh, ranks, i, j)
        lj = _best_ligand_index(mh, ranks, j, i)
        if li is None or lj is None:
            continue
        pi = conf.GetAtomPosition(i)
        pj = conf.GetAtomPosition(j)
        pli = conf.GetAtomPosition(li)
        plj = conf.GetAtomPosition(lj)
        ux, uy = pj.x - pi.x, pj.y - pi.y
        if abs(ux) + abs(uy) < 1e-9:
            continue
        wi_x, wi_y = pli.x - pi.x, pli.y - pi.y
        wj_x, wj_y = plj.x - pj.x, plj.y - pj.y
        si = _cross_z(ux, uy, wi_x, wi_y)
        sj = _cross_z(ux, uy, wj_x, wj_y)
        prod = si * sj
        if abs(prod) < 1e-16:
            continue
        if abs(si) < 1e-12 or abs(sj) < 1e-12:
            continue
        out[key] = "Z" if prod > 0 else "E"
    return out
