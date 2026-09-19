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

from __future__ import annotations

from molmanager.platform_support.performance_tracking import PerformanceTracker


def test_performance_tracker_snapshot_and_counts():
    tr = PerformanceTracker(enabled=True, log_every=999, window_size=64)
    for i in range(1, 21):
        tr.record("load_rows", float(i))
    snap = tr.snapshot("load_rows")
    assert snap is not None
    assert snap.count == 20
    assert snap.max_ms == 20.0
    assert snap.p50_ms >= 10.0
    assert snap.p95_ms >= snap.p50_ms
