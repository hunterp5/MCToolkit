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
# along with MolManager. If not, see <https://www.gnu.org/licenses/>.

"""Background BioTransformer metabolite prediction (local JAR)."""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass

import shiboken6
from PySide6.QtCore import QObject, QRunnable, Signal
from rdkit import Chem

from ..predictions.biotransformer_metabolites import (
    BIOTRANSFORMER_CANCELLED,
    DEFAULT_CYP_MODE,
    DEFAULT_MAX_METABOLITES,
    DEFAULT_NSTEPS,
    MetabolismOption,
    MetaboliteHit,
    MetabolitePrediction,
    format_metabolite_columns,
    metabolite_output_columns,
    predict_metabolites_batch,
)
from ..chem.molecule_conversion import mol_to_canonical_smiles
from .signals import emit_partial_results_if_cancelled
from .structure_grouping import group_rows_by_structure, structure_key

logger = logging.getLogger(__name__)

_TOOL_LABEL = "Predict Metabolites"


@dataclass(frozen=True)
class BiotransformerRequest:
    """Row payloads and BioTransformer options for :class:`BiotransformerWorker`."""

    rows: list
    metabolism: MetabolismOption = "allHuman"
    nsteps: int = DEFAULT_NSTEPS
    cyp_mode: int = DEFAULT_CYP_MODE
    max_metabolites: int = DEFAULT_MAX_METABOLITES
    add_as_rows: bool = False


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


def _prediction_is_useful(pred: MetabolitePrediction | None) -> bool:
    return pred is not None and pred.error != BIOTRANSFORMER_CANCELLED


def _completed_row_count(
    rows: list[tuple[int | None, Chem.Mol | None]],
    pred_by_key: dict[str, MetabolitePrediction],
) -> int:
    n = 0
    for _oid, mol in rows:
        if mol is None:
            n += 1
            continue
        if _prediction_is_useful(pred_by_key.get(structure_key(mol))):
            n += 1
    return n


def metabolite_hit_payload(hit: MetaboliteHit) -> dict[str, object]:
    return {
        "smiles": hit.smiles,
        "reaction": hit.reaction,
        "enzyme": hit.enzyme,
        "biosystem": hit.biosystem,
        "generation": hit.generation,
        "precursor_smiles": hit.precursor_smiles,
    }


class BiotransformerSignals(QObject):
    """Emits from :class:`BiotransformerWorker` (owned on the GUI thread)."""

    finished = Signal(list)
    failed = Signal(str)


class BiotransformerWorker(QRunnable):
    """Predict metabolites per row and emit table text plus product records."""

    def __init__(
        self,
        request: BiotransformerRequest,
        worker_signals,
        bt_signals: BiotransformerSignals,
        *,
        cancel_event: threading.Event | None = None,
        progress_state=None,
    ):
        super().__init__()
        self.rows = request.rows
        self.worker_signals = worker_signals
        self.bt_signals = bt_signals
        self.cancel_event = cancel_event
        self.metabolism = request.metabolism
        self.nsteps = request.nsteps
        self.cyp_mode = request.cyp_mode
        self.max_metabolites = request.max_metabolites
        self.add_as_rows = bool(request.add_as_rows)
        self.progress_state = progress_state

    def run(self) -> None:
        from ..platform_support.tool_progress import report_tool_progress

        cancel_ev = self.cancel_event
        columns = metabolite_output_columns()
        na = format_metabolite_columns(None)

        order, rep, _oids_map = group_rows_by_structure(self.rows)
        n_empty = sum(1 for _oid, mol in self.rows if mol is None)
        tot = max(len(self.rows), 1)
        throttle = [0, 0.0]
        done = n_empty

        def _emit_progress(message: str, *, force: bool = False) -> None:
            report_tool_progress(
                message=message,
                done=min(done, tot),
                total=tot,
                progress_state=self.progress_state,
                signals=self.worker_signals,
                throttle=throttle,
                force_signal=force,
            )

        from .process_pool_utils import application_is_shutting_down

        def _cancelled() -> bool:
            return application_is_shutting_down() or (cancel_ev is not None and cancel_ev.is_set())

        _emit_progress("Predict Metabolites: starting…", force=True)
        if _cancelled():
            _safe_emit(self.bt_signals, "failed", "Cancelled.")
            return

        smiles = [mol_to_canonical_smiles(rep[k]) for k in order]
        pred_by_key: dict[str, MetabolitePrediction] = {}
        if smiles:
            n_unique = max(len(smiles), 1)

            def _batch_progress(batch_done: int, batch_total: int) -> None:
                nonlocal done
                if _cancelled():
                    return
                frac = batch_done / max(batch_total, 1)
                done = n_empty + int(round(frac * (tot - n_empty)))
                _emit_progress(
                    f"Predict Metabolites ({min(batch_done, n_unique)}/{n_unique} unique)…"
                )

            try:
                preds = list(
                    predict_metabolites_batch(
                        smiles,
                        metabolism=self.metabolism,
                        nsteps=self.nsteps,
                        cyp_mode=self.cyp_mode,
                        max_metabolites=self.max_metabolites,
                        cancel=_cancelled,
                        progress=_batch_progress,
                    )
                )
            except Exception as e:
                if str(e) == BIOTRANSFORMER_CANCELLED:
                    _safe_emit(self.bt_signals, "failed", "Cancelled.")
                    return
                logger.exception("BioTransformer prediction failed")
                _safe_emit(self.bt_signals, "failed", f"Prediction failed: {e}")
                return
            for key, pred in zip(order, preds):
                pred_by_key[key] = pred

        if application_is_shutting_down():
            return

        cancelled = _cancelled()
        n_useful = sum(1 for pred in pred_by_key.values() if _prediction_is_useful(pred))
        if cancelled and n_useful == 0:
            _safe_emit(self.bt_signals, "failed", "Cancelled.")
            return

        out = []
        for oid, mol in self.rows:
            if mol is None:
                out.append((oid, dict(na), [], columns, self.add_as_rows, ""))
                continue
            pred = pred_by_key.get(structure_key(mol))
            cols = format_metabolite_columns(pred)
            hits = [metabolite_hit_payload(h) for h in pred.metabolites] if pred else []
            parent_smi = pred.smiles if pred is not None else ""
            out.append((oid, cols, hits, columns, self.add_as_rows, parent_smi))

        if application_is_shutting_down():
            return

        done_rows = _completed_row_count(self.rows, pred_by_key)
        emit_partial_results_if_cancelled(
            self.worker_signals, _TOOL_LABEL, done_rows, tot, cancelled
        )
        done = tot
        _emit_progress(_TOOL_LABEL, force=True)
        _safe_emit(self.bt_signals, "finished", out)
