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

"""Bulk within-selection fingerprint similarity summaries."""

from __future__ import annotations

import heapq
import logging
import threading
import time
from dataclasses import dataclass

from PySide6.QtCore import QRunnable
from rdkit import Chem, DataStructs

from ..platform_support.tool_progress import ToolProgressState, report_tool_progress
from ..chem.rdkit_fingerprints import fingerprint_bitvect_for_row, fingerprint_bitvect_for_ui_choice
from .fingerprint_similarity import SIMILARITY_METRIC_LABELS, pairwise_fingerprint_similarity
from .signals import BulkSimilaritySignals

logger = logging.getLogger(__name__)

_PROGRESS_LABEL = "Bulk similarity"


@dataclass(frozen=True)
class BulkSimilarityResult:
    n_rows: int
    n_pairs: int
    mean_similarity: float | None
    min_similarity: float | None
    max_similarity: float | None
    most_similar_pairs: list[tuple[int, int, float]]
    least_similar_pairs: list[tuple[int, int, float]]


class BulkSimilarityWorker(QRunnable):
    """Compute pairwise fingerprint similarities among selected rows."""

    def __init__(
        self,
        rows: list[tuple[int, Chem.Mol]],
        fp_choice: str,
        metric: str,
        *,
        top_k_pairs: int,
        signals: BulkSimilaritySignals,
        cancel_event: threading.Event | None = None,
        progress_state: ToolProgressState | None = None,
    ) -> None:
        super().__init__()
        self.rows = rows
        self.fp_choice = fp_choice
        self.metric = metric if metric in SIMILARITY_METRIC_LABELS else "Tanimoto"
        self.top_k_pairs = max(10, int(top_k_pairs))
        self.signals = signals
        self.cancel_event = cancel_event
        self.progress_state = progress_state

    def _report(self, done: int, total: int, *, force: bool = False) -> None:
        report_tool_progress(
            message=_PROGRESS_LABEL,
            done=int(done),
            total=int(total),
            progress_state=self.progress_state,
            force_signal=force,
        )

    def run(self) -> None:
        try:
            cancel_ev = self.cancel_event
            n_in = len(self.rows)
            if n_in < 2:
                self.signals.failed.emit("Select at least two rows.")
                return

            self._report(0, n_in, force=True)
            oids: list[int] = []
            fps: list = []
            for i, (oid, mol) in enumerate(self.rows, start=1):
                if cancel_ev is not None and cancel_ev.is_set():
                    self.signals.failed.emit("Cancelled.")
                    return
                try:
                    fp = fingerprint_bitvect_for_row(int(oid), mol, self.fp_choice)
                    if fp is None:
                        fp = fingerprint_bitvect_for_ui_choice(mol, self.fp_choice)
                except Exception:
                    fp = None
                if fp is None:
                    continue
                oids.append(int(oid))
                fps.append(fp)
                if i <= 2 or i == n_in or i % 25 == 0:
                    self._report(i, n_in)
            self._report(n_in, n_in, force=True)

            if len(fps) < 2:
                self.signals.failed.emit(
                    "Need at least two rows with valid fingerprints in this scope."
                )
                return

            tot_pairs = (len(fps) * (len(fps) - 1)) // 2
            k = min(self.top_k_pairs, max(10, tot_pairs))
            most_heap: list[tuple[float, int, int]] = []
            least_heap: list[tuple[float, int, int]] = []

            sum_sim = 0.0
            count = 0
            min_sim: float | None = None
            max_sim: float | None = None

            metric = self.metric
            outer_n = len(fps)
            self._report(0, outer_n, force=True)
            last_pulse = 0.0
            for i in range(outer_n):
                if cancel_ev is not None and cancel_ev.is_set():
                    self.signals.failed.emit("Cancelled.")
                    return
                if metric == "Tanimoto":
                    sims = DataStructs.BulkTanimotoSimilarity(fps[i], fps[:i])
                else:
                    sims = [
                        pairwise_fingerprint_similarity(fps[i], fps[j], metric) for j in range(i)
                    ]
                for j in range(i):
                    s = float(sims[j])
                    sum_sim += s
                    count += 1
                    min_sim = s if min_sim is None else min(min_sim, s)
                    max_sim = s if max_sim is None else max(max_sim, s)
                    a, b = int(oids[i]), int(oids[j])
                    if len(most_heap) < k:
                        heapq.heappush(most_heap, (s, a, b))
                    elif s > most_heap[0][0]:
                        heapq.heapreplace(most_heap, (s, a, b))
                    if len(least_heap) < k:
                        heapq.heappush(least_heap, (-s, a, b))
                    elif -s > least_heap[0][0]:
                        heapq.heapreplace(least_heap, (-s, a, b))
                now = time.monotonic()
                if i <= 2 or i + 1 == outer_n or (now - last_pulse) >= 0.15:
                    last_pulse = now
                    self._report(i + 1, outer_n)
            self._report(outer_n, outer_n, force=True)

            mean_sim = (sum_sim / float(count)) if count else None
            most = sorted(most_heap, key=lambda t: t[0], reverse=True)
            least = sorted([(-s, a, b) for (s, a, b) in least_heap], key=lambda t: t[0])
            self.signals.finished.emit(
                BulkSimilarityResult(
                    n_rows=len(fps),
                    n_pairs=int(tot_pairs),
                    mean_similarity=None if mean_sim is None else float(mean_sim),
                    min_similarity=None if min_sim is None else float(min_sim),
                    max_similarity=None if max_sim is None else float(max_sim),
                    most_similar_pairs=[(a, b, float(s)) for (s, a, b) in most],
                    least_similar_pairs=[(a, b, float(s)) for (a, b, s) in least],
                )
            )
        except Exception as e:
            logger.exception("BulkSimilarityWorker failed")
            self.signals.failed.emit(str(e) or "Bulk similarity failed.")
