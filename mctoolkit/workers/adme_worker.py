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

"""Background Predict ADME (ADMET-AI v2 Chemprop weights)."""

from __future__ import annotations

import contextlib
import logging
import threading
import time
from collections.abc import Callable

import shiboken6
from PySide6.QtCore import QObject, QRunnable, Signal

from ..predictions.adme_prediction import (
    adme_models_available,
    adme_needs_cuda_isolation,
    adme_stack_import_error,
    format_adme_row,
    mp_predict_adme_chunk,
    predict_adme_batch,
)
from .chemprop_cuda_pool import run_chemprop_chunked

logger = logging.getLogger(__name__)


def _safe_emit(obj, emitter_name: str, *args) -> None:
    if obj is None:
        return
    try:
        valid = shiboken6.isValid(obj)
    except (TypeError, AttributeError, RuntimeError):
        return
    if not valid:
        return
    with contextlib.suppress(RuntimeError):
        getattr(obj, emitter_name).emit(*args)


def _predict_in_cuda_child(
    smiles: list[str],
    batch_size: int,
    output_columns: tuple[str, ...],
    cancel_event: threading.Event | None,
    progress_callback: Callable[[int, int], None] | None,
) -> list[dict[str, float] | None]:
    return run_chemprop_chunked(
        mp_predict_adme_chunk,
        smiles,
        batch_size,
        extra_args=(output_columns,),
        cancel_event=cancel_event,
        progress_callback=progress_callback,
        fail_message=(
            "Predict ADME GPU worker failed. CUDA Chemprop cannot fall "
            "back to the GUI process; retry the job."
        ),
    )


def dispatch_adme_predict(
    smiles: list[str],
    *,
    output_columns: tuple[str, ...],
    batch_size: int,
    cancel_event: threading.Event | None = None,
    progress_callback: Callable[[int, int], None] | None = None,
) -> list[dict[str, float] | None]:
    """Run ADME in-process on CPU, or in the shared CUDA Chemprop child."""
    if adme_needs_cuda_isolation():
        return _predict_in_cuda_child(
            smiles,
            batch_size,
            output_columns,
            cancel_event,
            progress_callback,
        )
    return predict_adme_batch(
        smiles,
        output_columns=output_columns,
        batch_size=batch_size,
        progress_callback=progress_callback,
    )


class AdmePredictorSignals(QObject):
    """Emits from :class:`AdmePredictorWorker` (owned on the GUI thread)."""

    finished = Signal(list)  # list[tuple[int, dict[str, str]]]
    failed = Signal(str)


class AdmePredictorWorker(QRunnable):
    """Predict checked ADME endpoints per table row."""

    def __init__(
        self,
        rows: list[tuple[int, str]],
        worker_signals,
        adme_signals: AdmePredictorSignals,
        cancel_event: threading.Event | None = None,
        *,
        output_columns: tuple[str, ...],
        batch_size: int = 64,
        progress_state=None,
    ):
        super().__init__()
        self.rows = rows
        self.worker_signals = worker_signals
        self.adme_signals = adme_signals
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
        isolate = adme_needs_cuda_isolation()

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

        _emit_progress("Predict ADME…", force=True)

        if not isolate:
            err = adme_stack_import_error()
            if err:
                _safe_emit(self.adme_signals, "failed", err)
                return
        if not adme_models_available():
            _safe_emit(
                self.adme_signals,
                "failed",
                "ADME Chemprop weights are missing.\n"
                "Run: python scripts/bootstrap_adme_models.py\n"
                "See mctoolkit/resources/models/adme/README.md",
            )
            return

        oids: list[int] = []
        smiles: list[str] = []
        for oid, smi in self.rows:
            if cancel_ev is not None and cancel_ev.is_set():
                _safe_emit(self.adme_signals, "failed", "Cancelled.")
                return
            done += 1
            _emit_progress("Predict ADME…")
            text = (smi or "").strip()
            if text:
                oids.append(int(oid))
                smiles.append(text)

        if not smiles:
            _safe_emit(self.adme_signals, "finished", [])
            return

        _emit_progress("Running ADME models…", force=True)
        try:

            def _predict_progress(batch_done: int, batch_total: int) -> None:
                if cancel_ev is not None and cancel_ev.is_set():
                    return
                report_tool_progress(
                    message="Predict ADME…",
                    done=batch_done,
                    total=max(batch_total, 1),
                    progress_state=self.progress_state,
                    signals=self.worker_signals,
                    throttle=throttle,
                    force_signal=batch_done >= batch_total,
                )

            preds = dispatch_adme_predict(
                smiles,
                output_columns=self.output_columns,
                batch_size=self.batch_size,
                cancel_event=cancel_ev,
                progress_callback=_predict_progress,
            )
        except RuntimeError as e:
            logger.exception("ADME prediction failed")
            msg = str(e)
            if msg.lower() == "cancelled":
                _safe_emit(self.adme_signals, "failed", "Cancelled.")
            else:
                _safe_emit(self.adme_signals, "failed", f"Prediction failed: {e}")
            return
        except (OSError, ValueError, ImportError) as e:
            logger.exception("ADME prediction failed")
            _safe_emit(self.adme_signals, "failed", f"Prediction failed: {e}")
            return

        if cancel_ev is not None and cancel_ev.is_set():
            _safe_emit(self.adme_signals, "failed", "Cancelled.")
            return

        results: list[tuple[int, dict[str, str]]] = []
        for oid, pred in zip(oids, preds):
            row = format_adme_row(pred, self.output_columns)
            results.append((oid, row))

        done = tot
        _emit_progress("Predict ADME", force=True)
        _safe_emit(self.adme_signals, "finished", results)
