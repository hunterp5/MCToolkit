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

"""CI performance gate for core table operations."""

from __future__ import annotations

import statistics
import sys
import time
from pathlib import Path

from PySide6.QtWidgets import QApplication

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mctoolkit.ui.compound_table_model import CompoundTableModel
from mctoolkit.ui.filter_proxy_model import FilterProxyModel


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

    proxy = FilterProxyModel()
    proxy.setSourceModel(model)
    visible = frozenset(i for i in range(n_rows) if i % 2 == 0)
    t0 = time.perf_counter()
    proxy.set_visible_oids(visible)
    filter_ms = (time.perf_counter() - t0) * 1000.0

    return {
        "ingest_ms": ingest_ms,
        "bounds_ms": bounds_ms,
        "sort_ms": sort_ms,
        "filter_ms": filter_ms,
    }


def main() -> int:
    _app = QApplication.instance() or QApplication([])
    scale = 100_000
    runs = 2
    samples = [_run_once(scale) for _ in range(runs)]
    keys = ("ingest_ms", "bounds_ms", "sort_ms", "filter_ms")
    p95 = {
        key: sorted(s[key] for s in samples)[min(runs - 1, int(round((runs - 1) * 0.95)))]
        for key in keys
    }
    avg = {key: statistics.fmean(s[key] for s in samples) for key in keys}
    print("perf_gate 100k " + " ".join(f"{k}:avg={avg[k]:.1f}ms,p95={p95[k]:.1f}ms" for k in keys))

    # Generous CI thresholds to catch major regressions while avoiding runner flakiness.
    # filter_ms is an explicit row-map rebuild (not invalidateFilter); keep headroom for
    # slow CI hosts but far below the historical multi-second SortFilter walk budget.
    limits = {
        "ingest_ms": 8000.0,
        "bounds_ms": 8000.0,
        "sort_ms": 4000.0,
        "filter_ms": 2000.0,
    }
    failed = [k for k, lim in limits.items() if p95[k] > lim]
    if failed:
        print(
            "Performance gate failed: "
            + ", ".join(f"{k} p95={p95[k]:.1f}ms > {limits[k]:.1f}ms" for k in failed),
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
