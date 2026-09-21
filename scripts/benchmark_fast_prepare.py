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
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with MCToolkit.  If not, see <https://www.gnu.org/licenses/>.

"""Measure the cost of each Fast Prepare stage (disconnect, neutralize, render 2D).

Compares the current serial-chemistry + parallel-render pipeline against a fused
process-pool pass that does all three stages per molecule in one round trip.

Usage:
    python scripts/benchmark_fast_prepare.py samples/fda_approved_full_cleaned.sdf [--limit N]
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mctoolkit.table.structure_depiction_layout import (  # noqa: E402
    STRUCTURE_DEPICT_HEIGHT,
    STRUCTURE_DEPICT_WIDTH,
)


def _fused_batch(args):
    """Disconnect + neutralize + render one batch inside a child process."""
    from rdkit import Chem

    from mctoolkit.chem.fragment_disconnect import largest_fragment_and_rest
    from mctoolkit.chem.structure_2d_depiction import render_molecule_png
    from mctoolkit.chem.structure_neutralize import neutralize_mol
    from mctoolkit.chem.molecule_conversion import mol_to_canonical_smiles

    blobs, w, h = args
    out = []
    for oid, blob in blobs:
        mol = Chem.Mol(blob)
        parent, fragments = largest_fragment_and_rest(mol)
        if parent is None:
            out.append((oid, None, "", "", None))
            continue
        neutral = neutralize_mol(parent) or parent
        png = render_molecule_png(neutral, w, h)
        out.append((oid, neutral.ToBinary(), fragments, mol_to_canonical_smiles(neutral), png))
    return out


def _render_only_batch(args):
    from rdkit import Chem

    from mctoolkit.chem.structure_2d_depiction import render_molecule_png

    blobs, w, h = args
    return [(oid, render_molecule_png(Chem.Mol(blob), w, h)) for oid, blob in blobs]


def _chem_only_batch(args):
    """Disconnect + neutralize + canonical SMILES for one batch (no rendering)."""
    from rdkit import Chem

    from mctoolkit.chem.fragment_disconnect import largest_fragment_and_rest
    from mctoolkit.chem.structure_neutralize import neutralize_mol
    from mctoolkit.chem.molecule_conversion import mol_to_canonical_smiles

    blobs = args[0]
    out = []
    for oid, blob in blobs:
        mol = Chem.Mol(blob)
        parent, fragments = largest_fragment_and_rest(mol)
        if parent is None:
            out.append((oid, None, "", ""))
            continue
        neutral = neutralize_mol(parent) or parent
        out.append((oid, neutral.ToBinary(), fragments, mol_to_canonical_smiles(neutral)))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--batch", type=int, default=48)
    args = ap.parse_args()

    from rdkit import Chem

    from mctoolkit.chem.fragment_disconnect import largest_fragment_and_rest
    from mctoolkit.chem.structure_neutralize import neutralize_mol
    from mctoolkit.chem.molecule_conversion import mol_to_canonical_smiles

    suppl = Chem.SDMolSupplier(args.path)
    mols = [m for m in suppl if m is not None]
    if args.limit:
        mols = mols[: args.limit]
    n = len(mols)
    w, h = STRUCTURE_DEPICT_WIDTH, STRUCTURE_DEPICT_HEIGHT
    workers = min(8, max(2, (os.cpu_count() or 4) - 1), 6)
    print(f"file={args.path} n={n} depict={w}x{h} pool_workers={workers} batch={args.batch}")
    print("=" * 68)

    # --- Current pipeline: serial chemistry on one thread, then parallel render.
    t0 = time.perf_counter()
    frags = [largest_fragment_and_rest(m) for m in mols]
    t_dis = time.perf_counter() - t0

    parents = [(i, p) for i, (p, _f) in enumerate(frags) if p is not None]
    t0 = time.perf_counter()
    neutral = [(i, neutralize_mol(p) or p) for i, p in parents]
    t_neu = time.perf_counter() - t0

    t0 = time.perf_counter()
    [mol_to_canonical_smiles(m) for _i, m in neutral]
    t_smi = time.perf_counter() - t0

    blobs = [(i, m.ToBinary()) for i, m in neutral]
    batches = [(blobs[s : s + args.batch], w, h) for s in range(0, len(blobs), args.batch)]

    t0 = time.perf_counter()
    ex = ProcessPoolExecutor(max_workers=workers)
    try:
        got = 0
        for res in ex.map(_render_only_batch, batches):
            got += len(res)
    finally:
        ex.shutdown()
    t_render = time.perf_counter() - t0

    current = t_dis + t_neu + t_smi + t_render
    print("CURRENT (3 serial stages)")
    print(f"  disconnect (serial 1 thread) : {t_dis:6.2f}s")
    print(f"  neutralize (serial 1 thread) : {t_neu:6.2f}s")
    print(f"  canonical SMILES (GUI thread): {t_smi:6.2f}s")
    print(f"  render 2D (pool + startup)   : {t_render:6.2f}s")
    print(f"  TOTAL                        : {current:6.2f}s")

    # --- Fused: one process-pool pass doing all three stages per molecule.
    in_blobs = [(i, m.ToBinary()) for i, m in enumerate(mols)]
    fused_batches = [
        (in_blobs[s : s + args.batch], w, h) for s in range(0, len(in_blobs), args.batch)
    ]
    t0 = time.perf_counter()
    ex = ProcessPoolExecutor(max_workers=workers)
    try:
        got = 0
        for res in ex.map(_fused_batch, fused_batches):
            got += len(res)
    finally:
        ex.shutdown()
    t_fused = time.perf_counter() - t0

    print("FUSED-ALL (1 pool pass: disconnect+neutralize+render)")
    print(f"  TOTAL                        : {t_fused:6.2f}s   rows={got}")

    # --- Middle option: chemistry parallelized in a pool, render left on the existing pool.
    chem_batches = [(in_blobs[s : s + args.batch],) for s in range(0, len(in_blobs), args.batch)]
    t0 = time.perf_counter()
    ex = ProcessPoolExecutor(max_workers=workers)
    chem_out = []
    try:
        for res in ex.map(_chem_only_batch, chem_batches):
            chem_out.extend(res)
    finally:
        ex.shutdown()
    t_chem_pool = time.perf_counter() - t0

    rb = [(oid, blob) for oid, blob, _f, _s in chem_out if blob]
    render_batches = [(rb[s : s + args.batch], w, h) for s in range(0, len(rb), args.batch)]
    t0 = time.perf_counter()
    ex = ProcessPoolExecutor(max_workers=workers)
    try:
        for _res in ex.map(_render_only_batch, render_batches):
            pass
    finally:
        ex.shutdown()
    t_chem_pool_render = time.perf_counter() - t0
    middle = t_chem_pool + t_chem_pool_render

    print("CHEM-IN-POOL (chemistry pooled, existing render pipeline untouched)")
    print(f"  chemistry (pool)             : {t_chem_pool:6.2f}s")
    print(f"  render 2D (pool + startup)   : {t_chem_pool_render:6.2f}s")
    print(f"  TOTAL                        : {middle:6.2f}s")
    print("=" * 68)
    if t_fused > 0:
        print(
            f"fused-all    vs current: {current / t_fused:.2f}x  (saves {current - t_fused:.2f}s)"
        )
    if middle > 0:
        print(f"chem-in-pool vs current: {current / middle:.2f}x  (saves {current - middle:.2f}s)")
        print(f"fused-all buys a further {middle - t_fused:.2f}s over chem-in-pool")


if __name__ == "__main__":
    main()
