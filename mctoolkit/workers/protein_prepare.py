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

"""Background worker for Protein Viewer structure preparation."""

from __future__ import annotations

import os
import tempfile
import threading
from concurrent.futures import FIRST_COMPLETED, BrokenExecutor, ProcessPoolExecutor, wait
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, Signal

from .process_pool_utils import (
    register_process_pool,
    should_terminate_process_pool,
    shutdown_process_pool_executor,
)
from .protein_prepare_runtime import (
    ProteinPrepareRequest,
    mp_prepare_protein_structure,
    prepare_protein_structure,
)
from .protein_prepare_smina import ProteinPrepareResult

_OPENMM_VERSION_HINT = (
    "Prepare subprocess crashed. On Windows this is often caused by OpenMM 8.3+ "
    "(native crash during hydrogen placement). Install a supported build:\n"
    "  pip install 'openmm>=8.2,<8.3' pdbfixer pdb2pqr"
)


class ProteinPrepareSignals(QObject):
    finished = Signal(object)
    failed = Signal(str)
    progress = Signal(str)


def drain_prepare_log_file(path: str | Path | None, seen: list[int], emit) -> None:
    """Emit new lines from the Prepare log file written by the child process."""
    if not path or emit is None:
        return
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return
    lines = [ln.strip() for ln in text.splitlines()]
    start = seen[0] if seen else 0
    for line in lines[start:]:
        if line:
            emit(line)
    n = len(lines)
    if seen:
        seen[0] = n
    else:
        seen.append(n)


class ProteinPrepareWorker(QRunnable):
    """Run the Prepare pipeline in an isolated subprocess."""

    def __init__(
        self,
        req: ProteinPrepareRequest,
        *,
        signals: ProteinPrepareSignals,
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
                fd, log_path = tempfile.mkstemp(prefix="mctoolkit_prepare_log_", suffix=".txt")
                os.close(fd)
            except OSError:
                log_path = None
            seen = [0]
            try:
                future = ex.submit(mp_prepare_protein_structure, self.req, log_path)
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
                    try:
                        os.unlink(log_path)
                    except OSError:
                        pass

            if cancel_ev is not None and cancel_ev.is_set():
                self.signals.failed.emit("Cancelled.")
                return
            if ok:
                self.signals.finished.emit(msg)
            else:
                self.signals.failed.emit(msg)
        except BrokenExecutor:
            self.signals.failed.emit(_OPENMM_VERSION_HINT)
        except Exception as exc:
            text = str(exc) or "Structure preparation failed."
            if "terminated abruptly" in text.lower():
                self.signals.failed.emit(_OPENMM_VERSION_HINT)
            else:
                self.signals.failed.emit(text)


__all__ = [
    "ProteinPrepareRequest",
    "ProteinPrepareResult",
    "ProteinPrepareSignals",
    "ProteinPrepareWorker",
    "drain_prepare_log_file",
    "prepare_protein_structure",
]
