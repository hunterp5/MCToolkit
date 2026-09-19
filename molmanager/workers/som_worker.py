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

"""Background FAME3R site-of-metabolism prediction (NERDD)."""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass

from PyQt5 import sip
from PyQt5.QtCore import QObject, QRunnable, pyqtSignal
from rdkit import Chem

from ..predictions.som_prediction import (
    NERDD_METABOLISM_SUBSETS,
    SOM_CANCELLED_ERROR,
    MetabolismSubset,
    SomMoleculePrediction,
    format_som_columns,
    merge_phase_predictions,
    predict_soms_batch,
    render_som_map_png,
    som_output_columns,
    uses_split_phase_jobs,
)
from ..chem.molecule_conversion import mol_to_canonical_smiles
from .signals import emit_partial_results_if_cancelled
from .structure_grouping import group_rows_by_structure, structure_key

logger = logging.getLogger(__name__)

# Keep UI-facing label text local so workers do not import molmanager.ui.
_TOOL_LABEL = "Predict SOM"


@dataclass(frozen=True)
class SomPredictorRequest:
    """Row payloads and FAME3R options for :class:`SomPredictorWorker`."""

    rows: list
    metabolism_subset: MetabolismSubset = "all"
    fame_score: bool = False
    threshold: float = 0.3
    map_width: int = 242
    map_height: int = 202


def _safe_emit(obj, emitter_name: str, *args) -> None:
    if obj is None:
        return
    try:
        if sip.isdeleted(obj):
            return
    except Exception:
        return
    try:
        getattr(obj, emitter_name).emit(*args)
    except RuntimeError:
        pass


def _prediction_is_useful(pred: SomMoleculePrediction | None) -> bool:
    return pred is not None and pred.error != SOM_CANCELLED_ERROR


def _completed_row_count(
    rows: list[tuple[int | None, Chem.Mol | None]],
    pred_by_key: dict[str, SomMoleculePrediction],
) -> int:
    n = 0
    for _oid, mol in rows:
        if mol is None:
            n += 1
            continue
        if _prediction_is_useful(pred_by_key.get(structure_key(mol))):
            n += 1
    return n


class SomPredictorSignals(QObject):
    """Emits from :class:`SomPredictorWorker` (owned on the GUI thread)."""

    finished = pyqtSignal(list)
    failed = pyqtSignal(str)


class SomPredictorWorker(QRunnable):
    """Predict SOMs per row and emit table text plus PNG maps."""

    def __init__(
        self,
        request: SomPredictorRequest,
        worker_signals,
        som_signals: SomPredictorSignals,
        *,
        cancel_event: threading.Event | None = None,
        progress_state=None,
    ):
        super().__init__()
        self.rows = request.rows
        self.worker_signals = worker_signals
        self.som_signals = som_signals
        self.cancel_event = cancel_event
        self.metabolism_subset = request.metabolism_subset
        self.fame_score = request.fame_score
        self.threshold = request.threshold
        self.map_width = request.map_width
        self.map_height = request.map_height
        self.progress_state = progress_state

    def run(self) -> None:
        from ..platform_support.tool_progress import report_tool_progress

        cancel_ev = self.cancel_event
        include_fame = bool(self.fame_score)
        include_phases = uses_split_phase_jobs(self.metabolism_subset)
        columns = som_output_columns(include_fame=include_fame, include_phases=include_phases)
        na = format_som_columns(None, include_fame=include_fame, include_phases=include_phases)

        order, rep, oids_map = group_rows_by_structure(self.rows)
        n_empty = sum(1 for _oid, mol in self.rows if mol is None)
        tot = max(len(self.rows), 1)
        throttle = [0, 0.0]
        done = n_empty

        def _emit_progress(message: str, *, force: bool = False, waiting: bool = False) -> None:
            report_tool_progress(
                message=message,
                done=min(done, tot),
                total=-1 if waiting else tot,
                progress_state=self.progress_state,
                signals=self.worker_signals,
                throttle=throttle,
                force_signal=force,
            )

        from .process_pool_utils import application_is_shutting_down

        def _cancelled() -> bool:
            return application_is_shutting_down() or (cancel_ev is not None and cancel_ev.is_set())

        _emit_progress("Predict SOM: submitting…", force=True, waiting=True)
        if _cancelled():
            _safe_emit(self.som_signals, "failed", "Cancelled.")
            return

        smiles = [mol_to_canonical_smiles(rep[k]) for k in order]
        pred_by_key: dict[str, SomMoleculePrediction] = {}
        if smiles:
            n_unique_rows = tot - n_empty

            def _scale_progress(frac: float, message: str) -> None:
                nonlocal done
                if _cancelled():
                    return
                done = n_empty + int(round(max(0.0, min(frac, 1.0)) * n_unique_rows))
                waiting = done <= n_empty
                label = "Predict SOM: waiting on NERDD…" if waiting else message
                _emit_progress(label, waiting=waiting)

            def _cancelled_preds() -> list[SomMoleculePrediction]:
                return [
                    SomMoleculePrediction(smi, "", (), error=SOM_CANCELLED_ERROR) for smi in smiles
                ]

            def _run_subset(
                subset: str,
                lo: float,
                hi: float,
                message: str,
            ) -> list[SomMoleculePrediction]:
                if _cancelled():
                    return _cancelled_preds()

                def _batch_progress(batch_done: int, batch_total: int) -> None:
                    span = hi - lo
                    frac = lo + (batch_done / max(batch_total, 1)) * span
                    _scale_progress(frac, message)

                try:
                    return list(
                        predict_soms_batch(
                            smiles,
                            metabolism_subset=subset,
                            fame_score=include_fame,
                            shannon_entropy=False,
                            threshold=self.threshold,
                            cancel=_cancelled,
                            progress=_batch_progress,
                        )
                    )
                except Exception as e:
                    if str(e) == "Cancelled.":
                        return _cancelled_preds()
                    raise

            try:
                if include_phases:
                    phase1 = _run_subset("phase1", 0.0, 0.5, "Predict SOM (Phase 1)…")
                    phase2 = _run_subset("phase2", 0.5, 1.0, "Predict SOM (Phase 2)…")
                    preds = [merge_phase_predictions(p1, p2) for p1, p2 in zip(phase1, phase2)]
                else:
                    subset = str(self.metabolism_subset)
                    allowed = {k for k, _ in NERDD_METABOLISM_SUBSETS}
                    if subset not in allowed:
                        raise ValueError(f"Unknown metabolism subset: {subset}")
                    preds = _run_subset(subset, 0.0, 1.0, "Predict SOM…")
            except Exception as e:
                if str(e) == "Cancelled.":
                    _safe_emit(self.som_signals, "failed", "Cancelled.")
                    return
                logger.exception("FAME3R SOM prediction failed")
                _safe_emit(self.som_signals, "failed", f"Prediction failed: {e}")
                return
            for key, pred in zip(order, preds):
                pred_by_key[key] = pred

        if application_is_shutting_down():
            return

        cancelled = _cancelled()
        n_useful = sum(1 for pred in pred_by_key.values() if _prediction_is_useful(pred))
        if cancelled and n_useful == 0:
            _safe_emit(self.som_signals, "failed", "Cancelled.")
            return

        key_png: dict[str, bytes | None] = {}
        for key, pred in pred_by_key.items():
            if application_is_shutting_down():
                return
            png = None
            if pred is not None and not pred.error:
                png = render_som_map_png(
                    pred.preprocessed_smiles or pred.smiles,
                    pred.atoms,
                    width=self.map_width,
                    height=self.map_height,
                    reference_mol=rep.get(key),
                )
            key_png[key] = png

        by_oid: dict[
            int | None, tuple[dict[str, str], bytes | None, SomMoleculePrediction | None]
        ] = {}
        for oid, mol in self.rows:
            if mol is None:
                by_oid[oid] = (dict(na), None, None)
                continue
            key = structure_key(mol)
            pred = pred_by_key.get(key)
            cols = format_som_columns(
                pred, include_fame=include_fame, include_phases=include_phases
            )
            by_oid[oid] = (cols, key_png.get(key), pred)

        out = []
        for oid, _mol in self.rows:
            cols, png, pred = by_oid.get(oid, (dict(na), None, None))
            atoms = list(pred.atoms) if pred is not None else []
            out.append((oid, cols, png, atoms, columns))

        if application_is_shutting_down():
            return

        done_rows = _completed_row_count(self.rows, pred_by_key)
        emit_partial_results_if_cancelled(
            self.worker_signals, _TOOL_LABEL, done_rows, tot, cancelled
        )
        done = tot
        _emit_progress(_TOOL_LABEL, force=True)
        _safe_emit(self.som_signals, "finished", out)
