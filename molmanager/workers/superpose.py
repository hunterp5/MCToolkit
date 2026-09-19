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
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with MolManager. If not, see <https://www.gnu.org/licenses/>.

"""Conformer and structure superposition workers, plus RMSD.

Implementation lives in ``superpose_geom``, ``superpose_conformers``,
``superpose_structures``, and ``superpose_rmsd``. This module keeps the
QRunnable adapters and stable import path.
"""

from __future__ import annotations

import logging
import os
import threading
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

from PyQt5.QtCore import QRunnable
from rdkit import Chem

from ..config import load_config
from ..confs_codec import mol_from_packed_confs_cell
from ..storage import ensemble_mol_for
from .chemistry_worker_common import emit_tool_progress_throttled
from .signals import WorkerSignals, emit_partial_results_if_cancelled
from .superpose_conformers import run_superpose_conformers
from .superpose_geom import (
    _central_ring_atoms,
    _largest_ring_system_atoms,
    _normalize_superpose_geometry,
)
from .superpose_rmsd import run_conformer_rmsd
from .superpose_structures import (
    align_structure_onto_reference,
    run_superpose_structures,
)
from .superpose_types import RmsdParams, SuperposeParams, SuperposeStructuresParams

logger = logging.getLogger(__name__)

__all__ = [
    "RmsdParams",
    "SuperposeConformersWorker",
    "SuperposeParams",
    "SuperposeStructuresParams",
    "SuperposeStructuresWorker",
    "align_structure_onto_reference",
    "run_conformer_rmsd",
    "run_superpose_conformers",
    "run_superpose_structures",
    "_central_ring_atoms",
    "_largest_ring_system_atoms",
]


def _looks_like_packed_cell(src: str) -> bool:
    return (src or "").lstrip().startswith("{")


def _superpose_row_task(task: tuple) -> tuple[int, Chem.Mol | None, dict]:
    oid, src, params = task[0], task[1], task[2]
    cancel_event = task[3] if len(task) > 3 else None
    db_path = task[4] if len(task) > 4 else None
    try:
        if cancel_event is not None and cancel_event.is_set():
            return oid, None, {"ok": False, "err": "cancelled", "op": "superpose"}
        mol = None
        if db_path and not _looks_like_packed_cell(str(src or "")):
            mol = ensemble_mol_for(db_path, oid, str(src or ""), min_conformers=2)
        if mol is None:
            mol = mol_from_packed_confs_cell(src or "")
        if mol is None:
            return oid, None, {"ok": False, "err": "no_packed_conformers", "op": "superpose"}
        new_m, meta = run_superpose_conformers(mol, params, cancel_event=cancel_event)
        if new_m is None:
            return oid, None, dict(meta)
        return oid, new_m, dict(meta)
    except Exception as e:
        logger.exception("SuperposeConformersWorker failed for oid=%s", oid)
        return oid, None, {"ok": False, "err": str(e)[:200], "op": "superpose"}


class SuperposeConformersWorker(QRunnable):
    """Align conformers from the ensemble store (or packed cells) into a ``superpose`` column."""

    def __init__(
        self,
        data: list[tuple[int, str]],
        params: SuperposeParams,
        signals: WorkerSignals,
        cancel_event: threading.Event | None = None,
        progress_state=None,
        ensemble_db: str | None = None,
    ):
        super().__init__()
        self.data = data
        self.params = params
        self.signals = signals
        self.cancel_event = cancel_event
        self.progress_state = progress_state
        self.ensemble_db = ensemble_db

    def run(self):
        nrows = len(self.data)
        tot = max(nrows, 1)
        tasks = [(oid, cell, self.params) for oid, cell in self.data]
        cfg = load_config()
        if cfg.conformer_threads is not None:
            max_workers = cfg.conformer_threads
        else:
            max_workers = min(4, max(1, (os.cpu_count() or 4) // 2))
        use_parallel = nrows >= 6 and max_workers > 1
        cancel_ev = self.cancel_event
        results: list = []
        cancelled = False
        done_count = 0
        prog_state = [0, 0.0]
        try:
            if use_parallel:
                emit_tool_progress_throttled(
                    self.signals,
                    "Superpose conformers…",
                    0,
                    tot,
                    prog_state,
                    progress_state=self.progress_state,
                )
                ex = ThreadPoolExecutor(max_workers=max_workers)
                shutdown_cancel = False
                try:
                    row_tasks = [(*t, cancel_ev, self.ensemble_db) for t in tasks]
                    pending = {ex.submit(_superpose_row_task, rt) for rt in row_tasks}
                    done_count = 0
                    while pending:
                        if cancel_ev is not None and cancel_ev.is_set():
                            shutdown_cancel = True
                            cancelled = True
                            for f in list(pending):
                                if f.done() and not f.cancelled():
                                    try:
                                        results.append(f.result())
                                        done_count += 1
                                    except Exception:
                                        logger.exception("Superpose row task failed")
                                else:
                                    f.cancel()
                            break
                        completed, pending = wait(
                            pending, timeout=0.08, return_when=FIRST_COMPLETED
                        )
                        for f in completed:
                            if f.cancelled():
                                continue
                            try:
                                results.append(f.result())
                                done_count += 1
                            except Exception:
                                logger.exception("Superpose row task failed")
                            emit_tool_progress_throttled(
                                self.signals,
                                "Superpose conformers…",
                                done_count,
                                tot,
                                prog_state,
                                progress_state=self.progress_state,
                            )
                finally:
                    try:
                        ex.shutdown(wait=not shutdown_cancel, cancel_futures=shutdown_cancel)
                    except TypeError:
                        ex.shutdown(wait=not shutdown_cancel)
                emit_tool_progress_throttled(
                    self.signals,
                    "Superpose conformers…",
                    min(done_count, tot),
                    tot,
                    prog_state,
                    progress_state=self.progress_state,
                )
            else:
                for done, t in enumerate(tasks, start=1):
                    if cancel_ev is not None and cancel_ev.is_set():
                        cancelled = True
                        break
                    results.append(_superpose_row_task((*t, cancel_ev, self.ensemble_db)))
                    done_count = done
                    emit_tool_progress_throttled(
                        self.signals,
                        "Superpose conformers…",
                        done,
                        tot,
                        prog_state,
                        progress_state=self.progress_state,
                    )
        finally:
            emit_partial_results_if_cancelled(
                self.signals, "Superpose conformers", done_count, tot, cancelled
            )
            try:
                self.signals.superpose_finished.emit(results)
            except Exception:
                logger.warning("superpose_finished emit failed", exc_info=True)


class SuperposeStructuresWorker(QRunnable):
    """Align distinct table structures onto a reference off the GUI thread."""

    def __init__(
        self,
        ref_oid: int,
        ref_mol: Chem.Mol,
        probes: list[tuple[int, Chem.Mol]],
        params: SuperposeStructuresParams,
        signals: WorkerSignals,
        cancel_event: threading.Event | None = None,
        progress_state=None,
    ):
        super().__init__()
        self.ref_oid = int(ref_oid)
        self.ref_mol = ref_mol
        self.probes = probes
        self.params = params
        self.signals = signals
        self.cancel_event = cancel_event
        self.progress_state = progress_state

    def run(self):
        tot = max(len(self.probes), 1)
        prog_state = [0, 0.0]
        cancelled = False
        results: list = []
        try:
            emit_tool_progress_throttled(
                self.signals,
                "Superpose…",
                0,
                tot,
                prog_state,
                progress_state=self.progress_state,
            )

            def _prog(done: int, total: int) -> None:
                emit_tool_progress_throttled(
                    self.signals,
                    "Superpose…",
                    done,
                    total,
                    prog_state,
                    progress_state=self.progress_state,
                )

            results = run_superpose_structures(
                self.ref_mol,
                self.probes,
                self.params,
                ref_oid=self.ref_oid,
                cancel_event=self.cancel_event,
                progress=_prog,
            )
            if self.cancel_event is not None and self.cancel_event.is_set():
                cancelled = True
        except Exception:
            logger.exception("SuperposeStructuresWorker failed")
            results = [
                (
                    int(oid),
                    None,
                    {"ok": False, "err": "worker_failed", "op": "superpose_structures"},
                )
                for oid, _m in self.probes
            ]
        finally:
            done_ok = sum(1 for _o, mol, meta in results if mol is not None and meta.get("ok"))
            emit_partial_results_if_cancelled(self.signals, "Superpose", done_ok, tot, cancelled)
            try:
                geom = _normalize_superpose_geometry(getattr(self.params, "geometry", "3d"))
                self.signals.superpose_structures_finished.emit(
                    {
                        "ref_oid": int(self.ref_oid),
                        "geometry": geom,
                        "results": results,
                    }
                )
            except Exception:
                logger.warning("superpose_structures_finished emit failed", exc_info=True)
