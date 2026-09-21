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

"""Background BOILED-Egg / golden-triangle dataset builds."""

from __future__ import annotations

import shiboken6
from PySide6.QtCore import QObject, QRunnable, Signal

from ..analysis.medchem_space import build_medchem_space_result


def _safe_emit(obj, emitter_name: str, *args) -> None:
    """Emit if the signals QObject still exists (avoids close/dock races)."""
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


class MedChemSpaceSignals(QObject):
    finished = Signal(object)
    failed = Signal(str)


class MedChemSpaceWorker(QRunnable):
    def __init__(
        self,
        params: dict,
        signals: MedChemSpaceSignals,
        *,
        cancel_event=None,
    ):
        super().__init__()
        self.params = dict(params)
        self.signals = signals
        self.cancel_event = cancel_event

    def run(self) -> None:
        try:
            if self.cancel_event is not None and self.cancel_event.is_set():
                return
            snapshots = list(self.params.get("snapshots") or [])
            result = build_medchem_space_result(
                snapshots,
                plot_kind=str(self.params.get("plot_kind") or "boiled_egg"),
                tpsa_col=self.params.get("tpsa_col"),
                logp_col=self.params.get("logp_col"),
                mw_col=self.params.get("mw_col"),
                wlogp_col=self.params.get("wlogp_col"),
                use_table_columns_only=bool(self.params.get("use_table_columns_only")),
                max_plot_points=self.params.get("max_plot_points"),
                oid_smiles=dict(self.params.get("oid_smiles") or {}),
                progress_state=self.params.get("progress_state"),
                progress_label=str(self.params.get("progress_label") or "Medchem plot"),
                cancel_event=self.cancel_event,
            )
            if self.cancel_event is not None and self.cancel_event.is_set():
                return
            _safe_emit(self.signals, "finished", result)
        except Exception as exc:
            from ..analysis.medchem_space import MedChemSpaceCancelled

            if isinstance(exc, MedChemSpaceCancelled):
                return
            _safe_emit(self.signals, "failed", str(exc) or exc.__class__.__name__)
