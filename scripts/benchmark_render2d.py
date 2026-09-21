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
# along with mctoolkit.  If not, see <https://www.gnu.org/licenses/>.

"""Measure 2D render throughput: worker count vs task batch size.

The table render currently submits one molecule per process-pool task and emits one Qt signal per
molecule. This compares that against batched tasks and higher worker counts.

Usage:
    python scripts/benchmark_render2d.py samples/binding_db_pubchem_25k.sdf [--limit N]
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mctoolkit.table.structure_depiction_layout import (  # noqa: E402
    STRUCTURE_DEPICT_HEIGHT,
    STRUCTURE_DEPICT_WIDTH,
)


def _one(args: tuple):
    """Current shape: one molecule per task."""
    from rdkit import Chem

    from mctoolkit.chem.structure_2d_depiction import render_molecule_png

    oid, blob, w, h = args
    if not blob:
        return oid, b"", False, w, h
    try:
        return oid, render_molecule_png(Chem.Mol(blob), w, h), True, w, h
    except Exception:
        return oid, b"", False, w, h


def _batch(args: tuple):
    """Batched shape: many molecules per task."""
    from rdkit import Chem

    from mctoolkit.chem.structure_2d_depiction import render_molecule_png

    items, w, h = args
    out = []
    for oid, blob in items:
        if not blob:
            out.append((oid, b"", False, w, h))
            continue
        try:
            out.append((oid, render_molecule_png(Chem.Mol(blob), w, h), True, w, h))
        except Exception:
            out.append((oid, b"", False, w, h))
    return out


def _run(blobs, w, h, *, workers: int, batch: int) -> tuple[float, int]:
    if batch <= 1:
        tasks = [(oid, b, w, h) for oid, b in blobs]
        fn = _one
    else:
        tasks = [
            ([(oid, b) for oid, b in blobs[s : s + batch]], w, h)
            for s in range(0, len(blobs), batch)
        ]
        fn = _batch
    max_inflight = min(48, max(workers * 4, workers))
    it = iter(tasks)
    pending: set = set()
    got = 0
    nbytes = 0
    t0 = time.perf_counter()
    ex = ProcessPoolExecutor(max_workers=workers)

    def _fill():
        while len(pending) < max_inflight:
            nxt = next(it, None)
            if nxt is None:
                break
            pending.add(ex.submit(fn, nxt))

    try:
        _fill()
        while pending:
            done, pending = wait(pending, timeout=0.2, return_when=FIRST_COMPLETED)
            for f in done:
                res = f.result()
                rows = res if batch > 1 else [res]
                for _oid, png, _ok, _rw, _rh in rows:
                    got += 1
                    nbytes += len(png)
            _fill()
    finally:
        ex.shutdown()
    return time.perf_counter() - t0, got


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--limit", type=int, default=8000)
    args = ap.parse_args()

    from rdkit import Chem

    suppl = Chem.SDMolSupplier(args.path)
    mols = []
    for m in suppl:
        if m is not None:
            mols.append(m)
        if args.limit and len(mols) >= args.limit:
            break
    blobs = [(i, m.ToBinary()) for i, m in enumerate(mols)]
    w, h = STRUCTURE_DEPICT_WIDTH, STRUCTURE_DEPICT_HEIGHT
    ncpu = os.cpu_count() or 4
    current_workers = min(8, max(2, ncpu - 1), 6)
    print(f"n={len(blobs)} depict={w}x{h} cpu_count={ncpu} current_worker_cap={current_workers}")
    print("=" * 74)
    print(f"{'workers':>8} {'batch':>6} {'wall_s':>8} {'mol/s':>9}  note")

    combos = [
        (current_workers, 1, "current"),
        (6, 64, ""),
        (8, 64, ""),
        (10, 64, ""),
        (11, 64, ""),
        (11, 128, ""),
    ]
    seen = set()
    best = None
    for workers, batch, note in combos:
        key = (workers, batch)
        if workers < 1 or key in seen:
            continue
        seen.add(key)
        dt, got = _run(blobs, w, h, workers=workers, batch=batch)
        rate = got / dt if dt else 0.0
        print(f"{workers:>8} {batch:>6} {dt:>8.2f} {rate:>9.0f}  {note}")
        if best is None or dt < best[0]:
            best = (dt, workers, batch)
    if best:
        print("=" * 74)
        print(f"fastest: workers={best[1]} batch={best[2]} at {best[0]:.2f}s")


if __name__ == "__main__":
    main()
