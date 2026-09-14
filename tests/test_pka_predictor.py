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

"""pKa worker helpers (no Uni-pKa model required)."""

from __future__ import annotations

import pytest
from rdkit import Chem

from molmanager.ionization import PicklableIonizationEnsemble, PicklableIonizationMicrostate
from molmanager.workers.pka_predictor import (
    PKaPredictorSignals,
    PKaPredictorWorker,
    prepare_mol_for_ionization,
)
from molmanager.workers.signals import WorkerSignals


def _ensemble(*pkas: float, smiles: str = "CCO") -> PicklableIonizationEnsemble:
    return PicklableIonizationEnsemble(
        microstates=(PicklableIonizationMicrostate(smiles, 0, 0.0, None),),
        macro_pkas=tuple(pkas),
    )


@pytest.fixture(autouse=True)
def _force_sequential_pka_worker(monkeypatch) -> None:
    """Keep pKa worker tests on the in-process path (mocked scorer), not a process pool."""
    from molmanager import microstate_cache as mc

    mc.clear()
    monkeypatch.setenv("MOLMANAGER_PKA_PROCESS_WORKERS", "1")
    monkeypatch.setattr(
        "molmanager.workers.ionization_parallel.plan_ionization_process_workers",
        lambda _n, _c: (False, 1),
    )
    monkeypatch.setattr("molmanager.workers.pka_predictor.unipka_import_error", lambda: None)
    yield
    mc.clear()


def test_prepare_mol_for_ionization_strips_non_utf8_sdf_prop() -> None:
    m = Chem.MolFromSmiles("CCO")
    assert m is not None
    m.SetProp("_test_bad", b"\xa6vendor".decode("latin-1"))
    safe = prepare_mol_for_ionization(m)
    assert safe is not None
    assert safe.GetNumAtoms() == m.GetNumAtoms()
    if hasattr(safe, "GetPropsAsDict"):
        safe.GetPropsAsDict()


def test_pka_worker_emits_partial_results_on_cancel(monkeypatch) -> None:
    class _CancelAfterFirst:
        def __init__(self) -> None:
            self._flag = False

        def is_set(self) -> bool:
            return self._flag

        def trigger(self) -> None:
            self._flag = True

    cancel = _CancelAfterFirst()

    def _predict(_mol):
        cancel.trigger()
        return _ensemble(7.1, 4.2)

    monkeypatch.setattr("molmanager.workers.pka_predictor.predict_ionization_ensemble", _predict)
    ws = WorkerSignals()
    ps = PKaPredictorSignals()
    partial: list[tuple[str, int, int]] = []
    finished: list[list[tuple[int | None, str, str]]] = []
    ws.partial_results.connect(lambda tool, done, total: partial.append((tool, done, total)))
    ps.finished.connect(lambda rows, _include_pi=False: finished.append(rows))

    rows = [(1, Chem.MolFromSmiles("CCO")), (2, Chem.MolFromSmiles("CCN"))]
    worker = PKaPredictorWorker(rows, ws, ps, cancel_event=cancel)
    worker.run()

    assert finished, "expected finished signal"
    assert finished[0], "expected at least one completed pKa row"
    assert partial == [("pKa prediction", 1, 2)]


def test_pka_worker_deduplicates_identical_structures(monkeypatch) -> None:
    call_count = 0

    class _CancelNever:
        def is_set(self) -> bool:
            return False

    def _predict(_mol):
        nonlocal call_count
        call_count += 1
        return _ensemble(7.0)

    monkeypatch.setattr("molmanager.workers.pka_predictor.predict_ionization_ensemble", _predict)
    ws = WorkerSignals()
    ps = PKaPredictorSignals()
    finished: list[list[tuple[int | None, str, str]]] = []
    ps.finished.connect(lambda rows, _include_pi=False: finished.append(rows))

    m = Chem.MolFromSmiles("CCO")
    assert m is not None
    rows = [(1, Chem.Mol(m)), (2, Chem.Mol(m)), (3, Chem.MolFromSmiles("CCN"))]
    worker = PKaPredictorWorker(rows, ws, ps, cancel_event=_CancelNever())
    worker.run()

    assert call_count == 2
    assert finished
    by_oid = {oid: txt for oid, txt, _pi in finished[0]}
    assert by_oid[1] == by_oid[2] == "7.00"
    assert by_oid[3] == "7.00"


def test_pka_worker_reuses_session_cache(monkeypatch) -> None:
    from molmanager import microstate_cache as mc
    from molmanager.workers.structure_grouping import structure_key

    mol = Chem.MolFromSmiles("CCO")
    assert mol is not None
    mc.store(structure_key(mol), _ensemble(4.2, 9.1))

    call_count = 0

    def _predict(_mol):
        nonlocal call_count
        call_count += 1
        return _ensemble(0.0)

    monkeypatch.setattr("molmanager.workers.pka_predictor.predict_ionization_ensemble", _predict)
    ws = WorkerSignals()
    ps = PKaPredictorSignals()
    finished: list[list[tuple[int | None, str, str]]] = []
    ps.finished.connect(lambda rows, _include_pi=False: finished.append(rows))

    class _CancelNever:
        def is_set(self) -> bool:
            return False

    worker = PKaPredictorWorker([(1, Chem.Mol(mol))], ws, ps, cancel_event=_CancelNever())
    worker.run()

    assert call_count == 0
    assert finished
    oid, txt, pi = finished[0][0]
    assert oid == 1
    assert txt == "4.20; 9.10"
    assert pi == "7.00"


def test_pka_worker_emits_include_pi_flag(monkeypatch) -> None:
    monkeypatch.setattr(
        "molmanager.workers.pka_predictor.predict_ionization_ensemble",
        lambda _mol: _ensemble(7.0),
    )
    ws = WorkerSignals()
    ps = PKaPredictorSignals()
    flags: list[bool] = []
    ps.finished.connect(lambda _rows, include_pi: flags.append(bool(include_pi)))

    class _CancelNever:
        def is_set(self) -> bool:
            return False

    mol = Chem.MolFromSmiles("CCO")
    PKaPredictorWorker(
        [(1, mol)],
        ws,
        ps,
        cancel_event=_CancelNever(),
        include_pi=True,
    ).run()
    assert flags == [True]
