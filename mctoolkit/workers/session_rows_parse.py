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

"""Background SMILES parsing for session document and legacy CSV restore."""

from __future__ import annotations

from collections.abc import Callable
import csv
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

import shiboken6
from PySide6.QtCore import QObject, QRunnable, Signal
from rdkit import Chem

from ..platform_support.env import env_get
from ..platform_support.tool_progress import throttled_progress_should_emit
from ..table.session_codec import decode_mol_blob_b64, row_structure_smiles
from ..table.table_file_formats import ByteCountReader, uncompressed_file_size

_SERIAL_MOL_DECODE_MAX = 32
_MAX_MOL_DECODE_WORKERS = 8
_SESSION_READ_CHUNK = 1 << 20


def mol_from_session_blob(blob: bytes | None, smiles: str = "") -> Chem.Mol | None:
    """Rebuild a structure from an RDKit pickle blob, then SMILES if needed."""
    if blob:
        try:
            mol = Chem.Mol(blob)
            if mol is not None:
                return mol
        except Exception:
            pass
    smi = (smiles or "").strip()
    if not smi:
        return None
    try:
        return Chem.MolFromSmiles(smi)
    except Exception:
        return None


def decode_session_mols(jobs: list[tuple[int, bytes | None, str]]) -> dict[int, Any]:
    """Decode session structure blobs. Threads are opt-in; RDKit pickle is usually GIL-bound."""
    mols: dict[int, Any] = {}
    if not jobs:
        return mols
    n = len(jobs)
    workers = _session_mol_decode_workers(n)
    if n <= _SERIAL_MOL_DECODE_MAX or workers <= 1:
        for oid, blob, smi in jobs:
            mol = mol_from_session_blob(blob, smi)
            if mol is not None:
                mols[oid] = mol
        return mols
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(mol_from_session_blob, blob, smi) for _oid, blob, smi in jobs]
        for (oid, _blob, _smi), fut in zip(jobs, futures, strict=True):
            mol = fut.result()
            if mol is not None:
                mols[oid] = mol
    return mols


def _session_mol_decode_workers(n: int) -> int:
    raw = (env_get("MCTOOLKIT_SESSION_MOL_WORKERS") or "").strip()
    if not raw:
        return 1
    try:
        requested = int(raw)
    except ValueError:
        return 1
    if requested <= 1:
        return 1
    cpu = os.cpu_count() or 1
    return max(1, min(_MAX_MOL_DECODE_WORKERS, cpu, n, requested))


def _safe_emit(obj: QObject | None, emitter_name: str, *args) -> None:
    if obj is None:
        return
    try:
        if not shiboken6.isValid(obj):
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
    mol_jobs: list[tuple[int, bytes | None, str]] = field(default_factory=list)
    max_id: int = -1

    @property
    def mols(self) -> dict[int, Any]:
        return decode_session_mols(self.mol_jobs)


def prepare_session_rows(
    rows: list[dict],
    *,
    data_headers: list[str],
    structure_smiles: list[str] | None = None,
    structure_mols: list[str] | None = None,
    on_progress: Callable[[str, int, int], None] | None = None,
) -> SessionRowsParseResult:
    """Turn expanded session rows into table cells and mol-store jobs."""
    prepared: list[tuple[int, dict[str, str]]] = []
    jobs: list[tuple[int, bytes | None, str]] = []
    max_id = -1
    headers = list(data_headers)
    smiles_list = list(structure_smiles or [])
    mols_list = list(structure_mols or [])
    n_rows = len(rows)
    throttle: list = [0, 0.0]
    for i, entry in enumerate(rows):
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
        if i < len(smiles_list):
            saved_smi = str(smiles_list[i] or "")
        smi = row_structure_smiles(cells, saved_smi)
        row_cells = {cname: str(cells.get(cname, "") or "") for cname in headers}
        prepared.append((oid, row_cells))
        blob = None
        if i < len(mols_list):
            blob = decode_mol_blob_b64(mols_list[i])
        jobs.append((oid, blob, smi))
        if (
            on_progress is not None
            and n_rows
            and throttled_progress_should_emit(i + 1, n_rows, throttle)
        ):
            on_progress("Parsing structures…", i + 1, n_rows)
    if on_progress is not None and n_rows:
        on_progress("Parsing structures…", n_rows, n_rows)
    return SessionRowsParseResult(prepared_rows=prepared, mol_jobs=jobs, max_id=max_id)


@dataclass
class SessionOpenResult:
    """Decoded session document plus prepared table rows from a file-open worker."""

    doc: dict
    parse: SessionRowsParseResult | None = None


@dataclass
class CsvSessionParseResult:
    """Prepared rows from a legacy session CSV (SMILES + property columns)."""

    columns: list[str] = field(default_factory=list)
    prepared_rows: list[tuple[int, dict[str, str]]] = field(default_factory=list)
    mol_blobs: dict[int, bytes] = field(default_factory=dict)
    next_oid: int = 0

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


class SessionRowsParseSignals(QObject):
    """Signals for session row parse workers (owned on the GUI thread)."""

    finished = Signal(object)
    failed = Signal(str)
    progress = Signal(str, int, int)


def _progress_emitter(signals: SessionRowsParseSignals | None):
    """Queue overlay progress from a parse worker onto the GUI thread."""

    def _emit(message: str, done: int, total: int) -> None:
        _safe_emit(signals, "progress", str(message or ""), int(done), int(total))

    return _emit


class SessionRowsParseWorker(QRunnable):
    """Load session structures off the GUI thread (mol binary first, SMILES fallback)."""

    def __init__(
        self,
        rows: list[dict],
        *,
        data_headers: list[str],
        signals: SessionRowsParseSignals,
        generation: int,
        structure_smiles: list[str] | None = None,
        structure_mols: list[str] | None = None,
    ):
        super().__init__()
        self.setAutoDelete(True)
        self.rows = rows
        self.data_headers = list(data_headers)
        self.structure_smiles = list(structure_smiles or [])
        self.structure_mols = list(structure_mols or [])
        self.signals = signals
        self.generation = int(generation)

    def run(self) -> None:
        try:
            result = prepare_session_rows(
                list(self.rows),
                data_headers=list(self.data_headers),
                structure_smiles=list(self.structure_smiles),
                structure_mols=list(self.structure_mols),
                on_progress=_progress_emitter(self.signals),
            )
            _safe_emit(self.signals, "finished", result)
        except Exception as exc:
            _safe_emit(self.signals, "failed", str(exc) or "Session row parse failed.")


class SessionOpenWorker(QRunnable):
    """Read, decode, expand, and prepare session rows off the GUI thread."""

    def __init__(self, path: str, signals: SessionRowsParseSignals, generation: int):
        super().__init__()
        self.setAutoDelete(True)
        self.path = str(path)
        self.signals = signals
        self.generation = int(generation)

    def run(self) -> None:
        try:
            from ..table.session_codec import expand_session_document, loads_session_bytes

            emit = _progress_emitter(self.signals)
            size = 0
            try:
                size = int(os.path.getsize(self.path))
            except OSError:
                size = 0
            chunks: list[bytes] = []
            n = 0
            throttle: list = [0, 0.0]
            with open(self.path, "rb") as handle:
                while True:
                    block = handle.read(_SESSION_READ_CHUNK)
                    if not block:
                        break
                    chunks.append(block)
                    n += len(block)
                    if size > 0 and throttled_progress_should_emit(n, size, throttle):
                        emit("Reading session…", n, size)
            if size > 0:
                emit("Reading session…", n, size)
            emit("Decoding session…", 0, -1)
            raw = b"".join(chunks)
            doc = expand_session_document(loads_session_bytes(raw))
            headers = doc.get("headers") or ["ID_HIDDEN", "Structure", "SMILES"]
            rows = doc.get("rows") or []
            parse = prepare_session_rows(
                list(rows),
                data_headers=list(headers[2:]) if isinstance(headers, list) else [],
                structure_smiles=list(doc.get("structure_smiles") or []),
                structure_mols=list(doc.get("structure_mols") or []),
                on_progress=emit,
            )
            _safe_emit(self.signals, "finished", SessionOpenResult(doc=doc, parse=parse))
        except Exception as exc:
            _safe_emit(self.signals, "failed", str(exc) or "Could not read session file.")


class CsvSessionParseWorker(QRunnable):
    """Read a legacy session CSV and parse SMILES off the GUI thread."""

    def __init__(self, path: str, signals: SessionRowsParseSignals, generation: int):
        super().__init__()
        self.setAutoDelete(True)
        self.path = str(path)
        self.signals = signals
        self.generation = int(generation)

    def run(self) -> None:
        try:
            emit = _progress_emitter(self.signals)
            size = uncompressed_file_size(self.path)
            with open(self.path, "r", encoding="utf-8", errors="replace", newline="") as raw:
                if size > 0:
                    handle = ByteCountReader(
                        raw,
                        size=size,
                        on_progress=lambda d, t: emit("Reading session…", d, t),
                    )
                else:
                    handle = raw
                reader = csv.DictReader(handle)
                cols = list(reader.fieldnames or [])
                if "SMILES" not in cols:
                    cols = ["SMILES"] + cols
                prepared: list[tuple[int, dict[str, str]]] = []
                mol_blobs: dict[int, bytes] = {}
                oid = 0
                for row in reader:
                    smi = (row.get("SMILES", "") or "").strip()
                    row_cells = {c: str(row.get(c, "") or "") for c in cols}
                    prepared.append((oid, row_cells))
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
            if size > 0:
                emit("Reading session…", size, size)
            _safe_emit(
                self.signals,
                "finished",
                CsvSessionParseResult(
                    columns=cols,
                    prepared_rows=prepared,
                    mol_blobs=mol_blobs,
                    next_oid=oid,
                ),
            )
        except Exception as exc:
            _safe_emit(self.signals, "failed", str(exc) or "Session CSV parse failed.")
