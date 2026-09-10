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

"""Dominant protomer selection from pkasolver microstates."""

from __future__ import annotations

from types import SimpleNamespace

from rdkit import Chem

from molmanager.workers.protonate_worker import (
    _dominant_smiles_from_microstates,
    dominant_results_from_microstate_cache,
)


def _acetic_microstates():
    ha = Chem.MolFromSmiles("CC(=O)O")
    a = Chem.MolFromSmiles("CC(=O)[O-]")
    assert ha is not None and a is not None
    return [
        SimpleNamespace(pka=4.76, protonated_mol=ha, deprotonated_mol=a, ph7_mol=a),
    ]


def test_dominant_protomer_acetic_acid_at_ph_7_4():
    smi, pct = _dominant_smiles_from_microstates(_acetic_microstates(), 7.4)
    mol = Chem.MolFromSmiles(smi)
    assert mol is not None
    assert Chem.GetFormalCharge(mol) == -1
    assert pct > 90.0


def test_dominant_protomer_acetic_acid_at_ph_2():
    smi, pct = _dominant_smiles_from_microstates(_acetic_microstates(), 2.0)
    mol = Chem.MolFromSmiles(smi)
    assert mol is not None
    assert Chem.GetFormalCharge(mol) == 0
    assert pct > 90.0


def test_dominant_results_replicate_across_duplicate_oids():
    states = _acetic_microstates()
    ha = states[0].protonated_mol
    from molmanager.workers.structure_grouping import structure_key

    key = structure_key(ha)
    rows, cancelled = dominant_results_from_microstate_cache(
        [key],
        {key: [10, 20]},
        {key: states},
        7.4,
    )
    assert cancelled is False
    assert len(rows) == 2
    assert {oid for oid, _smi, _pct in rows} == {10, 20}
    assert all(pct > 90.0 for _oid, _smi, pct in rows)
