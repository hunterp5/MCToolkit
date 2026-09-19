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

"""Tests for Tools → Utilities → Random → Molecule (ChEMBL sampling helpers)."""

from __future__ import annotations

import pytest

from molmanager.sources.chembl_random_compounds import (
    RandomChemblMolecule,
    _record_to_hit,
    chembl_id_from_number,
    fetch_random_chembl_molecules,
)


def test_chembl_id_from_number():
    assert chembl_id_from_number(42) == "CHEMBL42"


def test_record_to_hit_requires_smiles_and_id():
    assert _record_to_hit({}) is None
    assert _record_to_hit({"molecule_chembl_id": "CHEMBL1"}) is None
    hit = _record_to_hit(
        {
            "molecule_chembl_id": "CHEMBL1",
            "pref_name": "Aspirin",
            "max_phase": 4,
            "molecule_type": "Small molecule",
            "molecule_structures": {"canonical_smiles": "CC(=O)Oc1ccccc1C(=O)O"},
        }
    )
    assert isinstance(hit, RandomChemblMolecule)
    assert hit.chembl_id == "CHEMBL1"
    assert hit.smiles.startswith("CC(=O)O")
    assert hit.fields["ChEMBL_ID"] == "CHEMBL1"
    assert hit.fields["PrefName"] == "Aspirin"
    assert hit.fields["MaxPhase"] == "4"


def test_fetch_random_chembl_molecules_mocked(monkeypatch):
    pages = {
        0: [
            {
                "molecule_chembl_id": "CHEMBL10",
                "molecule_structures": {"canonical_smiles": "CCO"},
            },
            {
                "molecule_chembl_id": "CHEMBL11",
                "molecule_structures": {"canonical_smiles": "CCC"},
            },
        ],
        50: [
            {
                "molecule_chembl_id": "CHEMBL20",
                "molecule_structures": {"canonical_smiles": "CCCC"},
            },
        ],
    }
    offsets = iter([0, 50])

    def fake_fetch_page(offset, limit, *, timeout=60.0):
        try:
            off = next(offsets)
        except StopIteration:
            off = 0
        return pages.get(off, [])

    monkeypatch.setattr("molmanager.sources.chembl_random_compounds._fetch_page", fake_fetch_page)
    monkeypatch.setattr(
        "molmanager.sources.chembl_random_compounds.small_molecule_total_count", lambda **_: 200
    )

    hits = fetch_random_chembl_molecules(3, seed=1, page_size=25)
    assert len(hits) == 3
    ids = {h.chembl_id for h in hits}
    assert ids == {"CHEMBL10", "CHEMBL11", "CHEMBL20"}


def test_fetch_rejects_bad_count():
    with pytest.raises(ValueError):
        fetch_random_chembl_molecules(0)
    with pytest.raises(ValueError):
        fetch_random_chembl_molecules(501)
