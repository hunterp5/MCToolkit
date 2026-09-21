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

"""Build analysis DataFrames off the GUI thread."""

from __future__ import annotations

import contextlib
import logging

import pandas as pd
from PySide6.QtCore import QObject, QRunnable, Signal

logger = logging.getLogger(__name__)


def _numeric_subset(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    cols = [c for c in df.columns if c != "ID_HIDDEN"]
    num = df[cols].apply(pd.to_numeric, errors="coerce")
    keep = [c for c in num.columns if num[c].notna().any()]
    return num[keep] if keep else pd.DataFrame(index=df.index)


class TableDataFrameSignals(QObject):
    finished = Signal(object, object, object)
    failed = Signal(str)


class TableDataFrameWorker(QRunnable):
    """``pd.DataFrame`` + numeric subset from a column-text snapshot."""

    def __init__(
        self,
        columns: dict[str, list[str]],
        source_rows: list[int],
        signals: TableDataFrameSignals,
        *,
        job_gen: int = 0,
    ) -> None:
        super().__init__()
        self.columns = columns
        self.source_rows = list(source_rows)
        self.signals = signals
        self.job_gen = int(job_gen)

    def run(self) -> None:
        try:
            df = pd.DataFrame(self.columns, copy=False)
            numeric = _numeric_subset(df)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Table DataFrame build failed")
            with contextlib.suppress(RuntimeError):
                self.signals.failed.emit(str(exc) or exc.__class__.__name__)
            return
        try:
            self.signals.finished.emit(df, self.source_rows, numeric)
        except RuntimeError:
            logger.exception("Table DataFrame finished signal failed")
