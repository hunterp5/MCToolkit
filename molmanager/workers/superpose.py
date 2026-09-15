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

"""Conformer and structure superposition workers, plus RMSD."""

from __future__ import annotations

import logging
import os
import threading
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass

from PyQt5.QtCore import QRunnable
from rdkit import Chem
from rdkit.Chem import rdMolAlign

from ..config import load_config
from ..confs_codec import format_confs_table_cell, mol_from_packed_confs_cell, pack_confs_cell
from .chemistry_worker_common import emit_tool_progress_throttled
from .signals import WorkerSignals, emit_partial_results_if_cancelled

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SuperposeParams:
    """Options for :func:`run_superpose_conformers` / :class:`SuperposeConformersWorker`."""

    reference_conformer_index: int = 0
    heavy_atoms_only: bool = True
    reflect: bool = False
    max_align_iters: int = 50
    # When non-empty, RMS alignment uses only atoms matching this pattern (SMILES or SMARTS).
    align_pattern: str = ""
    align_pattern_is_smarts: bool = False
    # ``3d``: rigid AlignMol. ``2d``: topological 2D depiction matching.
    geometry: str = "3d"
    # ``largest_ring`` / ``central_ring`` when no custom pattern is set.
    align_mode: str = ""


def _normalize_superpose_geometry(value: str | None) -> str:
    g = str(value or "3d").strip().lower().replace("-", "_").replace(" ", "_")
    if g in {"2d", "2d_topological", "topological", "depict", "2d_topo"}:
        return "2d"
    return "3d"


def _normalize_align_mode(value: str | None) -> str:
    m = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if m in {"largest_ring", "largest", "largest_ring_system", "ring_system"}:
        return "largest_ring"
    if m in {"central_ring", "central", "most_central_ring", "most_central"}:
        return "central_ring"
    return ""


def _sssr_rings(mol: Chem.Mol) -> list[tuple[int, ...]]:
    try:
        Chem.GetSymmSSSR(mol)
    except Exception:
        pass
    try:
        rings = mol.GetRingInfo().AtomRings()
    except Exception:
        return []
    out: list[tuple[int, ...]] = []
    for ring in rings or ():
        idxs = tuple(int(i) for i in ring)
        if len(idxs) >= 3:
            out.append(idxs)
    return out


def _fused_ring_systems(rings: list[tuple[int, ...]]) -> list[set[int]]:
    n = len(rings)
    if n == 0:
        return []
    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    atom_sets = [set(r) for r in rings]
    for i in range(n):
        for j in range(i + 1, n):
            if atom_sets[i] & atom_sets[j]:
                union(i, j)
    groups: dict[int, set[int]] = {}
    for i, atoms in enumerate(atom_sets):
        groups.setdefault(find(i), set()).update(atoms)
    return list(groups.values())


def _filter_heavy(mol: Chem.Mol, idxs: list[int], *, heavy_only: bool) -> list[int]:
    if not heavy_only:
        return list(idxs)
    return [i for i in idxs if mol.GetAtomWithIdx(i).GetAtomicNum() != 1]


def _largest_ring_system_atoms(mol: Chem.Mol, *, heavy_only: bool) -> list[int] | None:
    rings = _sssr_rings(mol)
    if not rings:
        return None
    systems = _fused_ring_systems(rings)
    if not systems:
        return None

    def score(atoms: set[int]) -> tuple[int, int]:
        n_rings = sum(1 for r in rings if set(r) <= atoms)
        return (len(atoms), n_rings)

    chosen = max(systems, key=score)
    idxs = _filter_heavy(mol, sorted(chosen), heavy_only=heavy_only)
    return idxs if len(idxs) >= 2 else None


def _atom_graph_distances(mol: Chem.Mol) -> list[list[int]]:
    n = int(mol.GetNumAtoms())
    adj: list[list[int]] = [[] for _ in range(n)]
    for bond in mol.GetBonds():
        a = int(bond.GetBeginAtomIdx())
        b = int(bond.GetEndAtomIdx())
        adj[a].append(b)
        adj[b].append(a)
    dist = [[-1] * n for _ in range(n)]
    for src in range(n):
        dist[src][src] = 0
        queue = [src]
        for u in queue:
            du = dist[src][u]
            for v in adj[u]:
                if dist[src][v] < 0:
                    dist[src][v] = du + 1
                    queue.append(v)
    return dist


def _central_ring_atoms(mol: Chem.Mol, *, heavy_only: bool) -> list[int] | None:
    rings = _sssr_rings(mol)
    if not rings:
        return None
    n = int(mol.GetNumAtoms())
    heavy = [i for i in range(n) if mol.GetAtomWithIdx(i).GetAtomicNum() != 1]
    if mol.GetNumConformers() >= 1 and heavy:
        conf = mol.GetConformer()
        cx = cy = cz = 0.0
        for i in heavy:
            p = conf.GetAtomPosition(i)
            cx += float(p.x)
            cy += float(p.y)
            cz += float(p.z)
        inv = 1.0 / len(heavy)
        cx, cy, cz = cx * inv, cy * inv, cz * inv
        best = None
        best_d = None
        for ring in rings:
            rx = ry = rz = 0.0
            for i in ring:
                p = conf.GetAtomPosition(int(i))
                rx += float(p.x)
                ry += float(p.y)
                rz += float(p.z)
            k = 1.0 / len(ring)
            dx, dy, dz = rx * k - cx, ry * k - cy, rz * k - cz
            d2 = dx * dx + dy * dy + dz * dz
            key = (d2, -len(ring))
            if best_d is None or key < best_d:
                best_d = key
                best = ring
        if best is not None:
            idxs = _filter_heavy(mol, sorted(best), heavy_only=heavy_only)
            if len(idxs) >= 2:
                return idxs
    dist = _atom_graph_distances(mol)
    targets = heavy or list(range(n))
    best = None
    best_key = None
    for ring in rings:
        vals: list[int] = []
        for a in ring:
            for t in targets:
                d = dist[int(a)][int(t)]
                if d >= 0:
                    vals.append(d)
        if not vals:
            continue
        mean = sum(vals) / len(vals)
        key = (mean, -len(ring))
        if best_key is None or key < best_key:
            best_key = key
            best = ring
    if best is None:
        return None
    idxs = _filter_heavy(mol, sorted(best), heavy_only=heavy_only)
    return idxs if len(idxs) >= 2 else None


def _ring_atoms_for_mode(mol: Chem.Mol, mode: str, *, heavy_only: bool) -> list[int] | None:
    if mode == "largest_ring":
        return _largest_ring_system_atoms(mol, heavy_only=heavy_only)
    if mode == "central_ring":
        return _central_ring_atoms(mol, heavy_only=heavy_only)
    return None


def _query_from_atom_indices(mol: Chem.Mol, idxs: list[int]) -> Chem.Mol | None:
    """Subgraph query from atom indices (atomic number + bond type; extra substitution still matches)."""
    keep = sorted({int(i) for i in idxs})
    if len(keep) < 2:
        return None
    amap = {old: i for i, old in enumerate(keep)}
    em = Chem.RWMol()
    for old in keep:
        src = mol.GetAtomWithIdx(old)
        atom = Chem.Atom(int(src.GetAtomicNum()))
        atom.SetIsAromatic(bool(src.GetIsAromatic()))
        em.AddAtom(atom)
    for bond in mol.GetBonds():
        a = int(bond.GetBeginAtomIdx())
        b = int(bond.GetEndAtomIdx())
        if a not in amap or b not in amap:
            continue
        em.AddBond(amap[a], amap[b], bond.GetBondType())
        nb = em.GetBondBetweenAtoms(amap[a], amap[b])
        if nb is not None:
            try:
                nb.SetIsAromatic(bool(bond.GetIsAromatic()))
            except Exception:
                pass
    q = em.GetMol()
    try:
        Chem.SanitizeMol(q)
    except Exception:
        try:
            q.UpdatePropertyCache(strict=False)
        except Exception:
            pass
    return q if q.GetNumAtoms() >= 2 else None


def _prefer_coordgen() -> None:
    try:
        from rdkit.Chem import rdDepictor

        rdDepictor.SetPreferCoordGen(True)
    except Exception:
        pass


def _coords_are_planar(mol: Chem.Mol, *, z_tol: float = 1e-2) -> bool:
    if mol is None or mol.GetNumConformers() < 1:
        return False
    try:
        conf = mol.GetConformer()
        n = int(mol.GetNumAtoms())
    except Exception:
        return False
    if n < 1:
        return False
    for i in range(n):
        if abs(float(conf.GetAtomPosition(i).z)) > z_tol:
            return False
    return True


def _to_2d_mol(mol: Chem.Mol) -> Chem.Mol | None:
    """Copy *mol* and ensure a single 2D conformer (CoordGen when available)."""
    if mol is None:
        return None
    try:
        m = Chem.Mol(mol)
    except Exception:
        return None
    if m.GetNumAtoms() < 1:
        return None
    _prefer_coordgen()
    from rdkit.Chem import rdDepictor

    if m.GetNumConformers() >= 1 and _coords_are_planar(m):
        single = _single_conformer_mol(m)
        return single if single is not None else m
    try:
        rdDepictor.Compute2DCoords(m)
    except Exception:
        logger.debug("Compute2DCoords failed", exc_info=True)
        return None
    if m.GetNumConformers() < 1:
        return None
    return m


def _copy_atom_positions(
    src: Chem.Mol,
    dest: Chem.Mol,
    *,
    src_cid: int = -1,
    dest_cid: int = -1,
) -> None:
    sc = src.GetConformer(src_cid)
    dc = dest.GetConformer(dest_cid)
    n = min(int(src.GetNumAtoms()), int(dest.GetNumAtoms()))
    for i in range(n):
        dc.SetAtomPosition(i, sc.GetAtomPosition(i))


def _rms_from_atom_map(
    probe: Chem.Mol,
    ref: Chem.Mol,
    atom_map: list[tuple[int, int]] | None,
) -> float:
    pairs = list(atom_map or [])
    if len(pairs) < 1:
        n = min(int(probe.GetNumAtoms()), int(ref.GetNumAtoms()))
        pairs = [(i, i) for i in range(n)]
    if not pairs:
        return 0.0
    pc = probe.GetConformer()
    rc = ref.GetConformer()
    acc = 0.0
    for p_idx, r_idx in pairs:
        a = pc.GetAtomPosition(int(p_idx))
        b = rc.GetAtomPosition(int(r_idx))
        dx = float(a.x) - float(b.x)
        dy = float(a.y) - float(b.y)
        dz = float(a.z) - float(b.z)
        acc += dx * dx + dy * dy + dz * dz
    return (acc / len(pairs)) ** 0.5


def _align_2d_topological(
    probe: Chem.Mol,
    ref: Chem.Mol,
    atom_map: list[tuple[int, int]] | None,
) -> tuple[float, list[tuple[int, int]]]:
    """
    Constrain *probe* 2D coords to *ref* via :func:`rdDepictor.GenerateDepictionMatching2DStructure`.

    *atom_map* is AlignMol-style ``(probe_idx, ref_idx)``. RDKit's atomMap argument is
    ``(reference_idx, probe_idx)``. Returns ``(rms, used_map)`` in AlignMol order.
    """
    from rdkit.Chem import rdDepictor

    _prefer_coordgen()
    used: list[tuple[int, int]] = list(atom_map or [])
    if used:
        rdkit_map = [(int(r_idx), int(p_idx)) for p_idx, r_idx in used]
        rdDepictor.GenerateDepictionMatching2DStructure(probe, ref, rdkit_map)
    else:
        pairs = rdDepictor.GenerateDepictionMatching2DStructure(probe, ref)
        used = [(int(m_idx), int(r_idx)) for r_idx, m_idx in (pairs or [])]
    return _rms_from_atom_map(probe, ref, used), used


def _superpose_atom_map(
    m: Chem.Mol, params: SuperposeParams
) -> tuple[list[tuple[int, int]] | None, str | None]:
    """
    Build ``atomMap`` for :func:`rdMolAlign.AlignMol` (probe index, ref index) for same-molecule conformers.

    Returns ``(atom_map, None)`` or ``(None, error_code)``.
    """
    pat = (params.align_pattern or "").strip()
    if not pat:
        mode = _normalize_align_mode(getattr(params, "align_mode", ""))
        if mode:
            atoms = _ring_atoms_for_mode(m, mode, heavy_only=bool(params.heavy_atoms_only))
            if not atoms or len(atoms) < 2:
                return None, "no_ring_for_alignment"
            return [(i, i) for i in atoms], None
        if params.heavy_atoms_only:
            am = [(i, i) for i in range(m.GetNumAtoms()) if m.GetAtomWithIdx(i).GetAtomicNum() != 1]
        else:
            am = [(i, i) for i in range(m.GetNumAtoms())]
        if len(am) < 2:
            return None, "too_few_atoms_for_alignment"
        return am, None
    q: Chem.Mol | None
    try:
        if params.align_pattern_is_smarts:
            q = Chem.MolFromSmarts(pat)
        else:
            q = Chem.MolFromSmiles(pat)
    except Exception:
        q = None
    if q is None:
        return None, "invalid_align_pattern"
    try:
        match = m.GetSubstructMatch(q)
    except Exception:
        return None, "substructure_match_failed"
    if not match or len(match) < 1:
        return None, "align_pattern_not_found"
    idxs = [int(i) for i in match]
    if params.heavy_atoms_only:
        idxs = [i for i in idxs if m.GetAtomWithIdx(i).GetAtomicNum() != 1]
    if len(idxs) < 2:
        return None, "too_few_atoms_in_match"
    return [(i, i) for i in idxs], None


def _superpose_conformers_meta(
    *,
    params: SuperposeParams,
    ref_cid: int,
    ref_clamped: bool,
    n_conf: int,
    rms_vals: list[float],
    atom_map: list[tuple[int, int]],
    max_it: int,
    geometry: str,
) -> dict:
    meta: dict = {
        "ok": True,
        "op": "superpose",
        "geometry": geometry,
        "ref_cid": ref_cid,
        "ref_clamped": ref_clamped,
        "n_conf": n_conf,
        "rms_mean": round(sum(rms_vals) / max(len(rms_vals), 1), 6),
        "rms_max": round(max(rms_vals) if rms_vals else 0.0, 6),
        "heavy": bool(params.heavy_atoms_only),
        "reflect": bool(params.reflect),
        "max_align_iters": max_it,
        "n_align_atoms": len(atom_map),
    }
    ap = (params.align_pattern or "").strip()
    if ap:
        meta["align_smarts"] = bool(params.align_pattern_is_smarts)
        meta["align_pattern"] = ap[:120]
    mode = _normalize_align_mode(getattr(params, "align_mode", ""))
    if mode:
        meta["align_mode"] = mode
    return meta


def _run_superpose_conformers_2d(
    m: Chem.Mol,
    params: SuperposeParams,
    atom_map: list[tuple[int, int]],
    cids: list[int],
    ref_cid: int,
    ref_clamped: bool,
    cancel_event: threading.Event | None,
) -> tuple[Chem.Mol | None, dict]:
    """Redraw each conformer in 2D constrained to the reference layout."""
    meta: dict = {"ok": False, "op": "superpose", "geometry": "2d"}
    ref_slice = _single_conformer_mol(m, ref_cid)
    ref_2d = _to_2d_mol(ref_slice) if ref_slice is not None else None
    if ref_2d is None:
        meta["err"] = "need_2d_coords"
        return None, meta
    try:
        _copy_atom_positions(ref_2d, m, dest_cid=int(ref_cid))
    except Exception as e:
        meta["err"] = str(e)[:200]
        return None, meta
    rms_vals: list[float] = []
    max_it = max(10, int(params.max_align_iters))
    try:
        for cid in cids:
            if cancel_event is not None and cancel_event.is_set():
                meta["err"] = "cancelled"
                return None, meta
            ic = int(cid)
            if ic == ref_cid:
                rms_vals.append(0.0)
                continue
            prb = _single_conformer_mol(m, ic)
            prb_2d = _to_2d_mol(prb) if prb is not None else None
            if prb_2d is None:
                meta["err"] = "need_2d_coords"
                return None, meta
            rms, _used = _align_2d_topological(prb_2d, ref_2d, atom_map)
            _copy_atom_positions(prb_2d, m, dest_cid=ic)
            rms_vals.append(float(rms))
    except Exception as e:
        logger.exception("run_superpose_conformers 2D failed")
        meta["err"] = str(e)[:200]
        return None, meta
    return m, _superpose_conformers_meta(
        params=params,
        ref_cid=ref_cid,
        ref_clamped=ref_clamped,
        n_conf=len(cids),
        rms_vals=rms_vals,
        atom_map=atom_map,
        max_it=max_it,
        geometry="2d",
    )


def run_superpose_conformers(
    mol: Chem.Mol,
    params: SuperposeParams,
    cancel_event: threading.Event | None = None,
) -> tuple[Chem.Mol | None, dict]:
    """
    Superpose all conformers of *mol* onto one reference conformer.

    ``geometry="3d"`` uses :func:`rdMolAlign.AlignMol`. ``geometry="2d"`` regenerates
    2D drawings constrained to the reference layout
    (:func:`rdDepictor.GenerateDepictionMatching2DStructure`).
    """
    geom = _normalize_superpose_geometry(getattr(params, "geometry", "3d"))
    meta: dict = {"ok": False, "op": "superpose", "geometry": geom}
    try:
        m = Chem.Mol(mol)
    except Exception:
        meta["err"] = "bad_mol"
        return None, meta
    try:
        nconf = int(m.GetNumConformers())
    except Exception:
        nconf = 0
    if nconf < 2:
        meta["err"] = "need_at_least_two_conformers"
        return None, meta
    try:
        cids = sorted(c.GetId() for c in m.GetConformers())
    except Exception:
        cids = list(range(nconf))
    if not cids:
        meta["err"] = "no_conformer_ids"
        return None, meta
    ref_idx = int(params.reference_conformer_index)
    if ref_idx < 0:
        ref_idx = 0
    ref_clamped = False
    if ref_idx >= len(cids):
        ref_idx = len(cids) - 1
        ref_clamped = True
    ref_cid = int(cids[ref_idx])
    atom_map, map_err = _superpose_atom_map(m, params)
    if map_err or not atom_map:
        meta["err"] = map_err or "no_atoms_for_alignment"
        return None, meta
    if geom == "2d":
        return _run_superpose_conformers_2d(
            m, params, atom_map, cids, ref_cid, ref_clamped, cancel_event
        )
    rms_vals: list[float] = []
    max_it = max(10, int(params.max_align_iters))
    try:
        for cid in cids:
            if cancel_event is not None and cancel_event.is_set():
                meta["err"] = "cancelled"
                return None, meta
            ic = int(cid)
            if ic == ref_cid:
                rms_vals.append(0.0)
                continue
            rms = float(
                rdMolAlign.AlignMol(
                    m,
                    m,
                    prbCid=ic,
                    refCid=ref_cid,
                    atomMap=atom_map,
                    reflect=bool(params.reflect),
                    maxIters=max_it,
                )
            )
            rms_vals.append(rms)
    except Exception as e:
        logger.exception("run_superpose_conformers failed")
        meta["err"] = str(e)[:200]
        return None, meta
    return m, _superpose_conformers_meta(
        params=params,
        ref_cid=ref_cid,
        ref_clamped=ref_clamped,
        n_conf=len(cids),
        rms_vals=rms_vals,
        atom_map=atom_map,
        max_it=max_it,
        geometry="3d",
    )


@dataclass(frozen=True)
class SuperposeStructuresParams:
    """Options for aligning distinct table structures onto a reference molecule."""

    heavy_atoms_only: bool = True
    reflect: bool = False
    max_align_iters: int = 50
    align_pattern: str = ""
    align_pattern_is_smarts: bool = False
    use_mcs: bool = True
    # ``3d``: AlignMol / O3A. ``2d``: topological 2D depiction matching.
    geometry: str = "3d"
    # 3D only: Crippen/MMFF O3A (then index-map) when pattern and MCS yield no atom map.
    use_o3a: bool = True
    # ``largest_ring`` / ``central_ring`` when no custom pattern is set.
    align_mode: str = ""


def _single_conformer_mol(mol: Chem.Mol, conf_id: int | None = None) -> Chem.Mol | None:
    """Return a copy of *mol* that keeps only one conformer."""
    if mol is None:
        return None
    try:
        m = Chem.Mol(mol)
    except Exception:
        return None
    try:
        nconf = int(m.GetNumConformers())
    except Exception:
        nconf = 0
    if nconf < 1:
        return None
    try:
        cids = sorted(int(c.GetId()) for c in m.GetConformers())
    except Exception:
        cids = list(range(nconf))
    if not cids:
        return None
    keep = int(cids[0] if conf_id is None else conf_id)
    if keep not in cids:
        keep = int(cids[0])
    try:
        conf = Chem.Conformer(m.GetConformer(keep))
        m.RemoveAllConformers()
        m.AddConformer(conf, assignId=True)
    except Exception:
        return None
    return m


def _parse_align_query(pattern: str, *, is_smarts: bool) -> Chem.Mol | None:
    pat = (pattern or "").strip()
    if not pat:
        return None
    try:
        return Chem.MolFromSmarts(pat) if is_smarts else Chem.MolFromSmiles(pat)
    except Exception:
        return None


def _atom_map_from_query(
    probe: Chem.Mol,
    ref: Chem.Mol,
    query: Chem.Mol,
    *,
    heavy_atoms_only: bool,
) -> list[tuple[int, int]] | None:
    try:
        prb_match = probe.GetSubstructMatch(query)
        ref_match = ref.GetSubstructMatch(query)
    except Exception:
        return None
    if not prb_match or not ref_match or len(prb_match) != len(ref_match):
        return None
    pairs = [(int(p), int(r)) for p, r in zip(prb_match, ref_match)]
    if heavy_atoms_only:
        pairs = [
            (p, r)
            for p, r in pairs
            if probe.GetAtomWithIdx(p).GetAtomicNum() != 1
            and ref.GetAtomWithIdx(r).GetAtomicNum() != 1
        ]
    return pairs if len(pairs) >= 2 else None


def _atom_map_from_mcs(
    probe: Chem.Mol,
    ref: Chem.Mol,
    *,
    heavy_atoms_only: bool,
    timeout_s: int = 5,
) -> list[tuple[int, int]] | None:
    try:
        from rdkit.Chem import rdFMCS
    except Exception:
        return None
    try:
        res = rdFMCS.FindMCS(
            [ref, probe],
            timeout=int(timeout_s),
            matchValences=True,
            ringMatchesRingOnly=True,
            completeRingsOnly=False,
        )
    except Exception:
        return None
    if res is None or getattr(res, "canceled", False):
        return None
    smarts = getattr(res, "smartsString", "") or ""
    if not smarts or int(getattr(res, "numAtoms", 0) or 0) < 2:
        return None
    q = Chem.MolFromSmarts(smarts)
    if q is None:
        return None
    return _atom_map_from_query(probe, ref, q, heavy_atoms_only=heavy_atoms_only)


def _align_probe_to_ref_o3a(
    probe: Chem.Mol,
    ref: Chem.Mol,
    *,
    reflect: bool,
) -> tuple[float | None, str | None]:
    """Best-effort overlay when no atom map is available (Crippen O3A, then MMFF O3A)."""
    try:
        py_o3a = rdMolAlign.GetCrippenO3A(probe, ref)
        if py_o3a is not None:
            return float(py_o3a.Align()), "crippen_o3a"
    except Exception:
        logger.debug("Crippen O3A failed", exc_info=True)
    try:
        o3a = rdMolAlign.GetO3A(probe, ref)
        if o3a is not None:
            return float(o3a.Align()), "mmff_o3a"
    except Exception:
        logger.debug("MMFF O3A failed", exc_info=True)
    # Last resort: AlignMol without atomMap only works for identical atom counts / order.
    try:
        if probe.GetNumAtoms() == ref.GetNumAtoms() and probe.GetNumAtoms() >= 2:
            am = [(i, i) for i in range(probe.GetNumAtoms())]
            rms = float(
                rdMolAlign.AlignMol(
                    probe,
                    ref,
                    atomMap=am,
                    reflect=bool(reflect),
                    maxIters=50,
                )
            )
            return rms, "index_map"
    except Exception:
        logger.debug("Index-map AlignMol failed", exc_info=True)
    return None, None


def align_structure_onto_reference(
    probe: Chem.Mol,
    ref: Chem.Mol,
    params: SuperposeStructuresParams,
    cancel_event: threading.Event | None = None,
) -> tuple[Chem.Mol | None, dict]:
    """
    Align a copy of *probe* onto *ref*.

    3D: optional substructure pattern → MCS (when enabled) → O3A (when enabled).
    2D: same atom-map preference, then :func:`rdDepictor.GenerateDepictionMatching2DStructure`.
    """
    geom = _normalize_superpose_geometry(getattr(params, "geometry", "3d"))
    meta: dict = {"ok": False, "op": "superpose_structures", "geometry": geom}
    if cancel_event is not None and cancel_event.is_set():
        meta["err"] = "cancelled"
        return None, meta
    if geom == "2d":
        prb = _to_2d_mol(probe)
        reference = _to_2d_mol(ref)
        if prb is None or reference is None:
            meta["err"] = "need_2d_coords"
            return None, meta
    else:
        prb = _single_conformer_mol(probe)
        reference = _single_conformer_mol(ref)
        if prb is None or reference is None:
            meta["err"] = "need_3d_conformers"
            return None, meta
    max_it = max(10, int(params.max_align_iters))
    method = ""
    atom_map: list[tuple[int, int]] | None = None
    pat = (params.align_pattern or "").strip()
    ring_mode = _normalize_align_mode(getattr(params, "align_mode", ""))
    if pat:
        q = _parse_align_query(pat, is_smarts=bool(params.align_pattern_is_smarts))
        if q is None:
            meta["err"] = "invalid_align_pattern"
            return None, meta
        atom_map = _atom_map_from_query(
            prb, reference, q, heavy_atoms_only=bool(params.heavy_atoms_only)
        )
        if atom_map:
            method = "pattern"
        else:
            meta["pattern_miss"] = True
    elif ring_mode:
        atoms = _ring_atoms_for_mode(reference, ring_mode, heavy_only=bool(params.heavy_atoms_only))
        if not atoms or len(atoms) < 2:
            meta["err"] = "no_ring_for_alignment"
            return None, meta
        q = _query_from_atom_indices(reference, atoms)
        if q is not None:
            atom_map = _atom_map_from_query(
                prb, reference, q, heavy_atoms_only=bool(params.heavy_atoms_only)
            )
        if atom_map:
            method = ring_mode
        else:
            meta["ring_miss"] = True
    if atom_map is None and params.use_mcs:
        atom_map = _atom_map_from_mcs(
            prb, reference, heavy_atoms_only=bool(params.heavy_atoms_only)
        )
        if atom_map:
            method = "mcs"
    rms: float | None = None
    if geom == "2d":
        try:
            rms, used = _align_2d_topological(prb, reference, atom_map)
        except Exception as e:
            logger.exception("structure 2D depiction match failed")
            meta["err"] = str(e)[:200]
            return None, meta
        if not method:
            method = "2d_match"
        if used:
            atom_map = used
    elif atom_map is not None:
        try:
            rms = float(
                rdMolAlign.AlignMol(
                    prb,
                    reference,
                    atomMap=atom_map,
                    reflect=bool(params.reflect),
                    maxIters=max_it,
                )
            )
        except Exception as e:
            logger.exception("structure AlignMol failed")
            meta["err"] = str(e)[:200]
            return None, meta
    else:
        if not bool(getattr(params, "use_o3a", True)):
            meta["err"] = "no_common_substructure"
            return None, meta
        rms, o3a_method = _align_probe_to_ref_o3a(prb, reference, reflect=bool(params.reflect))
        if rms is None or o3a_method is None:
            meta["err"] = "no_common_substructure_and_o3a_failed"
            return None, meta
        method = o3a_method
        atom_map = []
    meta["ok"] = True
    meta["method"] = method
    meta["rms"] = round(float(rms), 6)
    meta["n_align_atoms"] = len(atom_map) if atom_map else 0
    meta["heavy"] = bool(params.heavy_atoms_only)
    meta["reflect"] = bool(params.reflect)
    meta["max_align_iters"] = max_it
    if pat:
        meta["align_smarts"] = bool(params.align_pattern_is_smarts)
        meta["align_pattern"] = pat[:120]
    if ring_mode:
        meta["align_mode"] = ring_mode
    return prb, meta


def run_superpose_structures(
    ref_mol: Chem.Mol,
    probes: list[tuple[int, Chem.Mol]],
    params: SuperposeStructuresParams,
    *,
    ref_oid: int | None = None,
    cancel_event: threading.Event | None = None,
    progress=None,
) -> list[tuple[int, Chem.Mol | None, dict]]:
    """
    Align each probe onto *ref_mol*.

    Returns one ``(oid, aligned_mol_or_None, meta)`` per probe. The reference row
    (*ref_oid*, when set) is returned as a single-conformer copy without realigning.
    *progress*, when set, is ``progress(done, total)`` after each probe.
    """
    geom = _normalize_superpose_geometry(getattr(params, "geometry", "3d"))
    out: list[tuple[int, Chem.Mol | None, dict]] = []
    if geom == "2d":
        ref_single = _to_2d_mol(ref_mol)
    else:
        ref_single = _single_conformer_mol(ref_mol)
    ref_id = None if ref_oid is None else int(ref_oid)
    tot = max(len(probes), 1)
    for i, (oid, probe) in enumerate(probes):
        if cancel_event is not None and cancel_event.is_set():
            out.append(
                (int(oid), None, {"ok": False, "err": "cancelled", "op": "superpose_structures"})
            )
        elif ref_id is not None and int(oid) == ref_id:
            if geom == "2d":
                m = ref_single if ref_single is not None else _to_2d_mol(ref_mol)
            else:
                m = _single_conformer_mol(ref_single or ref_mol)
            out.append(
                (
                    int(oid),
                    m,
                    {
                        "ok": True,
                        "op": "superpose_structures",
                        "method": "reference",
                        "geometry": geom,
                        "rms": 0.0,
                        "n_align_atoms": 0,
                    },
                )
            )
        else:
            aligned, meta = align_structure_onto_reference(
                probe,
                ref_mol if ref_single is None else ref_single,
                params,
                cancel_event=cancel_event,
            )
            out.append((int(oid), aligned, meta))
        if progress is not None:
            try:
                progress(i + 1, tot)
            except Exception:
                pass
    return out


def _superpose_row_task(task: tuple) -> tuple[int, Chem.Mol | None, str]:
    oid, cell, params = task[0], task[1], task[2]
    cancel_event = task[3] if len(task) > 3 else None
    try:
        if cancel_event is not None and cancel_event.is_set():
            return (
                oid,
                None,
                format_confs_table_cell({"ok": False, "err": "cancelled", "op": "superpose"}),
            )
        mol = mol_from_packed_confs_cell(cell or "")
        if mol is None:
            return (
                oid,
                None,
                format_confs_table_cell(
                    {"ok": False, "err": "no_packed_conformers", "op": "superpose"}
                ),
            )
        new_m, meta = run_superpose_conformers(mol, params, cancel_event=cancel_event)
        if new_m is None:
            return oid, None, format_confs_table_cell(meta)
        return oid, new_m, pack_confs_cell(meta, new_m)
    except Exception as e:
        logger.exception("SuperposeConformersWorker failed for oid=%s", oid)
        return (
            oid,
            None,
            format_confs_table_cell({"ok": False, "err": str(e)[:200], "op": "superpose"}),
        )


class SuperposeConformersWorker(QRunnable):
    """Align conformers from packed ``confs`` cells into a new ``superpose`` column payload."""

    def __init__(
        self,
        data: list[tuple[int, str]],
        params: SuperposeParams,
        signals: WorkerSignals,
        cancel_event: threading.Event | None = None,
        progress_state=None,
    ):
        super().__init__()
        self.data = data
        self.params = params
        self.signals = signals
        self.cancel_event = cancel_event
        self.progress_state = progress_state

    def run(self):
        nrows = len(self.data)
        tot = max(nrows, 1)
        tasks = [(oid, cell, self.params) for oid, cell in self.data]
        cfg = load_config()
        if cfg.conformer_threads is not None:
            max_workers = cfg.conformer_threads
        else:
            max_workers = min(4, max(1, (os.cpu_count() or 4) // 2))
        use_parallel = nrows >= 6 and max_workers > 1
        cancel_ev = self.cancel_event
        results: list = []
        cancelled = False
        done_count = 0
        prog_state = [0, 0.0]
        try:
            if use_parallel:
                emit_tool_progress_throttled(
                    self.signals,
                    "Superpose conformers…",
                    0,
                    tot,
                    prog_state,
                    progress_state=self.progress_state,
                )
                ex = ThreadPoolExecutor(max_workers=max_workers)
                shutdown_cancel = False
                try:
                    row_tasks = [(*t, cancel_ev) for t in tasks]
                    pending = {ex.submit(_superpose_row_task, rt) for rt in row_tasks}
                    done_count = 0
                    while pending:
                        if cancel_ev is not None and cancel_ev.is_set():
                            shutdown_cancel = True
                            cancelled = True
                            for f in list(pending):
                                if f.done() and not f.cancelled():
                                    try:
                                        results.append(f.result())
                                        done_count += 1
                                    except Exception:
                                        logger.exception("Superpose row task failed")
                                else:
                                    f.cancel()
                            break
                        completed, pending = wait(
                            pending, timeout=0.08, return_when=FIRST_COMPLETED
                        )
                        for f in completed:
                            if f.cancelled():
                                continue
                            try:
                                results.append(f.result())
                                done_count += 1
                            except Exception:
                                logger.exception("Superpose row task failed")
                            emit_tool_progress_throttled(
                                self.signals,
                                "Superpose conformers…",
                                done_count,
                                tot,
                                prog_state,
                                progress_state=self.progress_state,
                            )
                finally:
                    try:
                        ex.shutdown(wait=not shutdown_cancel, cancel_futures=shutdown_cancel)
                    except TypeError:
                        ex.shutdown(wait=not shutdown_cancel)
                emit_tool_progress_throttled(
                    self.signals,
                    "Superpose conformers…",
                    min(done_count, tot),
                    tot,
                    prog_state,
                    progress_state=self.progress_state,
                )
            else:
                for done, t in enumerate(tasks, start=1):
                    if cancel_ev is not None and cancel_ev.is_set():
                        cancelled = True
                        break
                    results.append(_superpose_row_task((*t, cancel_ev)))
                    done_count = done
                    emit_tool_progress_throttled(
                        self.signals,
                        "Superpose conformers…",
                        done,
                        tot,
                        prog_state,
                        progress_state=self.progress_state,
                    )
        finally:
            emit_partial_results_if_cancelled(
                self.signals, "Superpose conformers", done_count, tot, cancelled
            )
            try:
                self.signals.superpose_finished.emit(results)
            except Exception:
                logger.warning("superpose_finished emit failed", exc_info=True)


class SuperposeStructuresWorker(QRunnable):
    """Align distinct table structures onto a reference off the GUI thread."""

    def __init__(
        self,
        ref_oid: int,
        ref_mol: Chem.Mol,
        probes: list[tuple[int, Chem.Mol]],
        params: SuperposeStructuresParams,
        signals: WorkerSignals,
        cancel_event: threading.Event | None = None,
        progress_state=None,
    ):
        super().__init__()
        self.ref_oid = int(ref_oid)
        self.ref_mol = ref_mol
        self.probes = probes
        self.params = params
        self.signals = signals
        self.cancel_event = cancel_event
        self.progress_state = progress_state

    def run(self):
        tot = max(len(self.probes), 1)
        prog_state = [0, 0.0]
        cancelled = False
        results: list = []
        try:
            emit_tool_progress_throttled(
                self.signals,
                "Superpose…",
                0,
                tot,
                prog_state,
                progress_state=self.progress_state,
            )

            def _prog(done: int, total: int) -> None:
                emit_tool_progress_throttled(
                    self.signals,
                    "Superpose…",
                    done,
                    total,
                    prog_state,
                    progress_state=self.progress_state,
                )

            results = run_superpose_structures(
                self.ref_mol,
                self.probes,
                self.params,
                ref_oid=self.ref_oid,
                cancel_event=self.cancel_event,
                progress=_prog,
            )
            if self.cancel_event is not None and self.cancel_event.is_set():
                cancelled = True
        except Exception:
            logger.exception("SuperposeStructuresWorker failed")
            results = [
                (
                    int(oid),
                    None,
                    {"ok": False, "err": "worker_failed", "op": "superpose_structures"},
                )
                for oid, _m in self.probes
            ]
        finally:
            done_ok = sum(1 for _o, mol, meta in results if mol is not None and meta.get("ok"))
            emit_partial_results_if_cancelled(self.signals, "Superpose", done_ok, tot, cancelled)
            try:
                geom = _normalize_superpose_geometry(getattr(self.params, "geometry", "3d"))
                self.signals.superpose_structures_finished.emit(
                    {
                        "ref_oid": int(self.ref_oid),
                        "geometry": geom,
                        "results": results,
                    }
                )
            except Exception:
                logger.warning("superpose_structures_finished emit failed", exc_info=True)


@dataclass(frozen=True)
class RmsdParams:
    """Options for :func:`run_conformer_rmsd`."""

    reference_conformer_index: int = 0
    heavy_atoms_only: bool = True
    reflect: bool = False
    max_align_iters: int = 50
    align_pattern: str = ""
    align_pattern_is_smarts: bool = False
    source_column: str = "confs"


def run_conformer_rmsd(
    mol: Chem.Mol,
    params: RmsdParams,
    cancel_event: threading.Event | None = None,
) -> tuple[dict[str, str] | None, dict]:
    """
    Rigid-align each conformer to a reference and report RMSD (Å).

    Works on a copy of *mol* so input coordinates are unchanged. Reference RMSD is 0.
    """
    meta: dict = {"ok": False, "op": "rmsd"}
    if cancel_event is not None and cancel_event.is_set():
        meta["err"] = "cancelled"
        return None, meta
    try:
        m = Chem.Mol(mol)
    except Exception:
        meta["err"] = "bad_mol"
        return None, meta
    try:
        nconf = int(m.GetNumConformers())
    except Exception:
        nconf = 0
    if nconf < 1:
        meta["err"] = "no_conformers"
        return None, meta
    try:
        cids = sorted(int(c.GetId()) for c in m.GetConformers())
    except Exception:
        cids = list(range(nconf))
    if not cids:
        meta["err"] = "no_conformer_ids"
        return None, meta
    ref_idx = int(params.reference_conformer_index)
    if ref_idx < 0:
        ref_idx = 0
    ref_clamped = False
    if ref_idx >= len(cids):
        ref_idx = len(cids) - 1
        ref_clamped = True
    ref_cid = int(cids[ref_idx])
    sp = SuperposeParams(
        reference_conformer_index=ref_idx,
        heavy_atoms_only=bool(params.heavy_atoms_only),
        reflect=bool(params.reflect),
        max_align_iters=int(params.max_align_iters),
        align_pattern=(params.align_pattern or "").strip(),
        align_pattern_is_smarts=bool(params.align_pattern_is_smarts),
    )
    atom_map, map_err = _superpose_atom_map(m, sp)
    if map_err or not atom_map:
        meta["err"] = map_err or "no_atoms_for_alignment"
        return None, meta
    max_it = max(10, int(params.max_align_iters))
    rms_vals: list[float] = []
    try:
        for cid in cids:
            if cancel_event is not None and cancel_event.is_set():
                meta["err"] = "cancelled"
                return None, meta
            ic = int(cid)
            if ic == ref_cid:
                rms_vals.append(0.0)
                continue
            rms = float(
                rdMolAlign.AlignMol(
                    m,
                    m,
                    prbCid=ic,
                    refCid=ref_cid,
                    atomMap=atom_map,
                    reflect=bool(params.reflect),
                    maxIters=max_it,
                )
            )
            rms_vals.append(rms)
    except Exception as e:
        logger.exception("run_conformer_rmsd failed")
        meta["err"] = str(e)[:200]
        return None, meta
    mean_rms = sum(rms_vals) / max(len(rms_vals), 1)
    max_rms = max(rms_vals) if rms_vals else 0.0
    meta["ok"] = True
    meta["ref_idx"] = ref_idx
    meta["ref_cid"] = ref_cid
    meta["ref_clamped"] = ref_clamped
    meta["n_conf"] = len(cids)
    meta["rms_mean"] = round(mean_rms, 6)
    meta["rms_max"] = round(max_rms, 6)
    meta["heavy"] = bool(params.heavy_atoms_only)
    meta["n_align_atoms"] = len(atom_map)
    row = {
        "RMSD_values": ";".join(f"{v:.4f}" for v in rms_vals),
        "RMSD_max": f"{max_rms:.4f}",
        "RMSD_mean": f"{mean_rms:.4f}",
    }
    return row, meta
