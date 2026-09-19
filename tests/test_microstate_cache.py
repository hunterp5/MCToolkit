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

from molmanager.ionization import microstate_cache as mc
from molmanager.ionization.unipka_ensembles import (
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

    monkeypatch.setattr("molmanager.ionization.unipka_ensembles.predict_ionization_ensemble", boom)
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


def _acetic_ensemble() -> PicklableIonizationEnsemble:
    acid = Chem.MolFromSmiles("CC(=O)O")
    base = Chem.MolFromSmiles("CC(=O)[O-]")
    assert acid is not None and base is not None
    return PicklableIonizationEnsemble(
        microstates=(
            PicklableIonizationMicrostate("CC(=O)O", 0, 0.0, acid.ToBinary()),
            PicklableIonizationMicrostate("CC(=O)[O-]", -1, 10.78, base.ToBinary()),
        ),
        macro_pkas=(4.68,),
    )


def test_ionization_sidecar_roundtrip_json() -> None:
    import json

    ens = _acetic_ensemble()
    mc.store("CC(=O)O", ens)
    mc.store("failed-key", None)
    raw = mc.serialize_ionization_sidecar()
    assert abs(float(raw["pka_mean"]) - 6.504894871171601) < 1e-6
    wire = json.dumps(raw)
    back = json.loads(wire)
    assert "failed-key" not in back["entries"]
    restored = mc.deserialize_ionization_sidecar(back)
    assert "CC(=O)O" in restored
    got = restored["CC(=O)O"]
    assert isinstance(got, PicklableIonizationEnsemble)
    assert got.macro_pkas == (4.68,)
    assert got.microstates[1].charge == -1
    assert got.microstates[0].mol_binary
    mol = Chem.Mol(got.microstates[0].mol_binary)
    assert Chem.MolToSmiles(mol) == Chem.MolToSmiles(Chem.MolFromSmiles("CC(=O)O"))


def test_ionization_sidecar_skips_corrupt_and_unknown_version() -> None:
    ens = _tiny_ensemble()
    mc.store("CCO", ens)
    raw = mc.serialize_ionization_sidecar()
    raw["entries"]["bad"] = {"kind": "unipka", "macro_pkas": "nope"}
    restored = mc.deserialize_ionization_sidecar(raw)
    assert "CCO" in restored
    assert "bad" not in restored
    raw["v"] = 99
    assert mc.deserialize_ionization_sidecar(raw) == {}
    assert mc.deserialize_ionization_sidecar(None) == {}
    raw["v"] = 1
    raw.pop("pka_mean", None)
    assert mc.deserialize_ionization_sidecar(raw) == {}


def test_restore_ionization_sidecar_replaces_store() -> None:
    mc.store("old", _tiny_ensemble(1.0))
    payload = {
        "v": 1,
        "engine": "unipka",
        "pka_mean": 6.504894871171601,
        "entries": {
            "CCO": {
                "kind": "unipka",
                "macro_pkas": [9.5],
                "microstates": [{"smiles": "CCO", "charge": 0, "free_energy": 0.0}],
            }
        },
    }
    n = mc.restore_ionization_sidecar(payload)
    assert n == 1
    assert mc.lookup("old") == (False, None)
    hit, cached = mc.lookup("CCO")
    assert hit is True
    assert cached.macro_pkas == (9.5,)


def test_microstate_cache_aliases_other_microstate_smiles() -> None:
    ens = _acetic_ensemble()
    acid = Chem.MolFromSmiles("CC(=O)O")
    base = Chem.MolFromSmiles("CC(=O)[O-]")
    assert acid is not None and base is not None
    mc.store(structure_key(acid), ens)
    hit, cached = mc.lookup(structure_key(base))
    assert hit is True
    assert cached is ens
    raw = mc.serialize_ionization_sidecar()
    assert len(raw["entries"]) == 1
    restored = mc.deserialize_ionization_sidecar(raw)
    assert structure_key(acid) in restored
    assert structure_key(base) in restored
