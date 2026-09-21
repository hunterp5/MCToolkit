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
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with MCToolkit. If not, see <https://www.gnu.org/licenses/>.

"""Background tautomer enumeration for Tools → Prepare Structures → Tautomers."""

from __future__ import annotations

import logging
import threading
import time
from contextlib import suppress
from dataclasses import dataclass

from PySide6.QtCore import QObject, QRunnable, Signal

from mctoolkit.chem.tautomer_enumeration import (
    DEFAULT_MAX_TAUTOMERS,
    enumerate_likely_tautomers,
)
from ..platform_support.tool_progress import report_tool_progress
from .pka_predictor import _safe_emit
from .process_pool_utils import should_terminate_process_pool
from .structure_grouping import group_rows_by_structure

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TautomerGeneratorRequest:
    """Molecules and result-size cap for :class:`TautomerGeneratorWorker`."""

    rows: list
    max_tautomers: int = DEFAULT_MAX_TAUTOMERS


class TautomerGeneratorSignals(QObject):
    finished = Signal(list)  # list[tuple[int | None, str, int, bool, bool]]
    failed = Signal(str)


class TautomerGeneratorWorker(QRunnable):
    """Enumerate likely tautomers per input molecule."""

    def __init__(
        self,
        request: TautomerGeneratorRequest,
        worker_signals,
        tautomer_signals: TautomerGeneratorSignals,
        *,
        cancel_event: threading.Event | None = None,
        progress_state=None,
    ):
        super().__init__()
        self.rows = request.rows
        self.max_tautomers = int(request.max_tautomers)
        self.worker_signals = worker_signals
        self.tautomer_signals = tautomer_signals
        self.cancel_event = cancel_event
        self.progress_state = progress_state

    def run(self) -> None:
        cancel_ev = self.cancel_event
        combined: list[tuple[int | None, str, int, bool, bool]] = []

        order, rep, oids_map = group_rows_by_structure(self.rows)
        n_work = sum(len(oids_map[k]) for k in order)
        tot = max(n_work, 1)
        n_unique = len(order)
        done_cum = 0
        prog_last = 0.0
        cancelled = False

        throttle = [0, 0.0]

        def _emit(done: int, *, force: bool = False) -> None:
            nonlocal prog_last
            now = time.monotonic()
            if force or done >= tot or (now - prog_last) >= 0.12:
                prog_last = now
                report_tool_progress(
                    message="Generate tautomers",
                    done=min(done, tot),
                    total=tot,
                    progress_state=self.progress_state,
                    signals=self.worker_signals,
                    throttle=throttle,
                    force_signal=force,
                )

        _emit(0, force=True)
        if not order:
            _emit(tot, force=True)
            _safe_emit(self.tautomer_signals, "finished", combined)
            return

        for key in order:
            if should_terminate_process_pool(cancel_ev):
                cancelled = True
                break
            mol = rep.get(key)
            hits = enumerate_likely_tautomers(mol, max_tautomers=self.max_tautomers)
            for oid in oids_map.get(key, ()):
                for hit in hits:
                    combined.append((oid, hit.smiles, hit.score, hit.is_canonical, hit.is_input))
            done_cum += len(oids_map.get(key, ()))
            _emit(done_cum)

        if should_terminate_process_pool(cancel_ev):
            cancelled = True
        _emit(tot if not cancelled else min(done_cum, tot), force=True)
        if cancelled and done_cum > 0:
            with suppress(RuntimeError):
                self.worker_signals.partial_results.emit("Generate tautomers", done_cum, tot)
        logger.debug(
            "Tautomers: %s table row(s), %s unique structure(s)",
            n_work,
            n_unique,
        )
        _safe_emit(self.tautomer_signals, "finished", combined)
