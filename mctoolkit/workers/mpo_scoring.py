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

"""Score MPO desirability columns off the GUI thread."""

from __future__ import annotations

import contextlib
import logging

from PySide6.QtCore import QObject, QRunnable, Signal

from ..analysis.mpo_scoring import CombineMethod, score_mpo_table

logger = logging.getLogger(__name__)


class MpoScoreSignals(QObject):
    finished = Signal(object, object)
    failed = Signal(str)


class MpoScoreWorker(QRunnable):
    """``score_mpo_table`` from a bulk column-text snapshot."""

    def __init__(
        self,
        oids: list[int],
        column_texts: dict[str, list[str]],
        specs,
        *,
        combine: CombineMethod,
        output_column: str,
        write_individual: bool,
        decimals: int,
        out_cols: list[str],
        signals: MpoScoreSignals,
    ) -> None:
        super().__init__()
        self.oids = list(oids)
        self.column_texts = column_texts
        self.specs = list(specs)
        self.combine = combine
        self.output_column = output_column
        self.write_individual = bool(write_individual)
        self.decimals = int(decimals)
        self.out_cols = list(out_cols)
        self.signals = signals

    def run(self) -> None:
        try:
            rows = score_mpo_table(
                self.oids,
                self.column_texts,
                self.specs,
                method=self.combine,
                output_column=self.output_column,
                write_individual=self.write_individual,
                decimals=self.decimals,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("MPO scoring failed")
            with contextlib.suppress(RuntimeError):
                self.signals.failed.emit(str(exc) or exc.__class__.__name__)
            return
        try:
            self.signals.finished.emit(rows, self.out_cols)
        except RuntimeError:
            logger.exception("MPO scoring finished signal failed")
