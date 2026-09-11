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

"""Background pKa prediction using Uni-pKa (Luo et al., JACS Au 2024).

**Uni-pKa** — Luo, Y.; Liu, Y.; Peng, J.; Tang, H.; Nie, H.; Zhong, W.; Chen, X.;
Zheng, S. Toward Universal Cell Environment pKa Prediction via Multi-task Learning.
JACS Au 2024, 4, 1721. https://doi.org/10.1021/jacsau.4c00271
Code: https://github.com/dptech-corp/Uni-pKa — runtime: unipkainfer.

Enumeration uses MolGpKa-derived SMARTS (Pan et al., J. Chem. Inf. Model. 2021).
Shorter copy-paste block: ``molmanager.science_citations.UNIPKA``.
"""

from __future__ import annotations

import contextlib
import logging
import os
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait

from PyQt5 import sip
from PyQt5.QtCore import QObject, QRunnable, pyqtSignal
from rdkit import Chem

from molmanager.ionization import (
    format_pka_values,
    pka_values_from_states,
    pin_unipka_torch_threads,
    predict_ionization_ensemble,
    predict_ionization_ensembles,
    prepare_mol_for_ionization,
    unipka_import_error,
)
from .process_pool_utils import (
    application_is_shutting_down,
    register_process_pool,
    should_terminate_process_pool,
    shutdown_process_pool_executor,
)
from .structure_grouping import group_rows_by_structure

logger = logging.getLogger(__name__)

_unipka_lock = threading.Lock()

_UNIPKA_SUPPRESSED_LOGGER_NAMES = (
    "rdkit.Chem.PandasPatcher",
    "rdkit.Chem.PandasTools",
    "unipkainfer",
    "unicoreinfer",
)


@contextlib.contextmanager
def _quieter_unipka_loggers():
    """Temporarily raise log levels so Uni-pKa / RDKit chatter does not flood the console."""
    saved: list[tuple[logging.Logger, int]] = []
    for name in _UNIPKA_SUPPRESSED_LOGGER_NAMES:
        lg = logging.getLogger(name)
        saved.append((lg, lg.level))
        lg.setLevel(logging.ERROR)
    try:
        yield
    finally:
        for lg, prev in saved:
            lg.setLevel(prev)


@contextlib.contextmanager
def _discard_stdio():
    """Hide Uni-pKa ``print`` output (it bypasses logging)."""
    with open(os.devnull, "w", encoding="utf-8") as dn:
        with contextlib.redirect_stdout(dn), contextlib.redirect_stderr(dn):
            yield


@contextlib.contextmanager
def _discard_stdout_only():
    """Hide chatty ``print`` on stdout while keeping stderr for tracebacks."""
    with open(os.devnull, "w", encoding="utf-8") as dn:
        with contextlib.redirect_stdout(dn):
            yield


def _safe_emit(obj, emitter_name: str, *args) -> None:
    """Emit on a QObject-owned signal if the C++ object still exists."""
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


def _acquire_lock_cooperative(
    lock: threading.Lock, cancel_event: threading.Event | None, timeout_s: float = 0.05
) -> bool:
    """Acquire lock in short slices so cancellation can abort long waits."""
    while True:
        if cancel_event is not None and cancel_event.is_set():
            return False
        if lock.acquire(timeout=timeout_s):
            return True


def _format_microstate_pkas(
    states, *, most_basic_only: bool = False, most_acidic_only: bool = False
) -> str:
    return format_pka_values(
        pka_values_from_states(states),
        most_basic_only=most_basic_only,
        most_acidic_only=most_acidic_only,
    )


def _mp_compute_pka_text(
    task: tuple[str, bytes, bool, bool],
) -> tuple[str, str, object | None, bool]:
    """Child-process entry: load Uni-pKa, predict one structure."""
    return _mp_compute_pka_chunk([task])[0]


def _mp_compute_pka_chunk(
    tasks: list[tuple[str, bytes, bool, bool]],
) -> list[tuple[str, str, object | None, bool]]:
    """Score a chunk of structures in one Uni-pKa free-energy call."""
    pin_unipka_torch_threads()
    err = unipka_import_error()
    if err:
        logger.error("pKa subprocess: %s", err)
        return [(task[0], "Error (see log)", None, False) for task in tasks]

    keys: list[str] = []
    flags: list[tuple[bool, bool]] = []
    mols: list[Chem.Mol | None] = []
    na_results: dict[int, tuple[str, str, object | None, bool]] = {}
    for i, (key, mol_blob, most_basic_only, most_acidic_only) in enumerate(tasks):
        keys.append(key)
        flags.append((most_basic_only, most_acidic_only))
        if not mol_blob:
            mols.append(None)
            na_results[i] = (key, "N/A", None, True)
            continue
        try:
            mol = Chem.Mol(mol_blob)
        except Exception:
            mols.append(None)
            na_results[i] = (key, "N/A", None, True)
            continue
        if mol is None or mol.GetNumAtoms() == 0:
            mols.append(None)
            na_results[i] = (key, "N/A", None, True)
            continue
        safe = prepare_mol_for_ionization(mol)
        if safe is None:
            mols.append(None)
            na_results[i] = (key, "N/A", None, True)
        else:
            mols.append(safe)

    usable_idx = [i for i, mol in enumerate(mols) if mol is not None]
    ensembles: list[object | None] = [None] * len(keys)
    failed = False
    if usable_idx:
        try:
            with _discard_stdout_only():
                scored = predict_ionization_ensembles([mols[i] for i in usable_idx])
            for i, ens in zip(usable_idx, scored):
                ensembles[i] = ens
        except Exception:
            failed = True
            logger.exception(
                "pKa subprocess: batched prediction failed for %s structure(s)",
                len(usable_idx),
            )

    out: list[tuple[str, str, object | None, bool]] = []
    for i, key in enumerate(keys):
        if i in na_results:
            out.append(na_results[i])
            continue
        most_basic_only, most_acidic_only = flags[i]
        ensemble = ensembles[i]
        if failed and ensemble is None:
            out.append((key, "Error (see log)", None, False))
            continue
        if ensemble is None:
            out.append((key, "N/A", None, True))
            continue
        txt = _format_microstate_pkas(
            ensemble,
            most_basic_only=most_basic_only,
            most_acidic_only=most_acidic_only,
        )
        out.append((key, txt, ensemble, True))
    return out


class PKaPredictorSignals(QObject):
    """Emits from :class:`PKaPredictorWorker` back to the dialog (owned on the GUI thread)."""

    finished = pyqtSignal(list)  # list[tuple[int | None, str]]  oid None = SMILES-only preview
    failed = pyqtSignal(str)


class PKaPredictorWorker(QRunnable):
    """Predict macro pKa values per row; writes are applied on the GUI thread via ``finished``."""

    def __init__(
        self,
        rows: list[tuple[int | None, Chem.Mol | None]],
        worker_signals,
        pka_signals: PKaPredictorSignals,
        cancel_event: threading.Event | None = None,
        *,
        most_basic_only: bool = False,
        most_acidic_only: bool = False,
        progress_state=None,
    ):
        super().__init__()
        self.rows = rows
        self.worker_signals = worker_signals
        self.pka_signals = pka_signals
        self.cancel_event = cancel_event
        self.most_basic_only = most_basic_only
        self.most_acidic_only = most_acidic_only
        self.progress_state = progress_state

    def run(self) -> None:
        with _quieter_unipka_loggers():
            err = unipka_import_error()
            if err:
                logger.exception("pKa predictor: Uni-pKa import failed")
                _safe_emit(self.pka_signals, "failed", err)
                return

            from molmanager.ionization import warn_if_cuda_torch_missing

            warn_if_cuda_torch_missing()

            cancel_ev = self.cancel_event
            row_text: dict[int | None, str] = {}
            for oid, mol in self.rows:
                if mol is None:
                    row_text[oid] = "N/A"

            order, rep, oids_map = group_rows_by_structure(self.rows)
            n_work = sum(len(oids_map[k]) for k in order) + sum(
                1 for oid, mol in self.rows if mol is None
            )
            tot = max(n_work, 1)
            n_unique = len(order)

            from ..config import load_config
            from .ionization_parallel import (
                chunk_structure_keys,
                plan_ionization_process_workers,
            )

            use_mp, proc_workers = plan_ionization_process_workers(
                n_unique, load_config().pka_process_workers
            )

            done_cum = sum(1 for oid, mol in self.rows if mol is None)
            cancelled = False
            prog_last = 0.0

            from ..tool_progress import report_tool_progress

            throttle = [0, 0.0]

            def _emit(done: int, *, force: bool = False) -> None:
                nonlocal prog_last
                now = time.monotonic()
                if force or done >= tot or (now - prog_last) >= 0.12:
                    prog_last = now
                    report_tool_progress(
                        message="pKa prediction",
                        done=min(done, tot),
                        total=tot,
                        progress_state=self.progress_state,
                        signals=self.worker_signals,
                        throttle=throttle,
                        force_signal=force,
                    )

            _emit(done_cum, force=True)

            if not order:
                out = [(oid, row_text.get(oid, "N/A")) for oid, _ in self.rows]
                _emit(tot, force=True)
                _safe_emit(self.pka_signals, "finished", out)
                return

            if use_mp:
                from molmanager.microstate_cache import store as cache_store
                from .ionization_parallel import (
                    _restore_unipka_mmff_thread_env,
                    _set_unipka_mmff_thread_env,
                )

                key_chunks = chunk_structure_keys(order, proc_workers)
                task_chunks = [
                    [
                        (k, rep[k].ToBinary(), self.most_basic_only, self.most_acidic_only)
                        for k in chunk
                    ]
                    for chunk in key_chunks
                ]
                results_by_key: dict[str, str] = {}
                wrote_mmff = (
                    os.environ.get("MOLMANAGER_UNIPKA_MMFF_THREADS") is None and proc_workers > 1
                )
                prev_mmff = _set_unipka_mmff_thread_env(proc_workers)
                logger.info(
                    "pKa: scoring in %s worker process(es) (%s unique structure(s))",
                    proc_workers,
                    n_unique,
                )
                ex = register_process_pool(ProcessPoolExecutor(max_workers=proc_workers))
                try:
                    pending = {ex.submit(_mp_compute_pka_chunk, chunk) for chunk in task_chunks}
                    while pending:
                        if (
                            should_terminate_process_pool(cancel_ev)
                            or application_is_shutting_down()
                        ):
                            cancelled = True
                            for f in pending:
                                f.cancel()
                            break
                        completed, pending = wait(
                            pending, timeout=0.25, return_when=FIRST_COMPLETED
                        )
                        for f in completed:
                            if f.cancelled():
                                continue
                            try:
                                for key, txt, ensemble, cacheable in f.result():
                                    results_by_key[key] = txt
                                    if cacheable:
                                        cache_store(key, ensemble)
                                    done_cum += len(oids_map.get(key, ()))
                            except Exception:
                                logger.exception("pKa process-pool task failed")
                            _emit(done_cum)
                finally:
                    shutdown_process_pool_executor(
                        ex, kill_workers=should_terminate_process_pool(cancel_ev)
                    )
                    _restore_unipka_mmff_thread_env(prev_mmff, wrote_mmff)
                for key in order:
                    txt = results_by_key.get(key, "Error (see log)")
                    for oid in oids_map.get(key, ()):
                        row_text[oid] = txt
            else:
                from molmanager.microstate_cache import store as cache_store

                pin_unipka_torch_threads()
                for key in order:
                    if should_terminate_process_pool(cancel_ev):
                        cancelled = True
                        break
                    mol = rep[key]
                    safe_mol = prepare_mol_for_ionization(mol)
                    if safe_mol is None:
                        txt = "N/A"
                        cache_store(key, None)
                    else:
                        try:
                            if not _acquire_lock_cooperative(_unipka_lock, cancel_ev):
                                cancelled = True
                                break
                            try:
                                with _discard_stdout_only():
                                    ensemble = predict_ionization_ensemble(safe_mol)
                            finally:
                                _unipka_lock.release()
                            txt = _format_microstate_pkas(
                                ensemble,
                                most_basic_only=self.most_basic_only,
                                most_acidic_only=self.most_acidic_only,
                            )
                            cache_store(key, ensemble)
                        except UnicodeDecodeError as e:
                            logger.warning(
                                "pKa prediction skipped %s row(s) (non-UTF8 structure metadata): %s",
                                len(oids_map[key]),
                                e,
                            )
                            txt = "N/A (SDF metadata)"
                            cache_store(key, None)
                        except Exception:
                            logger.exception(
                                "pKa prediction failed for %s row(s) (key prefix %.40s…)",
                                len(oids_map[key]),
                                key,
                            )
                            txt = "Error (see log)"
                    for oid in oids_map[key]:
                        row_text[oid] = txt
                    done_cum += len(oids_map[key])
                    _emit(done_cum)

            out = [(oid, row_text.get(oid, "N/A")) for oid, _ in self.rows]
            _emit(tot, force=True)
            if cancelled and done_cum > 0:
                try:
                    self.worker_signals.partial_results.emit("pKa prediction", done_cum, tot)
                except Exception:
                    pass
            if use_mp:
                logger.debug(
                    "pKa: %s table row(s), %s unique structure(s), process pool=%s",
                    n_work,
                    n_unique,
                    proc_workers,
                )
            else:
                logger.debug(
                    "pKa: %s table row(s), %s unique structure(s), sequential (set "
                    "MOLMANAGER_PKA_PROCESS_WORKERS>=1 to allow worker processes; <=0 disables)",
                    n_work,
                    n_unique,
                )
            _safe_emit(self.pka_signals, "finished", out)
