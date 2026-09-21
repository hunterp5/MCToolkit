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
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with mctoolkit.  If not, see <https://www.gnu.org/licenses/>.

"""Fast Prepare worker: disconnect, optional neutralize, and depict in one parallel pass.

Fast Prepare used to run disconnect, neutralize, and Render 2D as separate queued jobs.
Chemistry is fused here, and when the Structure column is the target the same child process
draws the PNG so the GUI does not spawn a second RDKit pool. Neutralize is optional (off by
default). Results carry molecules as binary blobs and optional PNG bytes rather than live
``Chem.Mol`` objects.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from dataclasses import dataclass

from PySide6.QtCore import QRunnable
from rdkit import Chem

from ..chem.fragment_disconnect import largest_fragment_and_rest
from ..chem.structure_neutralize import neutralize_mol
from ..chem.molecule_conversion import mol_to_canonical_smiles, parse_molecule_from_cell_text
from .process_pool_utils import (
    register_process_pool,
    should_terminate_process_pool,
    shutdown_process_pool_executor,
)
from .signals import WorkerSignals, emit_partial_results_if_cancelled
from ..platform_support.tool_progress import ToolProgressState, report_tool_progress

logger = logging.getLogger(__name__)

PROGRESS_LABEL = "Preparing structures…"
TOOL_LABEL = "Fast prepare"


@dataclass(frozen=True)
class FastPrepareParams:
    """Job flags for :class:`FastPrepareWorker` (not the row payloads)."""

    is_smiles: bool = False
    need_smiles: bool = False
    neutralize: bool = False
    need_png: bool = False
    png_width: int = 0
    png_height: int = 0
    batch_size: int = 64
    process_pool_min_rows: int = 250


def _prepare_one(
    blob_or_text: bytes | str,
    source_text: str | None,
    *,
    is_text: bool,
    need_smiles: bool,
    neutralize: bool = False,
    need_png: bool = False,
    png_width: int = 0,
    png_height: int = 0,
) -> tuple[bytes, str, str, bytes] | None:
    """Disconnect the largest fragment, then optionally neutralize and depict it.

    Returns ``(mol_blob, smaller_fragments_text, canonical_smiles, png_bytes)``, or ``None`` when
    the row has no usable structure. If neutralization is requested and fails, the disconnected
    parent is kept. ``png_bytes`` is empty unless *need_png* is set.
    """
    if is_text:
        raw = str(blob_or_text or "").strip()
        mol = parse_molecule_from_cell_text(raw) if raw else None
        source_text = source_text or (raw or None)
    else:
        mol = Chem.Mol(blob_or_text) if blob_or_text else None
        if mol is None and source_text:
            mol = parse_molecule_from_cell_text(source_text)
    if mol is None:
        return None
    parent, fragments = largest_fragment_and_rest(mol, source_text)
    if parent is None:
        return None
    out = parent
    if neutralize and Chem.GetFormalCharge(parent) != 0:
        out = neutralize_mol(parent) or parent
    smiles = mol_to_canonical_smiles(out) if need_smiles else ""
    png = b""
    if need_png:
        from ..chem.structure_2d_depiction import render_molecule_png

        width = int(png_width) or 0
        height = int(png_height) or 0
        if width > 0 and height > 0:
            try:
                png = render_molecule_png(out, width, height) or b""
            except Exception:  # noqa: BLE001
                png = b""
    return out.ToBinary(), fragments, smiles, png


def _structure_payload_as_blob(payload) -> bytes:
    """Pickle a live mol, or pass through a blob the GUI already read from the store."""
    if isinstance(payload, (bytes, bytearray)):
        return bytes(payload)
    if payload is None:
        return b""
    try:
        raw = payload.ToBinary()
    except Exception:
        return b""
    return bytes(raw) if raw else b""


def _mp_fast_prepare_batch(args: tuple) -> list[tuple]:
    """Run :func:`_prepare_one` over one batch inside a child process (picklable args)."""
    items = args[0]
    is_text = args[1]
    need_smiles = args[2]
    neutralize = args[3]
    need_png = args[4] if len(args) > 4 else False
    png_width = args[5] if len(args) > 5 else 0
    png_height = args[6] if len(args) > 6 else 0
    out: list[tuple] = []
    for oid, payload, source_text in items:
        try:
            res = _prepare_one(
                payload,
                source_text,
                is_text=bool(is_text),
                need_smiles=bool(need_smiles),
                neutralize=bool(neutralize),
                need_png=bool(need_png),
                png_width=int(png_width or 0),
                png_height=int(png_height or 0),
            )
        except Exception:  # noqa: BLE001
            res = None
        if res is None:
            continue
        blob, fragments, smiles, png = res
        out.append((int(oid), blob, fragments, smiles, png))
    return out


class FastPrepareWorker(QRunnable):
    """Disconnect (and optionally neutralize) every row in ``items``, batched across child processes.

    ``items`` are ``(oid, mol, source_text)`` tuples, or ``(oid, cell_text)`` when
    ``params.is_smiles``. Emits ``signals.fast_prepared`` with
    ``(oid, mol_blob, fragments_text, canonical_smiles, png_bytes)`` rows.
    """

    def __init__(
        self,
        items: list,
        params: FastPrepareParams,
        signals: WorkerSignals,
        *,
        cancel_event: threading.Event | None = None,
        progress_state: ToolProgressState | None = None,
    ):
        super().__init__()
        self.items = list(items)
        self.params = params
        self.signals = signals
        self.cancel_event = cancel_event
        self.progress_state = progress_state
        self._progress_throttle = [0, 0.0]

    def _emit_progress(self, done: int, total: int) -> None:
        report_tool_progress(
            message=PROGRESS_LABEL,
            done=int(done),
            total=int(total),
            progress_state=self.progress_state,
            signals=self.signals,
            throttle=self._progress_throttle,
        )

    def _tasks(self) -> list[tuple[int, object, str | None]]:
        """Serialize input rows into picklable ``(oid, payload, source_text)`` tuples."""
        tasks: list[tuple[int, object, str | None]] = []
        for row in self.items:
            oid = int(row[0])
            if self.params.is_smiles:
                tasks.append((oid, str(row[1] or ""), None))
                continue
            payload = row[1]
            source_text = (str(row[2]).strip() or None) if len(row) >= 3 and row[2] else None
            tasks.append((oid, _structure_payload_as_blob(payload), source_text))
        return tasks

    def run(self) -> None:
        tasks = self._tasks()
        total = max(len(tasks), 1)
        if not tasks:
            self.signals.fast_prepared.emit([])
            return

        p = self.params
        batch_size = max(1, int(p.batch_size))
        batches = [
            (
                tasks[s : s + batch_size],
                p.is_smiles,
                p.need_smiles,
                p.neutralize,
                p.need_png,
                p.png_width,
                p.png_height,
            )
            for s in range(0, len(tasks), batch_size)
        ]
        if p.need_png:
            from .load_render import render2d_process_worker_count

            workers = render2d_process_worker_count()
        else:
            workers = min(8, max(2, (os.cpu_count() or 4) - 1), 6)
        use_pool = len(tasks) >= max(2, int(p.process_pool_min_rows)) and workers > 1

        results: list[tuple] = []
        done = 0
        cancelled = False
        self._emit_progress(0, total)

        if use_pool:
            try:
                results, done, cancelled = self._run_pool(batches, total, workers)
            except Exception:
                logger.exception("Process-pool fast prepare failed; falling back to in-process")
                results, done, cancelled = [], 0, False
                use_pool = False
        if not use_pool:
            results, done, cancelled = self._run_inline(batches, total)

        self._emit_progress(done, total)
        emit_partial_results_if_cancelled(self.signals, TOOL_LABEL, len(results), total, cancelled)
        self.signals.fast_prepared.emit(results)

    def _run_pool(self, batches: list[tuple], total: int, workers: int):
        """Batch the work across child processes, streaming progress as futures land."""
        max_inflight = min(48, max(workers * 4, workers))
        it = iter(batches)
        pending: set = set()
        results: list[tuple] = []
        done = 0
        cancelled = False
        ev = self.cancel_event
        ex = register_process_pool(ProcessPoolExecutor(max_workers=workers))

        def _fill() -> None:
            while len(pending) < max_inflight:
                nxt = next(it, None)
                if nxt is None:
                    break
                pending.add(ex.submit(_mp_fast_prepare_batch, nxt))

        try:
            _fill()
            last_pulse = 0.0
            while pending:
                if should_terminate_process_pool(ev):
                    cancelled = True
                    for f in list(pending):
                        f.cancel()
                    break
                completed, pending = wait(pending, timeout=0.2, return_when=FIRST_COMPLETED)
                for f in completed:
                    if f.cancelled():
                        continue
                    try:
                        rows = f.result()
                    except Exception:
                        logger.exception("Fast prepare subprocess batch failed")
                        continue
                    results.extend(rows)
                    done += len(rows)
                if completed:
                    self._emit_progress(min(done, total), total)
                elif pending:
                    now = time.monotonic()
                    if now - last_pulse >= 0.55:
                        last_pulse = now
                        self._emit_progress(min(done, total), total)
                _fill()
        finally:
            shutdown_process_pool_executor(ex, kill_workers=should_terminate_process_pool(ev))
        return results, done, cancelled

    def _run_inline(self, batches: list[tuple], total: int):
        """Same work in this thread — used for small jobs and as a process-pool fallback."""
        results: list[tuple] = []
        done = 0
        cancelled = False
        for batch in batches:
            if self.cancel_event is not None and self.cancel_event.is_set():
                cancelled = True
                break
            rows = _mp_fast_prepare_batch(batch)
            results.extend(rows)
            done += len(batch[0])
            self._emit_progress(min(done, total), total)
        return results, done, cancelled
