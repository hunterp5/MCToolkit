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
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with MolManager.  If not, see <https://www.gnu.org/licenses/>.

"""Micro-benchmark key table operations at 10k/50k/100k rows."""

from __future__ import annotations

import argparse
import statistics
import sys
import time
from pathlib import Path

from PySide6.QtWidgets import QApplication

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from molmanager.ui.compound_table_model import CompoundTableModel


def _build_rows(n_rows: int) -> list[tuple[int, dict[str, str]]]:
    rows: list[tuple[int, dict[str, str]]] = []
    for i in range(n_rows):
        rows.append(
            (
                i,
                {
                    "SMILES": "CCO",
                    "Name": f"cmpd_{i}",
                    "MW": str(100.0 + (i % 200) * 0.1),
                    "Score": str((i * 7) % 1000),
                },
            )
        )
    return rows


def _run_once(n_rows: int) -> dict[str, float]:
    model = CompoundTableModel(["ID_HIDDEN", "Structure", "SMILES", "Name", "MW", "Score"])
    rows = _build_rows(n_rows)

    t0 = time.perf_counter()
    model.append_rows_batch(rows)
    ingest_ms = (time.perf_counter() - t0) * 1000.0

    t0 = time.perf_counter()
    _ = model.numeric_bounds_by_column()
    bounds_ms = (time.perf_counter() - t0) * 1000.0

    t0 = time.perf_counter()
    model.sort(5)
    sort_ms = (time.perf_counter() - t0) * 1000.0

    return {
        "ingest_ms": ingest_ms,
        "bounds_ms": bounds_ms,
        "sort_ms": sort_ms,
    }


def run_benchmark(scales: list[int], runs: int) -> None:
    _app = QApplication.instance() or QApplication([])
    for n in scales:
        samples = [_run_once(n) for _ in range(runs)]
        print(f"\nRows: {n:,}")
        for key in ("ingest_ms", "bounds_ms", "sort_ms"):
            vals = [s[key] for s in samples]
            p50 = statistics.median(vals)
            p95 = sorted(vals)[min(len(vals) - 1, int(round((len(vals) - 1) * 0.95)))]
            avg = statistics.fmean(vals)
            print(f"  {key:10s} avg={avg:8.1f}  p50={p50:8.1f}  p95={p95:8.1f}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark large-table core operations.")
    parser.add_argument("--runs", type=int, default=3, help="Runs per scale (default: 3)")
    parser.add_argument(
        "--scales",
        type=str,
        default="10000,50000,100000",
        help="Comma-separated row counts (default: 10000,50000,100000)",
    )
    args = parser.parse_args()
    scales = [max(100, int(x.strip())) for x in (args.scales or "").split(",") if x.strip()]
    run_benchmark(scales, max(1, int(args.runs)))


if __name__ == "__main__":
    main()
