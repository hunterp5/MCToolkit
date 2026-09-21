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

"""BRICS / RECAP fragment recomposition workers (Tools menu)."""

from __future__ import annotations

import threading

from PySide6.QtCore import QRunnable

from ..chem.fragment_decomposition import RecompositionMethod, recompose_fragments
from .signals import WorkerSignals, emit_partial_results_if_cancelled


class FragmentRecompositionWorker(QRunnable):
    """Build new molecules from pooled fragment SMILES columns."""

    def __init__(
        self,
        fragment_smiles: list[str],
        method: RecompositionMethod,
        max_depth: int,
        max_products: int,
        tool_title: str,
        signals: WorkerSignals,
        *,
        output_filters: str = "",
        cancel_event: threading.Event | None = None,
        progress_state=None,
    ):
        super().__init__()
        self.fragment_smiles = list(fragment_smiles)
        self.method = method
        self.max_depth = int(max_depth)
        self.max_products = int(max_products)
        self.output_filters = str(output_filters or "")
        self.tool_title = tool_title
        self.signals = signals
        self.cancel_event = cancel_event
        self.progress_state = progress_state

    def run(self) -> None:
        ev = self.cancel_event
        if ev is not None and ev.is_set():
            self._finish_cancelled([], 0)
            return
        from ..platform_support.tool_progress import report_tool_progress

        label = self.tool_title
        target = max(1, int(self.max_products))
        throttle = [0, 0.0]

        def on_progress(accepted: int, cap: int, examined: int) -> None:
            report_tool_progress(
                message=f"{label} ({examined:,} examined)",
                done=min(max(0, int(accepted)), cap),
                total=cap,
                progress_state=self.progress_state,
                signals=self.signals,
                throttle=throttle,
            )

        report_tool_progress(
            message=label,
            done=0,
            total=target,
            progress_state=self.progress_state,
            signals=self.signals,
            throttle=throttle,
            force_signal=True,
        )
        if ev is not None and ev.is_set():
            self._finish_cancelled([], 0)
            return
        try:
            products, skipped, cancelled = recompose_fragments(
                self.fragment_smiles,
                self.method,
                max_depth=self.max_depth,
                max_products=self.max_products,
                output_filters=self.output_filters,
                cancel_event=ev,
                progress_callback=on_progress,
            )
        except ValueError as exc:
            if ev is not None and ev.is_set():
                self._finish_cancelled([], 0)
                return
            try:
                self.signals.fragment_recomp_failed.emit(
                    str(exc) or exc.__class__.__name__,
                    self.tool_title,
                )
            except Exception:
                pass
            return
        except Exception as exc:
            if ev is not None and ev.is_set():
                self._finish_cancelled([], 0)
                return
            try:
                self.signals.fragment_recomp_failed.emit(
                    str(exc) or exc.__class__.__name__,
                    self.tool_title,
                )
            except Exception:
                pass
            return
        if cancelled or (ev is not None and ev.is_set()):
            self._finish_cancelled(products, skipped)
            return
        report_tool_progress(
            message=label,
            done=target,
            total=target,
            progress_state=self.progress_state,
            signals=self.signals,
            force_signal=True,
        )
        try:
            self.signals.fragment_recomp_finished.emit(products, self.tool_title, skipped)
        except Exception:
            pass

    def _finish_cancelled(self, products: list[str], skipped: int) -> None:
        kept = [str(smi) for smi in products if (smi or "").strip()]
        if kept:
            emit_partial_results_if_cancelled(
                self.signals,
                self.tool_title,
                len(kept),
                self.max_products,
                True,
            )
            try:
                self.signals.fragment_recomp_finished.emit(kept, self.tool_title, int(skipped))
            except Exception:
                pass
        try:
            self.signals.fragment_recomp_failed.emit("Cancelled.", self.tool_title)
        except Exception:
            pass
