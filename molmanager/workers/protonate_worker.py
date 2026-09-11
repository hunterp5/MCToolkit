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

"""Generate the dominant protomer per molecule from a Uni-pKa ionization ensemble."""

from __future__ import annotations

import logging
import threading
import time

from PyQt5.QtCore import QObject, QRunnable, pyqtSignal
from rdkit import Chem

from molmanager.ionization import populations_from_states, unipka_import_error
from ..config import load_config
from .ionization_parallel import build_microstates_cache_by_key
from .pka_predictor import _quieter_unipka_loggers
from .process_pool_utils import should_terminate_process_pool
from .structure_grouping import group_rows_by_structure

logger = logging.getLogger(__name__)


class ProtonateSignals(QObject):
    finished = pyqtSignal(list)  # list[tuple[int, str, float]] oid, dominant_smiles, pct
    failed = pyqtSignal(str)


def _dominant_smiles_from_microstates(states, pH: float) -> tuple[str, float] | None:
    pops = populations_from_states(states, float(pH))
    if not pops:
        return None
    smi, pct, _mol = pops[0]
    if not smi:
        return None
    return str(smi), float(pct)


def dominant_results_from_microstate_cache(
    order: list[str],
    oids_map: dict[str, list],
    by_key: dict[str, object | None],
    pH: float,
    *,
    cancel_event: threading.Event | None = None,
) -> tuple[list[tuple[int, str, float]], bool]:
    """Map cached ensembles to per-row dominant SMILES. Returns ``(rows, cancelled)``."""
    partial: list[tuple[int, str, float]] = []
    cancelled = False
    for key in order:
        if should_terminate_process_pool(cancel_event):
            cancelled = True
            break
        states = by_key.get(key)
        if not states:
            continue
        try:
            dom = _dominant_smiles_from_microstates(states, pH)
        except Exception:
            logger.exception("Protonate: population estimate failed for key=%s", key[:48])
            continue
        if dom is None:
            continue
        smi, pct = dom
        for oid in oids_map.get(key, ()):
            partial.append((int(oid), str(smi), float(pct)))
    return partial, cancelled


class ProtonateWorker(QRunnable):
    """Compute dominant protomer SMILES for each row at a target pH."""

    def __init__(
        self,
        rows: list[tuple[int, Chem.Mol | None]],
        pH: float,
        *,
        signals: ProtonateSignals,
        cancel_event: threading.Event | None = None,
        progress_state=None,
        worker_signals=None,
        progress_message: str = "Protonate",
    ) -> None:
        super().__init__()
        self.rows = rows
        self.pH = float(pH)
        self.signals = signals
        self.cancel_event = cancel_event
        self.progress_state = progress_state
        self.worker_signals = worker_signals
        self.progress_message = progress_message

    def run(self) -> None:
        from ..tool_progress import report_tool_progress

        with _quieter_unipka_loggers():
            err = unipka_import_error()
            if err:
                logger.error("Protonate: %s", err)
                self.signals.failed.emit(err)
                return

            cancel_ev = self.cancel_event
            order, rep, oids_map = group_rows_by_structure(self.rows)
            n_work = sum(len(oids_map[k]) for k in order)
            tot = max(n_work, 1)

            throttle = [0, 0.0]
            last_pulse = 0.0

            def _emit(done: int, *, force: bool = False) -> None:
                nonlocal last_pulse
                now = time.monotonic()
                if force or done >= tot or (now - last_pulse) >= 0.12:
                    last_pulse = now
                    report_tool_progress(
                        message=self.progress_message,
                        done=min(int(done), tot),
                        total=tot,
                        progress_state=self.progress_state,
                        signals=self.worker_signals,
                        throttle=throttle,
                        force_signal=force,
                    )

            _emit(0, force=True)
            if not order:
                _emit(tot, force=True)
                self.signals.finished.emit([])
                return

            mols = [rep[k] for k in order if rep.get(k) is not None]
            by_key = build_microstates_cache_by_key(
                mols,
                workers_cfg=load_config().protomer_process_workers,
                cancel_event=cancel_ev,
                progress_state=self.progress_state,
                signals=self.worker_signals,
                progress_message=self.progress_message,
                progress_total=tot,
            )
            partial, cancelled = dominant_results_from_microstate_cache(
                order, oids_map, by_key, self.pH, cancel_event=cancel_ev
            )
            if should_terminate_process_pool(cancel_ev):
                cancelled = True

            _emit(tot, force=True)
            if cancelled and self.worker_signals is not None:
                try:
                    from .signals import emit_partial_results_if_cancelled

                    emit_partial_results_if_cancelled(
                        self.worker_signals, "Protonate", len(partial), tot, True
                    )
                except Exception:
                    pass
            self.signals.finished.emit(partial)
            if cancelled:
                self.signals.failed.emit("Cancelled.")
