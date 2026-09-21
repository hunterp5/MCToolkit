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

"""Background worker for Protein Viewer complex minimization."""

from __future__ import annotations

import threading
from concurrent.futures import FIRST_COMPLETED, BrokenExecutor, ProcessPoolExecutor, wait

from PySide6.QtCore import QObject, QRunnable, Signal

from .process_pool_utils import (
    register_process_pool,
    should_terminate_process_pool,
    shutdown_process_pool_executor,
)
from .protein_complex_minimize import (
    ProteinMinimizeRequest,
    minimize_protein_complex,
    mp_minimize_protein_complex,
)

_OPENMM_VERSION_HINT = (
    "Minimize subprocess crashed. On Windows this is often caused by OpenMM 8.3+ "
    "(native crash during hydrogen placement). Install a supported build:\n"
    "  pip install 'openmm>=8.2,<8.3' pdbfixer pdb2pqr"
)


class ProteinMinimizeSignals(QObject):
    finished = Signal(str)
    failed = Signal(str)


class ProteinMinimizeWorker(QRunnable):
    """Run complex minimization in an isolated subprocess."""

    def __init__(
        self,
        req: ProteinMinimizeRequest,
        *,
        signals: ProteinMinimizeSignals,
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
            try:
                future = ex.submit(mp_minimize_protein_complex, self.req)
                pending = {future}
                while pending:
                    if should_terminate_process_pool(cancel_ev):
                        future.cancel()
                        self.signals.failed.emit("Cancelled.")
                        return
                    _done, pending = wait(pending, timeout=0.25, return_when=FIRST_COMPLETED)
                if future.cancelled():
                    self.signals.failed.emit("Cancelled.")
                    return
                ok, msg = future.result()
            finally:
                shutdown_process_pool_executor(
                    ex, kill_workers=should_terminate_process_pool(cancel_ev)
                )

            if cancel_ev is not None and cancel_ev.is_set():
                self.signals.failed.emit("Cancelled.")
                return
            if ok:
                self.signals.finished.emit(str(msg))
            else:
                self.signals.failed.emit(str(msg))
        except BrokenExecutor:
            self.signals.failed.emit(_OPENMM_VERSION_HINT)
        except Exception as exc:
            text = str(exc) or "Complex minimization failed."
            if "terminated abruptly" in text.lower():
                self.signals.failed.emit(_OPENMM_VERSION_HINT)
            else:
                self.signals.failed.emit(text)


__all__ = [
    "ProteinMinimizeRequest",
    "ProteinMinimizeSignals",
    "ProteinMinimizeWorker",
    "minimize_protein_complex",
]
