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

"""Align conformers of one molecule (3D rigid or 2D topological)."""

from __future__ import annotations

import logging
import threading

from rdkit import Chem
from rdkit.Chem import rdMolAlign

from .superpose_geom import (
    _align_2d_topological,
    _copy_atom_positions,
    _normalize_align_mode,
    _normalize_superpose_geometry,
    _single_conformer_mol,
    _superpose_atom_map,
    _to_2d_mol,
)
from .superpose_types import SuperposeParams

logger = logging.getLogger(__name__)


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
