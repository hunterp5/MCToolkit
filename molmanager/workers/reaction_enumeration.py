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

"""Reaction-based enumeration worker (Tools menu)."""

from __future__ import annotations

import threading

from PyQt5.QtCore import QRunnable

from ..chem.reaction_enumeration import (
    ReactionEnumerationJobResult,
    enumerate_reaction,
    load_reactant_pool,
    write_product_smiles_to_sdf,
)
from .signals import WorkerSignals, emit_partial_results_if_cancelled


class ReactionEnumerationWorker(QRunnable):
    """Enumerate reaction products from two reactant pools (files or SMILES text)."""

    def __init__(
        self,
        rxn_smarts: str,
        reaction_name: str,
        reactant_1_mode: str,
        reactant_2_mode: str,
        reactant_file_1: str,
        reactant_file_2: str,
        reactant_smiles_1: str,
        reactant_smiles_2: str,
        max_products: int,
        output_filters: str,
        add_to_table: bool,
        save_to_file: bool,
        save_path: str | None,
        tool_title: str,
        signals: WorkerSignals,
        *,
        cancel_event: threading.Event | None = None,
        progress_state=None,
    ):
        super().__init__()
        self.rxn_smarts = str(rxn_smarts or "")
        self.reaction_name = str(reaction_name or "Reaction")
        self.reactant_1_mode = str(reactant_1_mode or "file")
        self.reactant_2_mode = str(reactant_2_mode or "file")
        self.reactant_file_1 = str(reactant_file_1 or "")
        self.reactant_file_2 = str(reactant_file_2 or "")
        self.reactant_smiles_1 = str(reactant_smiles_1 or "")
        self.reactant_smiles_2 = str(reactant_smiles_2 or "")
        self.max_products = int(max_products)
        self.output_filters = str(output_filters or "")
        self.add_to_table = bool(add_to_table)
        self.save_to_file = bool(save_to_file)
        self.save_path = (save_path or "").strip() or None
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
                message=f"{label} ({examined:,} pairs examined)",
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
            pool_a = load_reactant_pool(
                source=self.reactant_1_mode,
                file_path=self.reactant_file_1,
                smiles_text=self.reactant_smiles_1,
            )
            pool_b = load_reactant_pool(
                source=self.reactant_2_mode,
                file_path=self.reactant_file_2,
                smiles_text=self.reactant_smiles_2,
            )
            products, skipped, cancelled = enumerate_reaction(
                self.rxn_smarts,
                [pool_a, pool_b],
                max_products=self.max_products,
                output_filters=self.output_filters,
                cancel_event=ev,
                progress_callback=on_progress,
            )
        except ValueError as exc:
            if ev is not None and ev.is_set():
                self._finish_cancelled([], 0)
                return
            self._emit_failed(str(exc) or exc.__class__.__name__)
            return
        except Exception as exc:
            if ev is not None and ev.is_set():
                self._finish_cancelled([], 0)
                return
            self._emit_failed(str(exc) or exc.__class__.__name__)
            return
        if cancelled or (ev is not None and ev.is_set()):
            self._finish_cancelled(products, skipped)
            return
        written = 0
        if self.save_to_file and self.save_path and products:
            try:
                written = write_product_smiles_to_sdf(
                    self.save_path,
                    products,
                    self.reaction_name,
                )
            except Exception as exc:
                self._emit_failed(str(exc) or exc.__class__.__name__)
                return
        report_tool_progress(
            message=label,
            done=target,
            total=target,
            progress_state=self.progress_state,
            signals=self.signals,
            force_signal=True,
        )
        result = ReactionEnumerationJobResult(
            products=list(products),
            reaction_name=self.reaction_name,
            skipped=int(skipped),
            add_to_table=self.add_to_table,
            save_to_file=self.save_to_file,
            save_path=self.save_path,
            written_count=int(written),
        )
        try:
            self.signals.reaction_enum_finished.emit(result)
        except Exception:
            pass

    def _emit_failed(self, message: str) -> None:
        try:
            self.signals.reaction_enum_failed.emit(message, self.tool_title)
        except Exception:
            pass

    def _finish_cancelled(self, products: list[str], skipped: int) -> None:
        kept = [str(smi) for smi in products if (smi or "").strip()]
        written = 0
        if self.save_to_file and self.save_path and kept:
            try:
                written = write_product_smiles_to_sdf(
                    self.save_path,
                    kept,
                    self.reaction_name,
                )
            except Exception:
                written = 0
        if kept:
            emit_partial_results_if_cancelled(
                self.signals,
                self.tool_title,
                len(kept),
                self.max_products,
                True,
            )
            result = ReactionEnumerationJobResult(
                products=kept,
                reaction_name=self.reaction_name,
                skipped=int(skipped),
                add_to_table=self.add_to_table,
                save_to_file=self.save_to_file,
                save_path=self.save_path,
                written_count=int(written),
            )
            try:
                self.signals.reaction_enum_finished.emit(result)
            except Exception:
                pass
        try:
            self.signals.reaction_enum_failed.emit("Cancelled.", self.tool_title)
        except Exception:
            pass
