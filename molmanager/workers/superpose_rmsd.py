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

"""Per-conformer RMSD after rigid alignment to a reference conformer."""

from __future__ import annotations

import logging
import threading

from rdkit import Chem
from rdkit.Chem import rdMolAlign

from .superpose_geom import _superpose_atom_map
from .superpose_types import RmsdParams, SuperposeParams

logger = logging.getLogger(__name__)


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
