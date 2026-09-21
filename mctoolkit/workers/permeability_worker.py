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

"""Background GNN-MTL permeability / efflux prediction (Chemprop)."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable

import shiboken6
from PySide6.QtCore import QObject, QRunnable, Signal

from ..predictions.permeability_prediction import (
    format_permeability_row,
    mp_predict_permeability_chunk,
    permeability_model_available,
    permeability_needs_cuda_isolation,
    permeability_stack_import_error,
    predict_permeability_batch,
)
from .chemprop_cuda_pool import (
    chunk_smiles,
    discard_chemprop_process_pool,
    run_chemprop_chunked,
)

logger = logging.getLogger(__name__)

discard_permeability_process_pool = discard_chemprop_process_pool
_chunk_smiles = chunk_smiles


def _safe_emit(obj, emitter_name: str, *args) -> None:
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


def _predict_in_cuda_child(
    smiles: list[str],
    batch_size: int,
    cancel_event: threading.Event | None,
    progress_callback: Callable[[int, int], None] | None,
) -> list[dict[str, float] | None]:
    """Run Chemprop in a child process so CUDA never initializes in the GUI."""
    return run_chemprop_chunked(
        mp_predict_permeability_chunk,
        smiles,
        batch_size,
        cancel_event=cancel_event,
        progress_callback=progress_callback,
        fail_message=(
            "Predict Permeability GPU worker failed. CUDA Chemprop cannot fall "
            "back to the GUI process; retry the job."
        ),
    )


def dispatch_permeability_predict(
    smiles: list[str],
    *,
    batch_size: int,
    cancel_event: threading.Event | None = None,
    progress_callback: Callable[[int, int], None] | None = None,
) -> list[dict[str, float] | None]:
    """Run GNN-MTL in-process on CPU, or in a CUDA child when the torch wheel is CUDA."""
    if permeability_needs_cuda_isolation():
        return _predict_in_cuda_child(
            smiles,
            batch_size,
            cancel_event,
            progress_callback,
        )
    return predict_permeability_batch(
        smiles,
        batch_size=batch_size,
        progress_callback=progress_callback,
    )


class PermeabilityPredictorSignals(QObject):
    """Emits from :class:`PermeabilityPredictorWorker` (owned on the GUI thread)."""

    finished = Signal(list)  # list[tuple[int, dict[str, str]]]
    failed = Signal(str)


class PermeabilityPredictorWorker(QRunnable):
    """Predict GNN-MTL endpoints per table row; writes via ``finished`` on the GUI thread."""

    def __init__(
        self,
        rows: list[tuple[int, str]],
        worker_signals,
        permeability_signals: PermeabilityPredictorSignals,
        cancel_event: threading.Event | None = None,
        *,
        output_columns: tuple[str, ...],
        batch_size: int = 64,
        progress_state=None,
    ):
        super().__init__()
        self.rows = rows
        self.worker_signals = worker_signals
        self.permeability_signals = permeability_signals
        self.cancel_event = cancel_event
        self.output_columns = output_columns
        self.batch_size = batch_size
        self.progress_state = progress_state

    def run(self) -> None:
        from ..platform_support.tool_progress import report_tool_progress

        cancel_ev = self.cancel_event
        tot = max(len(self.rows), 1)
        done = 0
        prog_last = 0.0
        throttle = [0, 0.0]
        isolate = permeability_needs_cuda_isolation()

        def _emit_progress(message: str, *, force: bool = False) -> None:
            nonlocal prog_last
            now = time.monotonic()
            if force or done >= tot or (now - prog_last) >= 0.12:
                prog_last = now
                report_tool_progress(
                    message=message,
                    done=min(done, tot),
                    total=tot,
                    progress_state=self.progress_state,
                    signals=self.worker_signals,
                    throttle=throttle,
                    force_signal=force,
                )

        _emit_progress("Predict Permeability…", force=True)

        if not isolate:
            err = permeability_stack_import_error()
            if err:
                _safe_emit(self.permeability_signals, "failed", err)
                return
        if not permeability_model_available():
            _safe_emit(
                self.permeability_signals,
                "failed",
                "GNN-MTL model file (model.pt) is missing.\n"
                "Run: python scripts/bootstrap_gnn_mtl_model.py\n"
                "See mctoolkit/resources/models/gnn_mtl/README.md",
            )
            return

        oids: list[int] = []
        smiles: list[str] = []
        for oid, smi in self.rows:
            if cancel_ev is not None and cancel_ev.is_set():
                _safe_emit(self.permeability_signals, "failed", "Cancelled.")
                return
            done += 1
            _emit_progress("Predict Permeability…")
            text = (smi or "").strip()
            if text:
                oids.append(int(oid))
                smiles.append(text)

        if not smiles:
            _safe_emit(self.permeability_signals, "finished", [])
            return

        _emit_progress("Running GNN-MTL model…", force=True)
        try:

            def _predict_progress(batch_done: int, batch_total: int) -> None:
                if cancel_ev is not None and cancel_ev.is_set():
                    return
                report_tool_progress(
                    message="Predict Permeability…",
                    done=batch_done,
                    total=max(batch_total, 1),
                    progress_state=self.progress_state,
                    signals=self.worker_signals,
                    throttle=throttle,
                    force_signal=batch_done >= batch_total,
                )

            preds = dispatch_permeability_predict(
                smiles,
                batch_size=self.batch_size,
                cancel_event=cancel_ev,
                progress_callback=_predict_progress,
            )
        except RuntimeError as e:
            logger.exception("Permeability prediction failed")
            msg = str(e)
            if msg.lower() == "cancelled":
                _safe_emit(self.permeability_signals, "failed", "Cancelled.")
            else:
                _safe_emit(self.permeability_signals, "failed", f"Prediction failed: {e}")
            return
        except Exception as e:
            logger.exception("Permeability prediction failed")
            _safe_emit(self.permeability_signals, "failed", f"Prediction failed: {e}")
            return

        if cancel_ev is not None and cancel_ev.is_set():
            _safe_emit(self.permeability_signals, "failed", "Cancelled.")
            return

        results: list[tuple[int, dict[str, str]]] = []
        for oid, pred in zip(oids, preds):
            row = format_permeability_row(pred, self.output_columns)
            results.append((oid, row))

        done = tot
        _emit_progress("Predict Permeability", force=True)
        _safe_emit(self.permeability_signals, "finished", results)
