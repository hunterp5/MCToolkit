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

"""Activity-cliff metrics derived from matched molecular pairs."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from rdkit import Chem
from rdkit.Chem import AllChem, DataStructs

from .mmp_analysis import MmpPair, canonicalize_pair_direction


@dataclass(frozen=True)
class ActivityCliffPoint:
    """One MMP pair plotted on the activity-cliff map."""

    pair_index: int
    oid_a: int
    oid_b: int
    change_heavy_atoms: int
    frag_distance: float
    abs_delta: float
    signed_delta: float
    transform: str
    core: str


def _heavy_atom_count(smiles: str, cache: dict[str, int]) -> int:
    if smiles in cache:
        return cache[smiles]
    mol = Chem.MolFromSmiles(smiles) if smiles else None
    n = 0 if mol is None else int(mol.GetNumHeavyAtoms())
    cache[smiles] = n
    return n


def _morgan_fp(smiles: str, cache: dict[str, object]):
    if smiles in cache:
        return cache[smiles]
    mol = Chem.MolFromSmiles(smiles) if smiles else None
    if mol is None:
        cache[smiles] = None
        return None
    try:
        fp = AllChem.GetMorganFingerprintAsBitVect(mol, 2, nBits=2048)
    except Exception:
        fp = None
    cache[smiles] = fp
    return fp


def fragment_tanimoto_distance(
    side_a: str,
    side_b: str,
    *,
    fp_cache: dict[str, object] | None = None,
) -> float:
    """Return ``1 − Tanimoto`` between Morgan fingerprints of two variable fragments."""
    cache = fp_cache if fp_cache is not None else {}
    fa = _morgan_fp(side_a, cache)
    fb = _morgan_fp(side_b, cache)
    if fa is None or fb is None:
        return 1.0
    try:
        sim = float(DataStructs.TanimotoSimilarity(fa, fb))
    except Exception:
        return 1.0
    return max(0.0, min(1.0, 1.0 - sim))


def change_heavy_atom_count(
    side_a: str,
    side_b: str,
    *,
    heavy_cache: dict[str, int] | None = None,
) -> int:
    """Heavy atoms in both variable sides (size of the structural change)."""
    cache = heavy_cache if heavy_cache is not None else {}
    return _heavy_atom_count(side_a, cache) + _heavy_atom_count(side_b, cache)


def build_activity_cliff_points(pairs: Sequence[MmpPair]) -> list[ActivityCliffPoint]:
    """Compute cliff-map coordinates for each MMP pair (canonical transform direction)."""
    heavy_cache: dict[str, int] = {}
    fp_cache: dict[str, object] = {}
    points: list[ActivityCliffPoint] = []
    for idx, pair in enumerate(pairs):
        transform, side_from, side_to, signed = canonicalize_pair_direction(pair)
        points.append(
            ActivityCliffPoint(
                pair_index=idx,
                oid_a=int(pair.oid_a),
                oid_b=int(pair.oid_b),
                change_heavy_atoms=change_heavy_atom_count(
                    side_from, side_to, heavy_cache=heavy_cache
                ),
                frag_distance=fragment_tanimoto_distance(side_from, side_to, fp_cache=fp_cache),
                abs_delta=abs(float(signed)),
                signed_delta=float(signed),
                transform=transform,
                core=pair.core or "",
            )
        )
    return points
