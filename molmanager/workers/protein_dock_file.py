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

"""Background worker that writes Gnina files from a ready protein–ligand structure."""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from pathlib import Path

from PyQt5.QtCore import QObject, QRunnable, pyqtSignal

from .protein_prepare_constants import ResidueKey
from .protein_prepare_smina import ProteinPrepareResult, write_dock_file_artifacts

logger = logging.getLogger(__name__)


@dataclass
class DockFileRequest:
    """Paths and box options for Prepare → Dock File."""

    input_path: str
    output_path: str
    box_ligand_keys: tuple[ResidueKey, ...] = ()
    box_ligand_path: str = ""
    box_padding: float = 4.0
    box_source_text: str = ""
    box_source_fmt: str = ""


class DockFileSignals(QObject):
    finished = pyqtSignal(object)
    failed = pyqtSignal(str)
    progress = pyqtSignal(str)


def run_dock_file(req: DockFileRequest) -> ProteinPrepareResult:
    """Read the input structure and write apo PDBQT, ligand, and search-box files."""
    rec = Path(req.input_path)
    text = rec.read_text(encoding="utf-8")
    from ..structure_components import sniff_structure_format, viewer_format_for

    fmt = viewer_format_for(sniff_structure_format(rec, text))
    keys = set(req.box_ligand_keys) if req.box_ligand_keys else None
    return write_dock_file_artifacts(
        text=text,
        fmt=fmt,
        output_path=Path(req.output_path),
        box_ligand_keys=keys,
        box_ligand_path=req.box_ligand_path,
        padding=float(req.box_padding),
        source_text=req.box_source_text,
        source_fmt=req.box_source_fmt,
    )


class DockFileWorker(QRunnable):
    """Write Gnina artifacts without PDBFixer, pdb2pqr, or OpenMM."""

    def __init__(
        self,
        req: DockFileRequest,
        *,
        signals: DockFileSignals,
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
            self.signals.progress.emit("Writing Gnina receptor PDBQT, ligand, and search box…")
            result = run_dock_file(self.req)
            if cancel_ev is not None and cancel_ev.is_set():
                self.signals.failed.emit("Cancelled.")
                return
            self.signals.finished.emit(result)
        except Exception as exc:
            logger.exception("Dock File failed")
            self.signals.failed.emit(str(exc) or "Dock File failed.")
