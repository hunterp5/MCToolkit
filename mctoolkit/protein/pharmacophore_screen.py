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


"""3D pharmacophore screening of conformation ensembles (pairwise feature distances)."""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Sequence

import numpy as np

from .pharmacophore import (
    Pharmacophore,
    PharmacophoreFeature,
    feature_atom_matches,
    features_from_mol,
)

DEFAULT_SLACK_ANGSTROM = 1.2
COLUMN_SUFFIXES = ("Match", "Score", "RMSD", "Conf")


@dataclass(frozen=True)
class PharmacophoreScreenHit:
    """Best match of a query pharmacophore against one molecule (or one conformer)."""

    matched: bool
    n_matched: int
    n_query: int
    rmsd: float | None
    score: float
    conf_id: int | None = None


def screening_features(pharmacophore: Pharmacophore) -> list[PharmacophoreFeature]:
    """Enabled attractive sites. Exclusion volumes are protein-frame and ignored here."""
    return [feat for feat in pharmacophore.enabled_features() if feat.type != "Exclusion"]


def _dist(a: PharmacophoreFeature, b: PharmacophoreFeature) -> float:
    dx = float(a.x) - float(b.x)
    dy = float(a.y) - float(b.y)
    dz = float(a.z) - float(b.z)
    return math.sqrt(dx * dx + dy * dy + dz * dz)


def kabsch_rmsd(mobile: Sequence[Sequence[float]], target: Sequence[Sequence[float]]) -> float:
    """RMSD (Å) after translating and rotating *mobile* onto *target*."""
    p = np.asarray(mobile, dtype=float)
    q = np.asarray(target, dtype=float)
    if p.shape != q.shape or p.ndim != 2 or p.shape[1] != 3 or p.shape[0] == 0:
        raise ValueError("Kabsch RMSD needs matching Nx3 point sets.")
    if p.shape[0] == 1:
        return 0.0
    pc = p - p.mean(axis=0)
    qc = q - q.mean(axis=0)
    cov = pc.T @ qc
    u, _s, vt = np.linalg.svd(cov)
    rot = vt.T @ u.T
    if np.linalg.det(rot) < 0.0:
        vt[-1, :] *= -1.0
        rot = vt.T @ u.T
    aligned = pc @ rot
    diff = aligned - qc
    return float(np.sqrt(float((diff * diff).sum()) / float(p.shape[0])))


def _hit_score(rmsd: float | None) -> float:
    if rmsd is None or not math.isfinite(rmsd):
        return 0.0
    return 1.0 / (1.0 + max(0.0, float(rmsd)))


def _better(candidate: PharmacophoreScreenHit, best: PharmacophoreScreenHit) -> bool:
    if candidate.n_matched != best.n_matched:
        return candidate.n_matched > best.n_matched
    cand_rmsd = candidate.rmsd if candidate.rmsd is not None else math.inf
    best_rmsd = best.rmsd if best.rmsd is not None else math.inf
    if cand_rmsd != best_rmsd:
        return cand_rmsd < best_rmsd
    return candidate.score > best.score


def match_ligand_features(
    query: Sequence[PharmacophoreFeature],
    ligand: Sequence[PharmacophoreFeature],
    *,
    slack: float = DEFAULT_SLACK_ANGSTROM,
    min_matched: int | None = None,
) -> PharmacophoreScreenHit:
    """Assign same-type ligand sites so pairwise distances match the query within *slack*."""
    qfeats = list(query)
    n_query = len(qfeats)
    if n_query == 0:
        return PharmacophoreScreenHit(matched=False, n_matched=0, n_query=0, rmsd=None, score=0.0)
    need = n_query if min_matched is None else max(1, min(int(min_matched), n_query))
    tol = max(0.0, float(slack))
    by_type: dict[str, list[int]] = {}
    for i, feat in enumerate(ligand):
        by_type.setdefault(feat.type, []).append(i)

    best = PharmacophoreScreenHit(matched=False, n_matched=0, n_query=n_query, rmsd=None, score=0.0)
    mapping: list[tuple[int, int]] = []
    used: set[int] = set()

    def consider() -> None:
        nonlocal best
        if len(mapping) < need:
            return
        q_pts = [(qfeats[qi].x, qfeats[qi].y, qfeats[qi].z) for qi, _li in mapping]
        l_pts = [(ligand[li].x, ligand[li].y, ligand[li].z) for _qi, li in mapping]
        rmsd = kabsch_rmsd(l_pts, q_pts)
        n_hit = len(mapping)
        cand = PharmacophoreScreenHit(
            matched=n_hit >= need,
            n_matched=n_hit,
            n_query=n_query,
            rmsd=rmsd,
            score=_hit_score(rmsd) if n_hit >= need else 0.0,
        )
        if _better(cand, best):
            best = cand

    def rec(qi: int) -> None:
        remaining = n_query - qi
        if len(mapping) + remaining < need:
            return
        if qi == n_query:
            consider()
            return
        qf = qfeats[qi]
        for li in by_type.get(qf.type, ()):
            if li in used:
                continue
            lig = ligand[li]
            if not feature_atom_matches(qf.atom, lig.atom):
                continue
            ok = True
            for qj, lj in mapping:
                if abs(_dist(qfeats[qj], qf) - _dist(ligand[lj], lig)) > tol:
                    ok = False
                    break
            if not ok:
                continue
            mapping.append((qi, li))
            used.add(li)
            rec(qi + 1)
            used.remove(li)
            mapping.pop()
            if best.n_matched == n_query and best.rmsd is not None and best.rmsd < 1e-6:
                return
        if need < n_query:
            rec(qi + 1)

    rec(0)
    return best


def screen_mol(
    mol,
    pharmacophore: Pharmacophore,
    *,
    slack: float = DEFAULT_SLACK_ANGSTROM,
    min_matched: int | None = None,
) -> PharmacophoreScreenHit:
    """Best-conformer pharmacophore match for a multi-conformer RDKit mol."""
    query = screening_features(pharmacophore)
    n_query = len(query)
    empty = PharmacophoreScreenHit(
        matched=False, n_matched=0, n_query=n_query, rmsd=None, score=0.0, conf_id=None
    )
    if mol is None or n_query == 0:
        return empty
    try:
        confs = list(mol.GetConformers())
    except Exception:
        return empty
    if not confs:
        return empty
    need = n_query if min_matched is None else max(1, min(int(min_matched), n_query))
    best = empty
    for conf in confs:
        try:
            cid = int(conf.GetId())
        except Exception:
            continue
        ligand = features_from_mol(mol, conf_id=cid)
        hit = match_ligand_features(query, ligand, slack=slack, min_matched=need)
        ranked = replace(hit, conf_id=cid)
        if _better(ranked, best):
            best = ranked
            if best.matched and best.n_matched == n_query and (best.rmsd or 0.0) == 0.0:
                break
    if best.matched:
        return best
    return replace(best, score=0.0)


POSE_PHARMA_MATCH_PROP = "pharmaMatch"
POSE_PHARMA_RMSD_PROP = "pharmaRMSD"
POSE_PHARMA_N_PROP = "pharmaN"
DEFAULT_DOCK_SLACK_ANGSTROM = 0.5


def positional_rmsd(mobile: Sequence[Sequence[float]], target: Sequence[Sequence[float]]) -> float:
    """RMSD (Å) of paired points in a shared frame (no superposition)."""
    p = np.asarray(mobile, dtype=float)
    q = np.asarray(target, dtype=float)
    if p.shape != q.shape or p.ndim != 2 or p.shape[1] != 3 or p.shape[0] == 0:
        raise ValueError("Positional RMSD needs matching Nx3 point sets.")
    diff = p - q
    return float(np.sqrt(float((diff * diff).sum()) / float(p.shape[0])))


def _pose_conf_id(mol, conf_id: int | None) -> int | None:
    if conf_id is not None:
        try:
            return int(conf_id)
        except (TypeError, ValueError):
            return None
    try:
        return int(mol.GetConformer().GetId())
    except Exception:
        return None


def pose_hits_exclusion(
    mol,
    exclusions: Sequence[PharmacophoreFeature],
    *,
    conf_id: int | None = None,
) -> bool:
    """True when a ligand heavy atom falls inside an enabled Exclusion sphere."""
    sites = [feat.normalized() for feat in exclusions if feat.enabled]
    if mol is None or not sites:
        return False
    cid = _pose_conf_id(mol, conf_id)
    if cid is None:
        return False
    try:
        conf = mol.GetConformer(cid)
    except Exception:
        return False
    for atom in mol.GetAtoms():
        try:
            if int(atom.GetAtomicNum()) <= 1:
                continue
            pos = conf.GetAtomPosition(int(atom.GetIdx()))
        except Exception:
            continue
        elem = ""
        try:
            elem = str(atom.GetSymbol() or "")
        except Exception:
            elem = ""
        x, y, z = float(pos.x), float(pos.y), float(pos.z)
        for feat in sites:
            if not feature_atom_matches(feat.atom, elem):
                continue
            dx = x - float(feat.x)
            dy = y - float(feat.y)
            dz = z - float(feat.z)
            limit = float(feat.radius)
            if dx * dx + dy * dy + dz * dz <= limit * limit:
                return True
    return False


def match_pose_features(
    query: Sequence[PharmacophoreFeature],
    ligand: Sequence[PharmacophoreFeature],
    *,
    slack: float = DEFAULT_DOCK_SLACK_ANGSTROM,
    min_matched: int | None = None,
) -> PharmacophoreScreenHit:
    """Assign same-type ligand sites that lie inside each query sphere (protein frame)."""
    qfeats = [feat.normalized() for feat in query]
    n_query = len(qfeats)
    if n_query == 0:
        return PharmacophoreScreenHit(matched=False, n_matched=0, n_query=0, rmsd=None, score=0.0)
    need = n_query if min_matched is None else max(1, min(int(min_matched), n_query))
    tol = max(0.0, float(slack))
    by_type: dict[str, list[int]] = {}
    for i, feat in enumerate(ligand):
        by_type.setdefault(feat.type, []).append(i)

    best = PharmacophoreScreenHit(matched=False, n_matched=0, n_query=n_query, rmsd=None, score=0.0)
    mapping: list[tuple[int, int]] = []
    used: set[int] = set()

    def consider() -> None:
        nonlocal best
        if len(mapping) < need:
            return
        q_pts = [(qfeats[qi].x, qfeats[qi].y, qfeats[qi].z) for qi, _li in mapping]
        l_pts = [(ligand[li].x, ligand[li].y, ligand[li].z) for _qi, li in mapping]
        rmsd = positional_rmsd(l_pts, q_pts)
        n_hit = len(mapping)
        cand = PharmacophoreScreenHit(
            matched=n_hit >= need,
            n_matched=n_hit,
            n_query=n_query,
            rmsd=rmsd,
            score=_hit_score(rmsd) if n_hit >= need else 0.0,
        )
        if _better(cand, best):
            best = cand

    def rec(qi: int) -> None:
        remaining = n_query - qi
        if len(mapping) + remaining < need:
            return
        if qi == n_query:
            consider()
            return
        qf = qfeats[qi]
        limit = float(qf.radius) + tol
        for li in by_type.get(qf.type, ()):
            if li in used:
                continue
            lig = ligand[li]
            if not feature_atom_matches(qf.atom, lig.atom):
                continue
            if _dist(qf, lig) > limit:
                continue
            mapping.append((qi, li))
            used.add(li)
            rec(qi + 1)
            used.remove(li)
            mapping.pop()
            if best.n_matched == n_query and best.rmsd is not None and best.rmsd < 1e-6:
                return
        if need < n_query:
            rec(qi + 1)

    rec(0)
    return best


def match_docked_pose(
    mol,
    pharmacophore: Pharmacophore,
    *,
    slack: float = DEFAULT_DOCK_SLACK_ANGSTROM,
    conf_id: int | None = None,
    min_matched: int | None = None,
) -> PharmacophoreScreenHit:
    """In-place pharmacophore match for a docked pose (protein coordinates, no Kabsch)."""
    query = screening_features(pharmacophore)
    n_query = len(query)
    empty = PharmacophoreScreenHit(
        matched=False, n_matched=0, n_query=n_query, rmsd=None, score=0.0, conf_id=None
    )
    if mol is None:
        return empty
    cid = _pose_conf_id(mol, conf_id)
    if cid is None:
        return empty
    exclusions = [feat for feat in pharmacophore.enabled_features() if feat.type == "Exclusion"]
    if pose_hits_exclusion(mol, exclusions, conf_id=cid):
        return replace(empty, conf_id=cid)
    if n_query == 0:
        return PharmacophoreScreenHit(
            matched=True, n_matched=0, n_query=0, rmsd=0.0, score=1.0, conf_id=cid
        )
    ligand = features_from_mol(mol, conf_id=cid)
    hit = match_pose_features(query, ligand, slack=slack, min_matched=min_matched)
    return replace(hit, conf_id=cid)


def stamp_docked_pharmacophore(mol, hit: PharmacophoreScreenHit) -> None:
    """Write pose-browser fields for a protein-frame pharmacophore match."""
    if mol is None:
        return
    mol.SetProp(POSE_PHARMA_MATCH_PROP, "1" if hit.matched else "0")
    if hit.rmsd is not None and math.isfinite(hit.rmsd):
        mol.SetProp(POSE_PHARMA_RMSD_PROP, f"{hit.rmsd:.3f}")
    elif mol.HasProp(POSE_PHARMA_RMSD_PROP):
        mol.ClearProp(POSE_PHARMA_RMSD_PROP)
    mol.SetProp(POSE_PHARMA_N_PROP, f"{int(hit.n_matched)}/{int(hit.n_query)}")


def filter_docked_poses(
    mols: Sequence,
    pharmacophore: Pharmacophore,
    *,
    slack: float = DEFAULT_DOCK_SLACK_ANGSTROM,
) -> tuple[list, list]:
    """Stamp each pose and split matches from poses that miss the pharmacophore."""
    kept: list = []
    dropped: list = []
    for mol in mols:
        if mol is None:
            continue
        hit = match_docked_pose(mol, pharmacophore, slack=slack)
        stamp_docked_pharmacophore(mol, hit)
        if hit.matched:
            kept.append(mol)
        else:
            dropped.append(mol)
    return kept, dropped


def output_column_names(prefix: str) -> tuple[str, str, str, str]:
    """``{prefix}Match``, ``Score``, ``RMSD``, ``Conf``."""
    base = str(prefix or "pharma").strip() or "pharma"
    match, score, rmsd, conf = (f"{base}{suffix}" for suffix in COLUMN_SUFFIXES)
    return match, score, rmsd, conf
