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

"""Measure Uni-pKa pKa/protonate cost and how much is our wrapper vs the model.

Breaks a unique-structure batch into:
  enumerate   MolGpKa SMARTS ensembles (MCToolkit)
  mmff_lmdb   Uni-pKa 11-conformer MMFF + LMDB write (unipkainfer)
  infer       Uni-Mol free-energy forward pass (unipkainfer)
  other       pickle, calibration, LMDB teardown, Python

Also compares in-process chunk sizes (1 = old CUDA path, 16 = current) so we
can tell whether batching is a win on this machine.

Usage:
    python scripts/benchmark_pka.py samples/fda_approved_physprops.sdf
    python scripts/benchmark_pka.py samples/fda_approved_physprops.sdf --limit 32
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from collections.abc import Sequence
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _load_mols(path: Path, limit: int) -> list:
    from rdkit import Chem

    from mctoolkit.workers.structure_grouping import structure_key

    suffix = path.suffix.lower()
    mols: list = []
    if suffix == ".sdf":
        suppl = Chem.SDMolSupplier(str(path), removeHs=False, sanitize=True)
        raw = [m for m in suppl if m is not None]
    elif suffix in {".smi", ".smiles"}:
        raw = []
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                smi = line.split()[0].strip() if line.strip() else ""
                if not smi:
                    continue
                mol = Chem.MolFromSmiles(smi)
                if mol is not None:
                    raw.append(mol)
    else:
        raise SystemExit(f"Unsupported input (use .sdf or .smi): {path}")

    seen: set[str] = set()
    for mol in raw:
        key = structure_key(mol)
        if key in seen:
            continue
        seen.add(key)
        mols.append(mol)
        if limit and len(mols) >= limit:
            break
    return mols


@contextmanager
def _trace_unipka():
    """Time Uni-pKa MMFF/LMDB preprocess vs the neural-net forward pass."""
    import unipkainfer.pka_predictor.free_energy as fe

    acc = {"mmff_lmdb": 0.0, "infer": 0.0, "infer_calls": 0}
    orig_write = fe._write_free_energy_lmdb
    orig_predict = fe._FreeEnergyFoldRunner.predict

    def _write(*args, **kwargs):
        t0 = time.perf_counter()
        try:
            return orig_write(*args, **kwargs)
        finally:
            acc["mmff_lmdb"] += time.perf_counter() - t0

    def _predict(self, *args, **kwargs):
        t0 = time.perf_counter()
        try:
            return orig_predict(self, *args, **kwargs)
        finally:
            acc["infer"] += time.perf_counter() - t0
            acc["infer_calls"] += 1

    fe._write_free_energy_lmdb = _write
    fe._FreeEnergyFoldRunner.predict = _predict
    try:
        yield acc
    finally:
        fe._write_free_energy_lmdb = orig_write
        fe._FreeEnergyFoldRunner.predict = orig_predict


def _chunks(items: Sequence, size: int) -> list:
    n = max(1, int(size))
    return [list(items[i : i + n]) for i in range(0, len(items), n)]


def _pct(part: float, total: float) -> str:
    if total <= 0:
        return "  n/a"
    return f"{100.0 * part / total:5.1f}%"


def _print_row(label: str, seconds: float, n: int, total: float | None = None) -> None:
    rate = (1000.0 * seconds / n) if n else 0.0
    extra = f"  {_pct(seconds, total)}" if total is not None else ""
    print(f"  {label:16s} {seconds:7.2f}s  {rate:7.1f} ms/mol{extra}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("path", type=Path, help="SDF or SMILES file")
    ap.add_argument("--limit", type=int, default=32, help="Unique structures (0 = all)")
    ap.add_argument(
        "--chunks",
        default="1,8,16",
        help="Comma-separated in-process batch sizes to compare",
    )
    args = ap.parse_args()
    chunk_sizes = [max(1, int(x)) for x in str(args.chunks).split(",") if x.strip()]

    from mctoolkit.ionization.unipka_ensembles import (
        pin_unipka_torch_threads,
        predict_ionization_ensembles,
        prepare_mol_for_ionization,
        score_microstate_free_energies,
        unipka_import_error,
        unipka_use_gpu,
        warn_if_cuda_torch_missing,
    )
    from mctoolkit.ionization.unipka_enumerator import (
        enumerate_charge_ensemble,
        flatten_charge_ensemble,
    )
    from mctoolkit.chem.molecule_conversion import mol_to_canonical_smiles
    from mctoolkit.workers.ionization_parallel import (
        UNIPKA_STRUCTURE_CHUNK,
        UNIPKA_STRUCTURE_CHUNK_SERIAL,
    )

    err = unipka_import_error()
    if err:
        raise SystemExit(err)
    warn_if_cuda_torch_missing()
    pin_unipka_torch_threads()

    mols = _load_mols(args.path, args.limit)
    if not mols:
        raise SystemExit(f"No molecules loaded from {args.path}")

    n = len(mols)
    gpu = unipka_use_gpu()
    print(f"file={args.path} unique={n} gpu={gpu}")
    print(
        f"app chunks: serial/CUDA={UNIPKA_STRUCTURE_CHUNK_SERIAL} cpu-pool={UNIPKA_STRUCTURE_CHUNK}"
    )
    print("=" * 68)

    print("WARMUP (fold load, excluded from later rows)")
    t0 = time.perf_counter()
    predict_ionization_ensembles(mols[:1])
    print(f"  first structure          {time.perf_counter() - t0:7.2f}s")
    print()

    def _microstate_mols(mol):
        safe = prepare_mol_for_ionization(mol)
        if safe is None:
            return []
        smi = mol_to_canonical_smiles(safe)
        if not smi:
            return []
        flat = flatten_charge_ensemble(enumerate_charge_ensemble(smi))
        if not flat:
            return [safe]
        return [row[2] for row in flat]

    print("PHASE BREAKDOWN (one in-process call, all unique mols)")
    t_enum0 = time.perf_counter()
    flats = [_microstate_mols(mol) for mol in mols]
    t_enum = time.perf_counter() - t_enum0
    score_mols = [ms for flat in flats for ms in flat]
    n_ms = len(score_mols)
    with _trace_unipka() as acc:
        t_score0 = time.perf_counter()
        energies = score_microstate_free_energies(score_mols)
        t_score = time.perf_counter() - t_score0
    if len(energies) != n_ms:
        raise SystemExit(f"scorer returned {len(energies)} rows, expected {n_ms}")
    t_other = max(0.0, t_score - acc["mmff_lmdb"] - acc["infer"])
    t_phase = t_enum + t_score
    print(f"  microstates scored     {n_ms:5d}  ({n_ms / max(n, 1):.2f} / mol)")
    _print_row("enumerate", t_enum, n, t_phase)
    _print_row("mmff+lmdb", acc["mmff_lmdb"], n, t_phase)
    _print_row("unimol infer", acc["infer"], n, t_phase)
    _print_row("other/wrap", t_other, n, t_phase)
    _print_row("TOTAL", t_phase, n)
    unipka = acc["mmff_lmdb"] + acc["infer"]
    print(
        f"  Uni-pKa share (mmff+lmdb+infer): {_pct(unipka, t_phase).strip()}  "
        f"wrapper+enumerate: {_pct(t_enum + t_other, t_phase).strip()}"
    )
    print()

    print("CHUNK SIZE (in-process predict_ionization_ensembles, model already warm)")
    print("  chunk=1 is the old CUDA job shape; 16 is the current 1-worker default.")
    baseline: float | None = None
    for size in chunk_sizes:
        t0 = time.perf_counter()
        for group in _chunks(mols, size):
            predict_ionization_ensembles(group)
        elapsed = time.perf_counter() - t0
        if baseline is None:
            baseline = elapsed
        vs = f"  {baseline / elapsed:.2f}x vs chunk=1" if baseline and elapsed else ""
        n_calls = (n + size - 1) // size
        print(
            f"  chunk={size:<3d}  {elapsed:7.2f}s  {1000.0 * elapsed / n:7.1f} ms/mol  "
            f"calls={n_calls}{vs}"
        )
    print("=" * 68)
    print("If mmff+lmdb + unimol infer are ~90%+ of TOTAL, Uni-pKa is the limiter.")
    print("chunk=1 slower than 8/16 means the old CUDA progress split was costing us.")


if __name__ == "__main__":
    main()
