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

"""Tests for session ionization-ensemble cache (Predict pKa → LogD/LogS reuse)."""

from __future__ import annotations

from types import SimpleNamespace

from molmanager import microstate_cache as mc
from molmanager.ionization import (
    PicklableIonizationEnsemble,
    PicklableIonizationMicrostate,
    PicklableMicrostate,
    hydrate_microstates,
    microstates_for_mol,
    microstates_to_picklable,
)
from molmanager.workers.ionization_parallel import build_microstates_cache_by_key
from molmanager.workers.structure_grouping import structure_key
from rdkit import Chem


def setup_function() -> None:
    mc.clear()


def teardown_function() -> None:
    mc.clear()


def _tiny_ensemble(pka: float = 4.2) -> PicklableIonizationEnsemble:
    return PicklableIonizationEnsemble(
        microstates=(PicklableIonizationMicrostate("CCO", 0, 0.0, None),),
        macro_pkas=(pka,),
    )


def test_microstate_cache_lookup_miss_and_store() -> None:
    assert mc.lookup("CCO") == (False, None)
    states = _tiny_ensemble()
    mc.store("CCO", states)
    hit, cached = mc.lookup("CCO")
    assert hit is True
    assert cached is states
    mc.store("CCO", None)
    hit, cached = mc.lookup("CCO")
    assert hit is True
    assert cached is None


def test_microstate_cache_clear() -> None:
    mc.store("C", [_tiny_ensemble(1.0)])
    assert mc.size() == 1
    mc.clear()
    assert mc.size() == 0
    assert mc.lookup("C") == (False, None)


def test_microstates_for_mol_uses_session_cache(monkeypatch) -> None:
    mol = Chem.MolFromSmiles("CCO")
    assert mol is not None
    key = structure_key(mol)
    fake = _tiny_ensemble(9.5)
    mc.store(key, fake)

    def boom(_m):
        raise AssertionError("Uni-pKa should not run on cache hit")

    monkeypatch.setattr("molmanager.ionization.predict_ionization_ensemble", boom)
    out = microstates_for_mol(mol)
    assert out is fake


def test_build_microstates_cache_skips_cached_keys(monkeypatch) -> None:
    mol = Chem.MolFromSmiles("CCN")
    assert mol is not None
    key = structure_key(mol)
    fake = _tiny_ensemble(10.1)
    mc.store(key, fake)

    def fail_pool(*_a, **_k):
        raise AssertionError("process pool should not start when all cached")

    monkeypatch.setattr(
        "molmanager.workers.ionization_parallel.plan_ionization_process_workers",
        fail_pool,
    )
    out = build_microstates_cache_by_key([mol], workers_cfg=0)
    assert out[key] is fake


def test_picklable_roundtrip_for_cache_payload() -> None:
    live = [
        SimpleNamespace(
            pka=7.4,
            protonated_mol=Chem.MolFromSmiles("CC[NH3+]"),
            deprotonated_mol=Chem.MolFromSmiles("CCN"),
            ph7_mol=None,
        )
    ]
    packed = microstates_to_picklable(live)
    assert isinstance(packed[0], PicklableMicrostate)
    mc.store("CCN", packed)
    hit, cached = mc.lookup("CCN")
    assert hit
    hydrated = hydrate_microstates(cached)
    assert abs(hydrated[0].pka - 7.4) < 1e-9
    assert hydrated[0].protonated_mol is not None
    assert hydrated[0].deprotonated_mol is not None
