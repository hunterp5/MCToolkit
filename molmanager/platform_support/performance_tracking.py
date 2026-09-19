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

"""Lightweight runtime performance tracking for large-table workflows."""

from __future__ import annotations

import logging
import statistics
import time
from collections import defaultdict, deque
from contextlib import contextmanager
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class PerfSnapshot:
    count: int
    avg_ms: float
    p50_ms: float
    p95_ms: float
    max_ms: float


class PerformanceTracker:
    """Collect rolling latency metrics for named operations."""

    def __init__(self, *, enabled: bool, log_every: int, window_size: int = 256) -> None:
        self.enabled = bool(enabled)
        self.log_every = max(1, int(log_every))
        self.window_size = max(32, int(window_size))
        self._samples: dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=self.window_size))
        self._counts: dict[str, int] = defaultdict(int)
        self._totals_ms: dict[str, float] = defaultdict(float)

    @contextmanager
    def track(self, name: str):
        """Context manager to time an operation by metric name."""
        if not self.enabled:
            yield
            return
        t0 = time.perf_counter()
        try:
            yield
        finally:
            dt_ms = (time.perf_counter() - t0) * 1000.0
            self.record(name, dt_ms)

    def record(self, name: str, elapsed_ms: float) -> None:
        """Record a single duration sample in milliseconds."""
        if not self.enabled:
            return
        metric = str(name or "").strip()
        if not metric:
            return
        ms = max(0.0, float(elapsed_ms))
        self._samples[metric].append(ms)
        self._counts[metric] += 1
        self._totals_ms[metric] += ms
        if self._counts[metric] % self.log_every == 0:
            snap = self.snapshot(metric)
            if snap is not None:
                logger.info(
                    "perf[%s]: n=%d avg=%.1fms p50=%.1fms p95=%.1fms max=%.1fms",
                    metric,
                    snap.count,
                    snap.avg_ms,
                    snap.p50_ms,
                    snap.p95_ms,
                    snap.max_ms,
                )

    def snapshot(self, name: str) -> PerfSnapshot | None:
        metric = str(name or "").strip()
        if not metric:
            return None
        vals = list(self._samples.get(metric) or [])
        count = int(self._counts.get(metric, 0))
        if not vals or count <= 0:
            return None
        p50 = statistics.median(vals)
        if len(vals) >= 20:
            vals_sorted = sorted(vals)
            p95 = vals_sorted[min(len(vals_sorted) - 1, int(round((len(vals_sorted) - 1) * 0.95)))]
        else:
            p95 = max(vals)
        avg = float(self._totals_ms.get(metric, 0.0)) / max(1, count)
        return PerfSnapshot(
            count=count,
            avg_ms=avg,
            p50_ms=float(p50),
            p95_ms=float(p95),
            max_ms=float(max(vals)),
        )
