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
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with mctoolkit. If not, see <https://www.gnu.org/licenses/>.

"""Background analysis of an OpenMM MD DCD (RMSD / RMSF / energy join)."""

from __future__ import annotations

import contextlib
import os
import tempfile
import threading
from concurrent.futures import FIRST_COMPLETED, BrokenExecutor, ProcessPoolExecutor, wait
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, Signal

from ..md.analysis import (
    TrajectoryAnalysis,
    analyze_trajectory,
    write_analysis_csv,
    write_rmsf_csv,
)
from .process_pool_utils import (
    register_process_pool,
    should_terminate_process_pool,
    shutdown_process_pool_executor,
)
from .protein_prepare import drain_prepare_log_file
from .protein_prepare_io import (
    append_prepare_log_file,
    bind_prepare_log,
    log_prepare,
    unbind_prepare_log,
)


@dataclass(frozen=True)
class ProteinMDAnalysisRequest:
    dcd_path: str
    topology_path: str = ""
    sidecar_path: str = ""
    energy_csv: str = ""
    mmgbsa_csv: str = ""
    output_csv: str = ""
    rmsf_csv: str = ""


@dataclass(frozen=True)
class ProteinMDAnalysisJobResult:
    summary: str
    csv_path: str = ""
    rmsf_csv_path: str = ""
    n_frames: int = 0
    analysis: TrajectoryAnalysis | None = None


def run_protein_md_analysis(
    req: ProteinMDAnalysisRequest, on_log=None
) -> ProteinMDAnalysisJobResult:
    """Load DCD + topology and write analysis CSVs."""
    token = bind_prepare_log(on_log)
    try:
        return _run_protein_md_analysis(req)
    finally:
        unbind_prepare_log(token)


def _run_protein_md_analysis(req: ProteinMDAnalysisRequest) -> ProteinMDAnalysisJobResult:
    dcd = (req.dcd_path or "").strip()
    if not dcd:
        raise RuntimeError("Analyze Trajectory needs a DCD path.")
    log_prepare(f"Reading {Path(dcd).name}…")
    result = analyze_trajectory(
        dcd_path=dcd,
        topology_path=(req.topology_path or "").strip(),
        sidecar_path=(req.sidecar_path or "").strip(),
        energy_csv=(req.energy_csv or "").strip(),
        mmgbsa_csv=(req.mmgbsa_csv or "").strip(),
    )
    csv_out = (req.output_csv or "").strip()
    if csv_out:
        write_analysis_csv(Path(csv_out), result)
        log_prepare(f"Wrote {Path(csv_out).name}")
    rmsf_out = (req.rmsf_csv or "").strip()
    if rmsf_out and result.rmsf:
        write_rmsf_csv(Path(rmsf_out), result)
        log_prepare(f"Wrote {Path(rmsf_out).name}")
    log_prepare(result.summary.strip().splitlines()[0] if result.summary else "Analysis finished")
    return ProteinMDAnalysisJobResult(
        summary=result.summary,
        csv_path=csv_out,
        rmsf_csv_path=rmsf_out if result.rmsf else "",
        n_frames=result.n_frames,
        analysis=result,
    )


def mp_run_protein_md_analysis(
    req: ProteinMDAnalysisRequest, log_path: str | None = None
) -> tuple[bool, object]:
    def _log(message: str) -> None:
        append_prepare_log_file(log_path, message)

    try:
        return True, run_protein_md_analysis(req, on_log=_log)
    except Exception as exc:  # noqa: BLE001
        return False, str(exc) or "Trajectory analysis failed."


class ProteinMDAnalysisSignals(QObject):
    finished = Signal(object)
    failed = Signal(str)
    progress = Signal(str)


class ProteinMDAnalysisWorker(QRunnable):
    """Run DCD analysis in an isolated subprocess."""

    def __init__(
        self,
        req: ProteinMDAnalysisRequest,
        *,
        signals: ProteinMDAnalysisSignals,
        cancel_event: threading.Event | None = None,
    ) -> None:
        super().__init__()
        self.req = req
        self.signals = signals
        self.cancel_event = cancel_event

    def run(self) -> None:
        cancel_ev = self.cancel_event
        try:
            if cancel_ev is not None and cancel_ev.is_set():
                self.signals.failed.emit("Cancelled.")
                return
            ex = register_process_pool(ProcessPoolExecutor(max_workers=1))
            log_path: str | None = None
            try:
                fd, log_path = tempfile.mkstemp(prefix="mctoolkit_md_an_log_", suffix=".txt")
                os.close(fd)
            except OSError:
                log_path = None
            seen = [0]
            try:
                future = ex.submit(mp_run_protein_md_analysis, self.req, log_path)
                pending = {future}
                while pending:
                    drain_prepare_log_file(log_path, seen, self.signals.progress.emit)
                    if should_terminate_process_pool(cancel_ev):
                        future.cancel()
                        self.signals.failed.emit("Cancelled.")
                        return
                    _done, pending = wait(pending, timeout=0.25, return_when=FIRST_COMPLETED)
                drain_prepare_log_file(log_path, seen, self.signals.progress.emit)
                if future.cancelled():
                    self.signals.failed.emit("Cancelled.")
                    return
                ok, msg = future.result()
                drain_prepare_log_file(log_path, seen, self.signals.progress.emit)
            finally:
                shutdown_process_pool_executor(
                    ex, kill_workers=should_terminate_process_pool(cancel_ev)
                )
                if log_path:
                    with contextlib.suppress(OSError):
                        os.unlink(log_path)
            if cancel_ev is not None and cancel_ev.is_set():
                self.signals.failed.emit("Cancelled.")
                return
            if ok:
                self.signals.finished.emit(msg)
            else:
                self.signals.failed.emit(str(msg))
        except BrokenExecutor:
            self.signals.failed.emit("Trajectory analysis subprocess crashed.")
        except Exception as exc:  # noqa: BLE001
            self.signals.failed.emit(str(exc) or "Trajectory analysis failed.")
