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

"""Ionization process-pool planning and structure cache."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from rdkit import Chem

import molmanager.workers.ionization_parallel as ionization_parallel
from molmanager.ionization import PicklableMicrostate, microstates_to_picklable
from molmanager.microstate_cache import clear as cache_clear
from molmanager.workers.ionization_parallel import plan_ionization_process_workers


@pytest.fixture(autouse=True)
def _force_sequential_ionization_cache(monkeypatch) -> None:
    """Tests that mock ``microstates_for_mol`` must not spawn a real process pool."""
    monkeypatch.setenv("MOLMANAGER_PKA_PROCESS_WORKERS", "1")
    monkeypatch.setattr(
        ionization_parallel,
        "plan_ionization_process_workers",
        lambda _n, _c: (False, 1),
    )


def test_plan_ionization_auto_uses_mp_from_two_unique(monkeypatch) -> None:
    monkeypatch.setattr(ionization_parallel, "unipka_cuda_available", lambda: False)
    use_mp, workers = plan_ionization_process_workers(3, None)
    assert use_mp is True
    assert workers >= 2


def test_plan_ionization_cuda_uses_one_worker_pool(monkeypatch) -> None:
    monkeypatch.setattr(ionization_parallel, "unipka_cuda_available", lambda: True)
    use_mp, workers = plan_ionization_process_workers(12, None)
    assert use_mp is True
    assert workers == 1
    use_mp, workers = plan_ionization_process_workers(12, 0)
    assert use_mp is False
    assert workers == 1


def test_chunk_structure_keys_spreads_across_workers() -> None:
    from molmanager.workers.ionization_parallel import chunk_structure_keys

    keys = [f"k{i}" for i in range(10)]
    chunks = chunk_structure_keys(keys, 2)
    assert len(chunks) == 2
    assert sum(len(c) for c in chunks) == 10
    assert chunk_structure_keys([], 4) == []


def test_plan_ionization_respects_force_sequential() -> None:
    use_mp, workers = plan_ionization_process_workers(10, 1)
    assert workers == 1
    _ = use_mp


def test_build_microstates_cache_dedupes(monkeypatch) -> None:
    cache_clear()
    calls: list[str] = []

    def _fake_microstates(mol):
        from molmanager.workers.structure_grouping import structure_key

        calls.append(structure_key(mol))
        return [{"pka": 7.0}]

    monkeypatch.setattr(
        "molmanager.ionization.microstates_for_mol",
        _fake_microstates,
    )

    m = Chem.MolFromSmiles("CCO")
    assert m is not None
    cache = ionization_parallel.build_microstates_cache_by_key(
        [Chem.Mol(m), Chem.Mol(m), Chem.MolFromSmiles("CCN")]
    )
    assert len(calls) == 2
    assert len(cache) == 2


def test_microstates_to_picklable_roundtrip() -> None:
    pm = Chem.MolFromSmiles("CCO")
    dm = Chem.MolFromSmiles("CC[O-]")
    assert pm is not None and dm is not None
    raw = [SimpleNamespace(pka=15.9, protonated_mol=pm, deprotonated_mol=dm, ph7_mol=pm)]
    snap = microstates_to_picklable(raw)
    assert snap[0].pka == 15.9
    assert isinstance(snap[0], PicklableMicrostate)
    assert snap[0].protonated_mol is not None
