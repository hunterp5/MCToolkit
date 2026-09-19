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

"""Fetch SQL rows and parse SMILES off the GUI thread."""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Any

from PyQt5 import sip
from PyQt5.QtCore import QObject, QRunnable, pyqtSignal
from rdkit import Chem

from ..exception_policy import log_swallowed_exception
from ..tool_progress import ToolProgressState, report_tool_progress

logger = logging.getLogger(__name__)


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
class SqlLoadParseResult:
    """Prepared table rows and parsed molecules for chunked UI apply."""

    columns: list[str] = field(default_factory=list)
    prepared_rows: list[tuple[int, dict[str, str]]] = field(default_factory=list)
    mol_blobs: dict[int, bytes] = field(default_factory=dict)
    next_oid: int = 0
    rows_hit_limit: bool = False
    limit_eff: int = 0
    smiles_column: str | None = None

    @property
    def mols(self) -> dict[int, Any]:
        out: dict[int, Any] = {}
        for oid, blob in self.mol_blobs.items():
            try:
                mol = Chem.Mol(blob)
            except Exception:
                continue
            if mol is not None:
                out[int(oid)] = mol
        return out


class SqlLoadSignals(QObject):
    """Signals for SQL load workers (owned on the GUI thread)."""

    finished = pyqtSignal(object)
    failed = pyqtSignal(str)


class SqlLoadWorker(QRunnable):
    """Stream a SQL result set and parse SMILES away from the GUI thread."""

    def __init__(
        self,
        *,
        url: str,
        engine_kwargs: dict,
        sql: str,
        page_size: int,
        limit_eff: int,
        apply_limit: bool,
        signals: SqlLoadSignals,
        generation: int,
        cancel_event: threading.Event | None = None,
        progress_state: ToolProgressState | None = None,
    ):
        super().__init__()
        self.setAutoDelete(True)
        self.url = str(url)
        self.engine_kwargs = dict(engine_kwargs or {})
        self.sql = str(sql)
        self.page_size = max(32, int(page_size))
        self.limit_eff = max(0, int(limit_eff))
        self.apply_limit = bool(apply_limit)
        self.signals = signals
        self.generation = int(generation)
        self.cancel_event = cancel_event
        self.progress_state = progress_state
        self._progress_throttle = [0, 0.0]

    def _cancelled(self) -> bool:
        return self.cancel_event is not None and self.cancel_event.is_set()

    def _emit_progress(self, done: int, total: int) -> None:
        report_tool_progress(
            message="SQL load: fetching…",
            done=int(done),
            total=max(1, int(total)),
            progress_state=self.progress_state,
            throttle=self._progress_throttle,
        )

    def run(self) -> None:
        if self._cancelled():
            _safe_emit(self.signals, "failed", "Cancelled.")
            return
        try:
            from sqlalchemy import create_engine, text
        except Exception as exc:
            _safe_emit(
                self.signals,
                "failed",
                "sqlalchemy is required for SQL loading. Install requirements-core.txt "
                f"(or requirements.txt). ({exc})",
            )
            return

        eng = None
        try:
            eng = create_engine(self.url, **self.engine_kwargs)
            with eng.connect() as conn:
                if self._cancelled():
                    _safe_emit(self.signals, "failed", "Cancelled.")
                    return
                rs = conn.execution_options(stream_results=True).execute(text(self.sql))
                cols = [str(c) for c in rs.keys()]
                if not cols:
                    rs.close()
                    _safe_emit(self.signals, "failed", "Query returned 0 rows.")
                    return

                smiles_col = next((c for c in cols if c.lower() == "smiles"), None)
                prepared: list[tuple[int, dict[str, str]]] = []
                mol_blobs: dict[int, bytes] = {}
                oid = 0
                rows_hit_limit = False
                progress_total = self.limit_eff if self.apply_limit and self.limit_eff > 0 else 0
                self._emit_progress(0, progress_total if progress_total > 0 else 1)

                while True:
                    if self._cancelled():
                        try:
                            rs.close()
                        except Exception:
                            log_swallowed_exception(logger, "SQL load cancel: close result")
                        _safe_emit(self.signals, "failed", "Cancelled.")
                        return
                    chunk = rs.fetchmany(self.page_size)
                    if not chunk:
                        break
                    for rec in chunk:
                        row_cells: dict[str, str] = {}
                        for c in cols:
                            v = rec._mapping.get(c)
                            row_cells[c] = "" if v is None else str(v)
                        prepared.append((oid, row_cells))
                        if smiles_col is not None:
                            smi = (row_cells.get(smiles_col, "") or "").strip()
                            if smi:
                                mol = Chem.MolFromSmiles(smi)
                                if mol is not None:
                                    try:
                                        blob = mol.ToBinary()
                                    except Exception:
                                        blob = None
                                    if blob:
                                        mol_blobs[oid] = bytes(blob)
                        oid += 1
                        if self.apply_limit and self.limit_eff and oid >= self.limit_eff:
                            rows_hit_limit = True
                            break
                    total_ui = progress_total if progress_total > 0 else max(oid, 1)
                    self._emit_progress(oid, total_ui)
                    if rows_hit_limit:
                        break
                rs.close()

            if oid <= 0:
                _safe_emit(self.signals, "failed", "Query returned 0 rows.")
                return
            if self._cancelled():
                _safe_emit(self.signals, "failed", "Cancelled.")
                return

            self._emit_progress(oid, oid)
            _safe_emit(
                self.signals,
                "finished",
                SqlLoadParseResult(
                    columns=cols,
                    prepared_rows=prepared,
                    mol_blobs=mol_blobs,
                    next_oid=oid,
                    rows_hit_limit=rows_hit_limit,
                    limit_eff=self.limit_eff,
                    smiles_column=smiles_col,
                ),
            )
        except Exception as exc:
            logger.exception("SQL load failed")
            _safe_emit(self.signals, "failed", str(exc) or exc.__class__.__name__)
        finally:
            if eng is not None:
                try:
                    eng.dispose()
                except Exception:
                    log_swallowed_exception(logger, "SQL load engine dispose failed")
