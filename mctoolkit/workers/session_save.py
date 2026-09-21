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

"""Write a session snapshot to ``.mct`` off the GUI thread."""

from __future__ import annotations

import contextlib
import logging

from PySide6.QtCore import QObject, QRunnable, Signal

from ..table.session_document_build import dumps_session_snapshot

logger = logging.getLogger(__name__)


class SessionSaveSignals(QObject):
    finished = Signal(str)
    failed = Signal(str)


class SessionSaveWorker(QRunnable):
    """Encode, gzip, and write a session snapshot."""

    def __init__(self, snapshot: dict, path: str, signals: SessionSaveSignals) -> None:
        super().__init__()
        self.snapshot = snapshot
        self.path = path
        self.signals = signals

    def run(self) -> None:
        try:
            payload = dumps_session_snapshot(self.snapshot)
            with open(self.path, "wb") as handle:
                handle.write(payload)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Session save failed: %s", self.path)
            with contextlib.suppress(RuntimeError):
                self.signals.failed.emit(str(exc) or exc.__class__.__name__)
            return
        try:
            self.signals.finished.emit(self.path)
        except RuntimeError:
            logger.exception("Session save finished signal failed")
