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

from __future__ import annotations

from rdkit import Chem

from mctoolkit.workers.cluster_worker import ClusterWorker
from mctoolkit.workers.signals import WorkerSignals


class _StepCancel:
    def __init__(self, trigger_at: int):
        self._calls = 0
        self._trigger_at = max(1, int(trigger_at))

    def is_set(self) -> bool:
        self._calls += 1
        return self._calls >= self._trigger_at


def test_cluster_worker_emits_partial_rows_on_cancel():
    sigs = WorkerSignals()
    out: dict[str, object] = {}
    sigs.calculated.connect(lambda rows, headers: out.update({"rows": rows, "headers": headers}))
    sigs.cluster_failed.connect(lambda msg: out.update({"failed": msg}))

    rows = [
        (1, Chem.MolFromSmiles("CCO")),
        (2, Chem.MolFromSmiles("CCN")),
        (3, Chem.MolFromSmiles("CCC")),
        (4, Chem.MolFromSmiles("CCCl")),
    ]
    worker = ClusterWorker(
        rows=rows,
        fp_choice="Morgan (r=2, n=1024)",
        method="kmeans",
        params={"n_clusters": 2},
        column_name="Cluster",
        signals=sigs,
        cancel_event=_StepCancel(trigger_at=3),
    )
    worker.run()

    assert out.get("failed") == "Cancelled."
    got_rows = out.get("rows")
    assert isinstance(got_rows, list)
    assert len(got_rows) >= 1
    assert out.get("headers") == ["Cluster"]
