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

"""Generate protomer sets from a Uni-pKa ionization ensemble at a target pH.

**Uni-pKa** — Luo et al., JACS Au 2024, doi:10.1021/jacsau.4c00271.
Populations are Boltzmann weights of β-scaled free energies plus
``charge · ln(10) · pH`` (same ensemble as Predict pKa / LogD 7.4).
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass

from PySide6.QtCore import QObject, QRunnable, Signal
from rdkit import Chem

from molmanager.ionization.unipka_ensembles import populations_from_states, unipka_import_error
from ..platform_support.config import load_config
from .ionization_parallel import build_microstates_cache_by_key
from .pka_predictor import _quieter_unipka_loggers, _safe_emit
from .process_pool_utils import should_terminate_process_pool
from .structure_grouping import group_rows_by_structure

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProtomerGeneratorRequest:
    """Molecules and target pH for :class:`ProtomerGeneratorWorker`."""

    rows: list
    pH: float


def estimate_protomer_populations_from_states(
    states, pH: float
) -> list[tuple[str, float, Chem.Mol]]:
    """Protomer mole fractions at ``pH`` from a Uni-pKa ensemble (or HA/A− HH fallback)."""
    return populations_from_states(states, pH)


class ProtomerGeneratorSignals(QObject):
    finished = Signal(list)  # list[tuple[int | None, str, float]]  source_oid, smiles, pct
    failed = Signal(str)


class ProtomerGeneratorWorker(QRunnable):
    """Enumerate protomers per input molecule and estimate populations at a target pH."""

    def __init__(
        self,
        request: ProtomerGeneratorRequest,
        worker_signals,
        protomer_signals: ProtomerGeneratorSignals,
        *,
        cancel_event: threading.Event | None = None,
        progress_state=None,
    ):
        super().__init__()
        self.rows = request.rows
        self.pH = float(request.pH)
        self.worker_signals = worker_signals
        self.protomer_signals = protomer_signals
        self.cancel_event = cancel_event
        self.progress_state = progress_state

    def run(self) -> None:
        with _quieter_unipka_loggers():
            err = unipka_import_error()
            if err:
                logger.error("Protomer generator: %s", err)
                _safe_emit(self.protomer_signals, "failed", err)
                return

            cancel_ev = self.cancel_event
            combined: list[tuple[int | None, str, float]] = []

            order, rep, oids_map = group_rows_by_structure(self.rows)
            n_work = sum(len(oids_map[k]) for k in order)
            tot = max(n_work, 1)
            n_unique = len(order)

            done_cum = 0
            prog_last = 0.0
            cancelled = False

            from ..platform_support.tool_progress import report_tool_progress

            throttle = [0, 0.0]

            def _emit(done: int, *, force: bool = False) -> None:
                nonlocal prog_last
                now = time.monotonic()
                if force or done >= tot or (now - prog_last) >= 0.12:
                    prog_last = now
                    report_tool_progress(
                        message="Generate protomers",
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
                _safe_emit(self.protomer_signals, "finished", combined)
                return

            mols = [rep[k] for k in order if rep.get(k) is not None]
            by_key = build_microstates_cache_by_key(
                mols,
                workers_cfg=load_config().protomer_process_workers,
                cancel_event=cancel_ev,
                progress_state=self.progress_state,
                signals=self.worker_signals,
                progress_message="Generate protomers",
                progress_total=tot,
                reserve_final_tick=False,
            )
            for key in order:
                states = by_key.get(key)
                if not states:
                    done_cum += len(oids_map.get(key, ()))
                    _emit(done_cum)
                    continue
                try:
                    pops = estimate_protomer_populations_from_states(states, self.pH)
                except Exception as e:
                    logger.warning(
                        "Protomer generation failed for %s row(s) (structure key prefix %.40s…): %s",
                        len(oids_map.get(key, ())),
                        key,
                        e,
                    )
                    pops = []
                for oid in oids_map.get(key, ()):
                    for smi, pct, _m in pops:
                        combined.append((oid, smi, pct))
                done_cum += len(oids_map.get(key, ()))
                _emit(done_cum)

            if should_terminate_process_pool(cancel_ev):
                cancelled = True
            _emit(tot if not cancelled else min(done_cum, tot), force=True)
            if cancelled and done_cum > 0:
                try:
                    self.worker_signals.partial_results.emit("Generate protomers", done_cum, tot)
                except Exception:
                    pass
            logger.debug(
                "Protomer: %s table row(s), %s unique structure(s)",
                n_work,
                n_unique,
            )
            _safe_emit(self.protomer_signals, "finished", combined)
