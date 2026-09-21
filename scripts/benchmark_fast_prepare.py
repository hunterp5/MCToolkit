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
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with mctoolkit. If not, see <https://www.gnu.org/licenses/>.

"""Time the production Fast Prepare path against a fused chemistry+PNG child pass.

Production today: process-pool chemistry (disconnect, optional neutralize), shut the pool
down, spawn a second Render 2D pool, re-hydrate each prepared blob, draw PNG.

Usage:
    python scripts/benchmark_fast_prepare.py samples/fda_approved_physprops.sdf [--limit N]
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
from mctoolkit.workers.load_render import render2d_process_worker_count  # noqa: E402


def _chem_batch(args):
    """Two-pool chemistry child: disconnect + optional neutralize, no PNG."""
    from rdkit import Chem

    from mctoolkit.chem.fragment_disconnect import largest_fragment_and_rest
    from mctoolkit.chem.structure_neutralize import neutralize_mol

    items, neutralize = args
    out = []
    for oid, blob, source_text in items:
        mol = Chem.Mol(blob) if blob else None
        if mol is None:
            continue
        parent, fragments = largest_fragment_and_rest(mol, source_text)
        if parent is None:
            continue
        prepared = neutralize_mol(parent) or parent if neutralize else parent
        out.append((int(oid), prepared.ToBinary(), fragments))
    return out


def _render_batch(args):
    from mctoolkit.workers.load_render import _mp_render_structure_batch

    return _mp_render_structure_batch(args)


def _fused_batch(args):
    """Disconnect + optional neutralize + PNG in one child, one hydrate."""
    from rdkit import Chem

    from mctoolkit.chem.fragment_disconnect import largest_fragment_and_rest
    from mctoolkit.chem.structure_2d_depiction import render_molecule_png
    from mctoolkit.chem.structure_neutralize import neutralize_mol

    items, neutralize, w, h = args
    out = []
    for oid, blob, source_text in items:
        mol = Chem.Mol(blob) if blob else None
        if mol is None:
            continue
        parent, fragments = largest_fragment_and_rest(mol, source_text)
        if parent is None:
            continue
        prepared = parent
        if neutralize:
            prepared = neutralize_mol(parent) or parent
        try:
            png = render_molecule_png(prepared, w, h) or b""
        except Exception:  # noqa: BLE001
            png = b""
        out.append((int(oid), prepared.ToBinary(), fragments, png))
    return out


def _shipped_fused_batch(args):
    """The Fast Prepare child batch that ships: chemistry + PNG in one hydrate."""
    from mctoolkit.workers.fast_prepare import _mp_fast_prepare_batch

    items, neutralize, w, h = args
    return _mp_fast_prepare_batch((items, False, False, neutralize, True, w, h))


def _micro_uncharger(args):
    from rdkit import Chem

    from mctoolkit.chem.structure_neutralize import neutralize_mol

    blobs, skip_zero = args
    n = 0
    for blob in blobs:
        mol = Chem.Mol(blob)
        if mol is None:
            continue
        if skip_zero and Chem.GetFormalCharge(mol) == 0:
            n += 1
            continue
        neutralize_mol(mol)
        n += 1
    return n


def _micro_frags(args):
    from rdkit import Chem

    blobs, sanitize = args
    n = 0
    for blob in blobs:
        mol = Chem.Mol(blob)
        if mol is None:
            continue
        list(Chem.GetMolFrags(mol, asMols=True, sanitizeFrags=sanitize))
        n += 1
    return n


def _chunk(items, size):
    return [items[s : s + size] for s in range(0, len(items), size)]


def _pool_map(fn, batches, workers):
    ex = ProcessPoolExecutor(max_workers=workers)
    try:
        got = 0
        for res in ex.map(fn, batches):
            got += len(res) if isinstance(res, list) else int(res or 0)
        return got
    finally:
        ex.shutdown(wait=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--batch", type=int, default=64)
    ap.add_argument("--neutralize", action="store_true")
    args = ap.parse_args()

    from rdkit import Chem

    suppl = Chem.SDMolSupplier(args.path, sanitize=True, removeHs=False)
    mols = [m for m in suppl if m is not None]
    if args.limit:
        mols = mols[: args.limit]
    n = len(mols)
    w, h = STRUCTURE_DEPICT_WIDTH, STRUCTURE_DEPICT_HEIGHT
    chem_workers = min(8, max(2, (os.cpu_count() or 4) - 1), 6)
    render_workers = render2d_process_worker_count()
    batch = max(1, int(args.batch))
    neutralize = bool(args.neutralize)
    print(
        f"file={args.path} n={n} depict={w}x{h} chem_workers={chem_workers} "
        f"render_workers={render_workers} batch={batch} neutralize={neutralize}"
    )
    print("=" * 72)

    t0 = time.perf_counter()
    items = [
        (i, m.ToBinary(), Chem.MolToSmiles(m) if m is not None else "") for i, m in enumerate(mols)
    ]
    t_snap = time.perf_counter() - t0
    print(f"blob snapshot (ToBinary, no store) : {t_snap:6.2f}s")

    item_batches = _chunk(items, batch)
    chem_batches = [(b, neutralize) for b in item_batches]

    t0 = time.perf_counter()
    chem_got = _pool_map(_chem_batch, chem_batches, chem_workers)
    t_chem = time.perf_counter() - t0
    print(f"chemistry pool (production chem)   : {t_chem:6.2f}s   rows={chem_got}")

    t0 = time.perf_counter()
    ex = ProcessPoolExecutor(max_workers=render_workers)
    # First submit forces Windows spawn + RDKit import in children.
    spawn_fut = ex.submit(_render_batch, ([], w, h))
    spawn_fut.result()
    t_spawn = time.perf_counter() - t0
    print(f"second pool spawn + RDKit import   : {t_spawn:6.2f}s")

    # Re-run chemistry once so render has prepared blobs (not counted in two-pool total;
    # production would already have them). Use the chem output from the timed pass.
    prepared = []
    for batch_args in chem_batches:
        prepared.extend(_chem_batch(batch_args))
    render_items = [(int(oid), blob) for oid, blob, _frag in prepared if blob]
    render_batches = [(rb, w, h) for rb in _chunk(render_items, batch)]

    t0 = time.perf_counter()
    try:
        render_got = 0
        for res in ex.map(_render_batch, render_batches):
            render_got += len(res)
    finally:
        ex.shutdown(wait=True)
    t_render = time.perf_counter() - t0
    print(f"render 2D pool (rehydrate + PNG)   : {t_render:6.2f}s   rows={render_got}")

    two_pool = t_chem + t_spawn + t_render
    print(f"PRODUCTION two-pool TOTAL          : {two_pool:6.2f}s")
    print("-" * 72)

    fused_batches = [(b, neutralize, w, h) for b in item_batches]
    t0 = time.perf_counter()
    fused_got = _pool_map(_fused_batch, fused_batches, render_workers)
    t_fused = time.perf_counter() - t0
    print(f"FUSED chem+PNG one pool            : {t_fused:6.2f}s   rows={fused_got}")
    if t_fused > 0:
        print(
            f"fused vs two-pool                  : {two_pool / t_fused:.2f}x  "
            f"(saves {two_pool - t_fused:.2f}s)"
        )
    t0 = time.perf_counter()
    shipped_got = _pool_map(_shipped_fused_batch, fused_batches, render_workers)
    t_shipped = time.perf_counter() - t0
    print(f"SHIPPED _mp_fast_prepare_batch PNG : {t_shipped:6.2f}s   rows={shipped_got}")
    print("-" * 72)

    micro_blobs = [blob for _i, blob, _s in items[: min(len(items), 800)]]
    micro_batches = [(mb, False) for mb in _chunk(micro_blobs, batch)]
    t0 = time.perf_counter()
    _pool_map(_micro_uncharger, micro_batches, chem_workers)
    t_uncharge_all = time.perf_counter() - t0
    t0 = time.perf_counter()
    _pool_map(_micro_uncharger, [(mb, True) for mb, _ in micro_batches], chem_workers)
    t_uncharge_skip = time.perf_counter() - t0
    print(
        f"micro Uncharger all vs skip-zero   : {t_uncharge_all:6.2f}s vs {t_uncharge_skip:6.2f}s  "
        f"n={len(micro_blobs)}"
    )

    t0 = time.perf_counter()
    _pool_map(_micro_frags, [(mb, True) for mb, _ in micro_batches], chem_workers)
    t_frag_s = time.perf_counter() - t0
    t0 = time.perf_counter()
    _pool_map(_micro_frags, [(mb, False) for mb, _ in micro_batches], chem_workers)
    t_frag_ns = time.perf_counter() - t0
    print(
        f"micro GetMolFrags sanitize vs not  : {t_frag_s:6.2f}s vs {t_frag_ns:6.2f}s  "
        f"n={len(micro_blobs)}"
    )
    print("=" * 72)
    uncharge_delta = t_uncharge_all - t_uncharge_skip
    frags_delta = t_frag_s - t_frag_ns
    print(
        f"chem fast-path needle: uncharge skip {uncharge_delta:.2f}s, "
        f"sanitizeFrags {frags_delta:.2f}s (on {len(micro_blobs)} mols)"
    )


if __name__ == "__main__":
    main()
