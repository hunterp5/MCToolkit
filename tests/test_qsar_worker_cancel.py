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
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with MolManager.  If not, see <https://www.gnu.org/licenses/>.

"""QSAR workers report cancellation via failed signal."""

from __future__ import annotations

import threading

from PySide6.QtCore import QObject

from molmanager.workers.qsar_worker import QSARSignals, QSARPredictWorker, QSARTrainWorker


class _Collector(QObject):
    def __init__(self) -> None:
        super().__init__()
        self.messages: list[str] = []

    def on_failed(self, msg: str) -> None:
        self.messages.append(msg)


def test_qsar_train_worker_emits_failed_when_cancelled_before_run() -> None:
    signals = QSARSignals()
    collector = _Collector()
    signals.failed.connect(collector.on_failed)
    cancel = threading.Event()
    cancel.set()
    worker = QSARTrainWorker({"oids": [1], "activity_column": "y"}, signals, cancel_event=cancel)
    worker.run()
    assert collector.messages == ["Cancelled."]


def test_qsar_predict_worker_emits_failed_when_cancelled_before_run() -> None:
    signals = QSARSignals()
    collector = _Collector()
    signals.failed.connect(collector.on_failed)
    cancel = threading.Event()
    cancel.set()
    worker = QSARPredictWorker(
        {"bundle": None, "oids": [], "dataframe": None}, signals, cancel_event=cancel
    )
    worker.run()
    assert collector.messages == ["Cancelled."]


def test_qsar_train_worker_reports_fitting_progress(monkeypatch) -> None:
    from molmanager.platform_support.tool_progress import ToolProgressState

    state = ToolProgressState()
    state.begin("QSAR", 3)
    snapshots: list[tuple[str, int, int]] = []

    def fake_fit(**_kwargs):
        msg, done, total, _active = state.snapshot()
        snapshots.append((msg, done, total))
        raise RuntimeError("stop-after-progress")

    monkeypatch.setattr("molmanager.workers.qsar_worker.fit_qsar_model", fake_fit)
    signals = QSARSignals()
    collector = _Collector()
    signals.failed.connect(collector.on_failed)
    worker = QSARTrainWorker(
        {
            "oids": [1, 2, 3],
            "activity_column": "y",
            "dataframe": None,
            "model_key": "ridge",
        },
        signals,
        progress_state=state,
    )
    worker.run()
    assert snapshots
    assert snapshots[0][0].startswith("QSAR: fitting")
    assert snapshots[0][2] == 3
    assert collector.messages
    assert "stop-after-progress" in collector.messages[0]
