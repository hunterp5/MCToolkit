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

"""Background QSAR training and prediction."""

from __future__ import annotations

import logging
import threading

from PySide6.QtCore import QObject, QRunnable, Signal

from ..platform_support.exception_policy import log_swallowed_exception
from ..analysis.qsar_models import fit_qsar_model, predict_qsar_rows
from ..platform_support.tool_progress import ToolProgressState, report_tool_progress

logger = logging.getLogger(__name__)


def _emit_qsar_cancelled(signals: QSARSignals) -> None:
    try:
        signals.failed.emit("Cancelled.")
    except Exception:
        log_swallowed_exception(logger, "QSAR cancel signal emit failed")


class QSARSignals(QObject):
    train_finished = Signal(object)
    predict_finished = Signal(list)
    failed = Signal(str)


class QSARTrainWorker(QRunnable):
    """Fit a QSAR model off the GUI thread."""

    def __init__(
        self,
        params: dict,
        signals: QSARSignals,
        cancel_event: threading.Event | None = None,
        progress_state: ToolProgressState | None = None,
    ):
        super().__init__()
        self.params = dict(params)
        self.signals = signals
        self.cancel_event = cancel_event
        self.progress_state = progress_state

    def run(self) -> None:
        if self.cancel_event is not None and self.cancel_event.is_set():
            _emit_qsar_cancelled(self.signals)
            return
        try:
            oids = list(self.params["oids"])
            n = max(1, len(oids))
            report_tool_progress(
                message="QSAR: fitting…",
                done=0,
                total=n,
                progress_state=self.progress_state,
            )
            use_fp = bool(self.params.get("use_fingerprints"))
            result = fit_qsar_model(
                df=self.params["dataframe"],
                oids=oids,
                activity_column=str(self.params["activity_column"]),
                feature_columns=self.params.get("feature_columns"),
                fp_choice=self.params.get("fp_choice") if use_fp else None,
                mol_rows=self.params.get("mol_rows") if use_fp else None,
                model_key=str(self.params["model_key"]),
                task_mode=str(self.params.get("task_mode") or "auto"),
                train_fraction=float(self.params.get("train_fraction", 0.8)),
                cv_folds=int(self.params.get("cv_folds", 5)),
                standardize=bool(self.params.get("standardize", True)),
                model_params=self.params.get("model_params"),
            )
            if self.cancel_event is not None and self.cancel_event.is_set():
                _emit_qsar_cancelled(self.signals)
                return
            report_tool_progress(
                message="QSAR: done",
                done=n,
                total=n,
                progress_state=self.progress_state,
            )
            self.signals.train_finished.emit(result)
        except Exception as exc:
            logger.exception("QSAR training failed")
            try:
                self.signals.failed.emit(str(exc) or exc.__class__.__name__)
            except Exception:
                log_swallowed_exception(logger, "QSAR train failed-signal emit failed")


class QSARPredictWorker(QRunnable):
    """Apply a fitted QSAR model to in-scope rows."""

    def __init__(
        self,
        params: dict,
        signals: QSARSignals,
        cancel_event: threading.Event | None = None,
        progress_state: ToolProgressState | None = None,
    ):
        super().__init__()
        self.params = dict(params)
        self.signals = signals
        self.cancel_event = cancel_event
        self.progress_state = progress_state

    def run(self) -> None:
        if self.cancel_event is not None and self.cancel_event.is_set():
            _emit_qsar_cancelled(self.signals)
            return
        try:
            oids = list(self.params["oids"])
            n = max(1, len(oids))
            report_tool_progress(
                message="QSAR predictions: scoring…",
                done=0,
                total=n,
                progress_state=self.progress_state,
            )
            bundle = self.params["bundle"]
            rows = predict_qsar_rows(
                bundle,
                df=self.params["dataframe"],
                oids=oids,
                mol_rows=self.params.get("mol_rows"),
                output_column=self.params.get("output_column"),
            )
            if self.cancel_event is not None and self.cancel_event.is_set():
                _emit_qsar_cancelled(self.signals)
                return
            report_tool_progress(
                message="QSAR predictions: done",
                done=n,
                total=n,
                progress_state=self.progress_state,
            )
            self.signals.predict_finished.emit(rows)
        except Exception as exc:
            logger.exception("QSAR prediction failed")
            try:
                self.signals.failed.emit(str(exc) or exc.__class__.__name__)
            except Exception:
                log_swallowed_exception(logger, "QSAR predict failed-signal emit failed")
