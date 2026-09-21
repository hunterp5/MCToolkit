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

"""Align distinct molecules onto a reference (MCS / pattern / O3A / 2D)."""

from __future__ import annotations

import logging
import threading

from rdkit import Chem
from rdkit.Chem import rdMolAlign

from .superpose_geom import (
    _align_2d_topological,
    _normalize_align_mode,
    _normalize_superpose_geometry,
    _query_from_atom_indices,
    _ring_atoms_for_mode,
    _single_conformer_mol,
    _to_2d_mol,
)
from .superpose_types import SuperposeStructuresParams

logger = logging.getLogger(__name__)


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
