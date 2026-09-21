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

"""Background MAFFT multiple-sequence alignment."""

from __future__ import annotations

import threading

from PySide6.QtCore import QObject, QRunnable, Signal

from ..protein.protein_msa import FastaRecord, run_mafft_alignment


class MafftAlignSignals(QObject):
    finished = Signal(list)
    failed = Signal(str)


class MafftAlignWorker(QRunnable):
    """Run MAFFT on a sequence pool and emit aligned :class:`FastaRecord` rows."""

    def __init__(
        self,
        records: list[FastaRecord],
        exe: str,
        *,
        threads: int = 1,
        timeout_s: int = 600,
        cancel_event: threading.Event | None = None,
    ):
        super().__init__()
        self.records = list(records)
        self.exe = exe
        self.threads = int(threads)
        self.timeout_s = int(timeout_s)
        self.cancel_event = cancel_event
        self.signals = MafftAlignSignals()

    def run(self) -> None:
        try:
            aligned = run_mafft_alignment(
                self.records,
                exe=self.exe,
                timeout_s=self.timeout_s,
                threads=self.threads,
                cancel_event=self.cancel_event,
            )
        except Exception as exc:
            try:
                self.signals.failed.emit(str(exc) or "MAFFT alignment failed.")
            except Exception:
                pass
            return
        try:
            self.signals.finished.emit(aligned)
        except Exception:
            pass
