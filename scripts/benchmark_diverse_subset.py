#!/usr/bin/env python3
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

"""Lightweight timing for Diverse Subset MaxMin (exact vs fast, warm vs cold cache).

Example:
  python scripts/benchmark_diverse_subset.py --n 2000 --k 50 --candidate-cap 500
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from rdkit import Chem
from rdkit.Chem import AllChem

from mctoolkit.chem.fingerprint_cache import clear as clear_fp_cache
from mctoolkit.workers.diverse_subset_worker import (
    DiverseSubsetPoolRow,
    run_diverse_subset_pick,
)


def _pool(n: int) -> list[DiverseSubsetPoolRow]:
    # Deterministic pseudo-diverse SMILES via carbon-chain / phenyl variants.
    rows: list[DiverseSubsetPoolRow] = []
    for i in range(n):
        if i % 5 == 0:
            smi = "c1ccccc1" + "C" * (i % 7)
        elif i % 5 == 1:
            smi = "C" * (2 + (i % 12)) + "O"
        elif i % 5 == 2:
            smi = "CC(=O)O" + "C" * (i % 5)
        elif i % 5 == 3:
            smi = "c1ccncc1" + "C" * (i % 4)
        else:
            smi = "C" * (1 + (i % 10)) + "N"
        mol = Chem.MolFromSmiles(smi)
        if mol is None:
            mol = Chem.MolFromSmiles("CCO")
        assert mol is not None
        AllChem.GetMorganFingerprintAsBitVect(mol, 2, 2048)  # warm RDKit path
        rows.append(DiverseSubsetPoolRow(oid=i, mol=mol, fp=None))
    return rows


def _time_pick(pool: list[DiverseSubsetPoolRow], k: int, mode: str, candidate_cap: int) -> float:
    t0 = time.perf_counter()
    picks, n_cached, n_computed = run_diverse_subset_pick(
        pool,
        "Morgan (r=2, n=2048)",
        k,
        "FP_Morgan_2_2048",
        mode=mode,
        candidate_cap=candidate_cap,
        use_process_pool=False,
    )
    dt = time.perf_counter() - t0
    print(
        f"  mode={mode:5s}  picks={len(picks):4d}  "
        f"cache={n_cached:5d}  computed={n_computed:5d}  {dt:7.3f}s"
    )
    return dt


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--n", type=int, default=2000, help="Pool size")
    ap.add_argument("--k", type=int, default=50, help="Subset size")
    ap.add_argument("--candidate-cap", type=int, default=500, help="Fast-mode candidate pool")
    args = ap.parse_args()
    n = max(10, int(args.n))
    k = max(1, min(int(args.k), n))
    cap = max(k, int(args.candidate_cap))

    print(f"Building pool n={n}, k={k}, candidate_cap={cap}")
    pool = _pool(n)

    print("Cold cache:")
    clear_fp_cache()
    for row in pool:
        row.fp = None
    _time_pick(pool, k, "exact", cap)
    clear_fp_cache()
    for row in pool:
        row.fp = None
    _time_pick(pool, k, "fast", cap)

    print("Warm cache (exact then fast):")
    # Warm via exact
    clear_fp_cache()
    for row in pool:
        row.fp = None
    _time_pick(pool, k, "exact", cap)
    # Reattach cache hits
    from mctoolkit.chem.fingerprint_cache import get as cache_get

    for row in pool:
        row.fp = cache_get(row.oid, "FP_Morgan_2_2048")
    _time_pick(pool, k, "exact", cap)
    _time_pick(pool, k, "fast", cap)


if __name__ == "__main__":
    main()
