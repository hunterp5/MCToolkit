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

"""Worker: pairwise fingerprint similarity + activity → SALI landscape points."""

from __future__ import annotations

import logging
import threading
import time

from PySide6.QtCore import QRunnable
from rdkit import Chem, DataStructs

from ..chem.rdkit_fingerprints import fingerprint_bitvect_for_row, fingerprint_bitvect_for_ui_choice
from ..analysis.sali_analysis import accumulate_sali_candidate, finalize_sali_points
from ..platform_support.tool_progress import report_tool_progress
from .fingerprint_similarity import SIMILARITY_METRIC_LABELS, pairwise_fingerprint_similarity
from .signals import WorkerSignals

logger = logging.getLogger(__name__)


class SaliAnalysisWorker(QRunnable):
    """Compute SALI pairs among molecules with numeric activity values."""

    def __init__(
        self,
        records: list[tuple[int, Chem.Mol, float]],
        *,
        activity_column: str,
        fp_choice: str,
        metric: str = "Tanimoto",
        min_similarity: float = 0.0,
        min_activity_difference: float = 0.0,
        max_pairs: int = 10000,
        signals: WorkerSignals,
        cancel_event: threading.Event | None = None,
        progress_state=None,
    ):
        super().__init__()
        self.records = records
        self.activity_column = activity_column
        self.fp_choice = fp_choice
        self.metric = metric if metric in SIMILARITY_METRIC_LABELS else "Tanimoto"
        self.min_similarity = float(min_similarity)
        self.min_activity_difference = float(min_activity_difference)
        self.max_pairs = int(max_pairs)
        self.signals = signals
        self.cancel_event = cancel_event
        self.progress_state = progress_state

    def run(self) -> None:
        label = "SALI"
        ev = self.cancel_event
        if ev is not None and ev.is_set():
            return
        tot = max(len(self.records), 1)
        throttle = [0, 0.0]
        report_tool_progress(
            message=label,
            done=0,
            total=tot,
            progress_state=self.progress_state,
            signals=self.signals,
            throttle=throttle,
            force_signal=True,
        )
        try:
            oids: list[int] = []
            fps: list = []
            activities: list[float] = []
            for i, (oid, mol, act) in enumerate(self.records):
                if ev is not None and ev.is_set():
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
                activities.append(float(act))
                report_tool_progress(
                    message=label,
                    done=min(i + 1, tot),
                    total=tot,
                    progress_state=self.progress_state,
                    signals=self.signals,
                    throttle=throttle,
                )

            if len(fps) < 2:
                self.signals.sali_failed.emit(
                    "Need at least two molecules with both a structure and a fingerprint."
                )
                return

            n = len(fps)
            min_sim = max(0.0, float(self.min_similarity))
            min_dact = max(0.0, float(self.min_activity_difference))
            heap: list = []
            last_pulse = 0.0
            report_tool_progress(
                message=label,
                done=0,
                total=n,
                progress_state=self.progress_state,
                signals=self.signals,
                throttle=throttle,
                force_signal=True,
            )
            for i in range(n):
                if ev is not None and ev.is_set():
                    return
                if self.metric == "Tanimoto":
                    sims = DataStructs.BulkTanimotoSimilarity(fps[i], fps[:i])
                else:
                    sims = [
                        pairwise_fingerprint_similarity(fps[i], fps[j], self.metric)
                        for j in range(i)
                    ]
                act_i = activities[i]
                oid_i = oids[i]
                for j in range(i):
                    accumulate_sali_candidate(
                        heap,
                        oid_i,
                        oids[j],
                        float(sims[j]),
                        act_i,
                        activities[j],
                        min_similarity=min_sim,
                        min_activity_difference=min_dact,
                        max_pairs=self.max_pairs,
                    )
                now = time.monotonic()
                if i <= 2 or i + 1 == n or (now - last_pulse) >= 0.12:
                    last_pulse = now
                    report_tool_progress(
                        message=label,
                        done=i + 1,
                        total=n,
                        progress_state=self.progress_state,
                        signals=self.signals,
                        throttle=throttle,
                    )

            points = finalize_sali_points(heap)
            report_tool_progress(
                message=label,
                done=n,
                total=n,
                progress_state=self.progress_state,
                signals=self.signals,
                throttle=throttle,
                force_signal=True,
            )
            if ev is not None and ev.is_set():
                return
            self.signals.sali_finished.emit(
                points,
                self.activity_column,
                self.fp_choice,
                self.metric,
            )
        except Exception as exc:
            logger.exception("SALI analysis failed")
            self.signals.sali_failed.emit(str(exc) or "SALI analysis failed.")
