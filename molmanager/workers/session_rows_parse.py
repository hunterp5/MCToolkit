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

"""Background SMILES parsing for session document restore."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from PyQt5 import sip
from PyQt5.QtCore import QObject, QRunnable, pyqtSignal
from rdkit import Chem

from ..session_codec import row_structure_smiles


def _safe_emit(obj: QObject | None, emitter_name: str, *args) -> None:
    if obj is None:
        return
    try:
        if sip.isdeleted(obj):
            return
    except Exception:
        return
    try:
        getattr(obj, emitter_name).emit(*args)
    except RuntimeError:
        pass


@dataclass
class SessionRowsParseResult:
    """Prepared table rows and parsed molecules for chunked UI apply."""

    prepared_rows: list[tuple[int, dict[str, str]]] = field(default_factory=list)
    mols: dict[int, Any] = field(default_factory=dict)
    max_id: int = -1


class SessionRowsParseSignals(QObject):
    """Signals for :class:`SessionRowsParseWorker` (owned on the GUI thread)."""

    finished = pyqtSignal(object)
    failed = pyqtSignal(str)


class SessionRowsParseWorker(QRunnable):
    """Parse session row SMILES off the GUI thread."""

    def __init__(
        self,
        rows: list[dict],
        *,
        data_headers: list[str],
        signals: SessionRowsParseSignals,
        generation: int,
        structure_smiles: list[str] | None = None,
    ):
        super().__init__()
        self.setAutoDelete(True)
        self.rows = rows
        self.data_headers = list(data_headers)
        self.structure_smiles = list(structure_smiles or [])
        self.signals = signals
        self.generation = int(generation)

    def run(self) -> None:
        try:
            prepared: list[tuple[int, dict[str, str]]] = []
            mols: dict[int, Any] = {}
            max_id = -1
            headers = self.data_headers
            for i, entry in enumerate(self.rows):
                if not isinstance(entry, dict):
                    continue
                try:
                    oid = int(entry["id"])
                except (KeyError, TypeError, ValueError):
                    continue
                max_id = max(max_id, oid)
                cells = entry.get("cells") or {}
                if not isinstance(cells, dict):
                    cells = {}
                saved_smi = ""
                if i < len(self.structure_smiles):
                    saved_smi = str(self.structure_smiles[i] or "")
                smi = row_structure_smiles(cells, saved_smi)
                row_cells = {cname: str(cells.get(cname, "") or "") for cname in headers}
                prepared.append((oid, row_cells))
                if smi:
                    mol = Chem.MolFromSmiles(smi)
                    if mol is not None:
                        mols[oid] = mol
            _safe_emit(
                self.signals,
                "finished",
                SessionRowsParseResult(
                    prepared_rows=prepared,
                    mols=mols,
                    max_id=max_id,
                ),
            )
        except Exception as exc:
            _safe_emit(self.signals, "failed", str(exc) or "Session row parse failed.")
