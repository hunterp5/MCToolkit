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
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with MCToolkit. If not, see <https://www.gnu.org/licenses/>.

"""Ring maps, 2D depiction matching, and atom-map helpers for superposition."""

from __future__ import annotations

import logging

from rdkit import Chem

from .superpose_types import SuperposeParams

logger = logging.getLogger(__name__)


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
