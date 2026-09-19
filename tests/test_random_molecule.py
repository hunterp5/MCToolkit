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
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with MolManager. If not, see <https://www.gnu.org/licenses/>.

"""Tests for Tools → Random → Molecule source sampling (no network)."""

from __future__ import annotations

import json

import pytest

from molmanager.chembl_random import RandomChemblMolecule
from molmanager.random_molecule_sources import (
    SOURCE_CHEMBL,
    SOURCE_PUBCHEM,
    SOURCE_ZINC,
    IntBounds,
    RandomMoleculeFilters,
    RandomSourceMolecule,
    _fetch_zinc_page,
    _pubchem_record_to_hit,
    _zinc_record_to_hit,
    apply_molecule_filters,
    fetch_random_molecules,
    fetch_random_pubchem_molecules,
    fetch_random_zinc_molecules,
    normalize_source,
    smiles_property_counts,
    source_label,
)


def test_normalize_source_and_label():
    assert normalize_source("ChEMBL") == SOURCE_CHEMBL
    assert normalize_source("pubchem") == SOURCE_PUBCHEM
    assert normalize_source("ZINC20") == SOURCE_ZINC
    assert normalize_source("zinc22") == SOURCE_ZINC
    assert source_label("pubchem") == "PubChem"
    with pytest.raises(ValueError):
        normalize_source("pdb")


def test_pubchem_record_to_hit():
    assert _pubchem_record_to_hit({}) is None
    hit = _pubchem_record_to_hit(
        {
            "CID": 2244,
            "CanonicalSMILES": "CC(=O)Oc1ccccc1C(=O)O",
            "Title": "Aspirin",
            "MolecularFormula": "C9H8O4",
            "MolecularWeight": 180.16,
            "IUPACName": "2-acetyloxybenzoic acid",
        }
    )
    assert isinstance(hit, RandomSourceMolecule)
    assert hit.source == SOURCE_PUBCHEM
    assert hit.molecule_id == "2244"
    assert hit.fields["CID"] == "2244"
    assert hit.fields["Source"] == "PubChem"
    assert hit.fields["Title"] == "Aspirin"


def test_zinc_record_to_hit():
    assert _zinc_record_to_hit({}) is None
    hit = _zinc_record_to_hit(
        {"zinc_id": "ZINC000000000007", "smiles": "CCO", "mwt": 46.07, "logp": -0.3}
    )
    assert hit is not None
    assert hit.source == SOURCE_ZINC
    assert hit.molecule_id == "ZINC000000000007"
    assert hit.fields["ZINC_ID"] == "ZINC000000000007"
    assert hit.fields["Source"] == "ZINC"
    assert hit.fields["MW"] == "46.07"
    cart = _zinc_record_to_hit(
        {"zincid": "ZINCtx00000f8wmW", "SMILES": "CCO", "tranche": "H29P270"}
    )
    assert cart is not None
    assert cart.molecule_id == "ZINCtx00000f8wmW"
    assert cart.smiles == "CCO"
    assert cart.fields["Tranche"] == "H29P270"


def test_fetch_zinc_page_polls_cartblanche_task(monkeypatch):
    calls: list[str] = []
    payloads = iter(
        [
            {"task": "abc-123"},
            {"status": "PENDING", "progress": 0},
            {
                "status": "SUCCESS",
                "result": json.dumps([{"zincid": "ZINC1", "SMILES": "CCO", "tranche": "H04P010"}]),
            },
        ]
    )

    def fake_json(url, *, timeout, error_prefix):  # noqa: ARG001
        calls.append(url)
        try:
            return next(payloads)
        except StopIteration:
            raise AssertionError(url)

    monkeypatch.setattr("molmanager.random_molecule_sources._http_get_json", fake_json)
    recs = _fetch_zinc_page(2, sleep=lambda _s: None)
    assert recs[0]["zincid"] == "ZINC1"
    assert recs[0]["SMILES"] == "CCO"
    assert "substance/random.json?count=2" in calls[0]
    assert calls[1].endswith("/substance/random/abc-123.json")
    assert calls[2].endswith("/substance/random/abc-123.json")


def test_fetch_random_pubchem_molecules_mocked(monkeypatch):
    id_pages = {
        0: [10, 11],
        50: [20],
    }
    props = {
        10: {"CID": 10, "CanonicalSMILES": "CCO"},
        11: {"CID": 11, "CanonicalSMILES": "CCC"},
        20: {"CID": 20, "CanonicalSMILES": "CCCC"},
    }
    starts = iter([0, 50])

    def fake_idlist(retstart, retmax, *, timeout=60.0):
        try:
            start = next(starts)
        except StopIteration:
            start = 0
        return id_pages.get(start, [])

    def fake_props(cids, *, timeout=60.0):
        return [props[c] for c in cids if c in props]

    monkeypatch.setattr("molmanager.random_molecule_sources._fetch_pubchem_idlist", fake_idlist)
    monkeypatch.setattr("molmanager.random_molecule_sources._fetch_pubchem_properties", fake_props)
    monkeypatch.setattr(
        "molmanager.random_molecule_sources.pubchem_compound_total_count", lambda **_: 200
    )

    hits = fetch_random_pubchem_molecules(3, seed=1, page_size=25)
    assert len(hits) == 3
    assert {h.molecule_id for h in hits} == {"10", "11", "20"}


def test_fetch_random_zinc_molecules_mocked(monkeypatch):
    pages = iter(
        [
            [
                {"zinc_id": "ZINC1", "smiles": "CCO"},
                {"zinc_id": "ZINC2", "smiles": "CCC"},
            ],
            [{"zinc_id": "ZINC3", "smiles": "CCCC"}],
        ]
    )

    def fake_page(count, **_kwargs):
        try:
            return next(pages)
        except StopIteration:
            return []

    monkeypatch.setattr("molmanager.random_molecule_sources._fetch_zinc_page", fake_page)
    hits = fetch_random_zinc_molecules(3, seed=1, page_size=25)
    assert len(hits) == 3
    assert {h.molecule_id for h in hits} == {"ZINC1", "ZINC2", "ZINC3"}


def test_fetch_random_molecules_dispatches_chembl(monkeypatch):
    def fake_chembl(count, **kwargs):
        return [
            RandomChemblMolecule(
                chembl_id="CHEMBL1",
                smiles="CCO",
                fields={"ChEMBL_ID": "CHEMBL1"},
            )
        ]

    monkeypatch.setattr(
        "molmanager.random_molecule_sources.fetch_random_chembl_molecules", fake_chembl
    )
    hits = fetch_random_molecules("ChEMBL", 1)
    assert len(hits) == 1
    assert hits[0].source == SOURCE_CHEMBL
    assert hits[0].molecule_id == "CHEMBL1"
    assert hits[0].fields["Source"] == "ChEMBL"


def test_smiles_property_counts_and_filters():
    ethanol = smiles_property_counts("CCO")
    assert ethanol is not None
    assert ethanol["heavy_atoms"] == 3
    assert ethanol["nitrogen"] == 0
    assert ethanol["oxygen"] == 1
    assert ethanol["rings"] == 0
    ethylamine = smiles_property_counts("CCN")
    assert ethylamine is not None
    assert ethylamine["nitrogen"] == 1
    assert ethylamine["oxygen"] == 0
    n_only = RandomMoleculeFilters(nitrogen=IntBounds(minimum=1))
    hit = RandomSourceMolecule(SOURCE_PUBCHEM, "1", "CCO", {"CID": "1"})
    assert apply_molecule_filters(hit, n_only) is None
    kept = apply_molecule_filters(
        RandomSourceMolecule(SOURCE_PUBCHEM, "2", "CCN", {"CID": "2"}), n_only
    )
    assert kept is not None
    assert kept.fields["NitrogenCount"] == "1"
    assert kept.fields["OxygenCount"] == "0"
    unconstrained = apply_molecule_filters(hit, RandomMoleculeFilters())
    assert unconstrained is hit


def test_fetch_random_pubchem_respects_nitrogen_filter(monkeypatch):
    props = {
        10: {"CID": 10, "CanonicalSMILES": "CCO"},
        11: {"CID": 11, "CanonicalSMILES": "CCN"},
        20: {"CID": 20, "CanonicalSMILES": "CCC"},
    }

    def fake_idlist(retstart, retmax, *, timeout=60.0):
        return [10, 11, 20]

    def fake_props(cids, *, timeout=60.0):
        return [props[c] for c in cids if c in props]

    monkeypatch.setattr("molmanager.random_molecule_sources._fetch_pubchem_idlist", fake_idlist)
    monkeypatch.setattr("molmanager.random_molecule_sources._fetch_pubchem_properties", fake_props)
    monkeypatch.setattr(
        "molmanager.random_molecule_sources.pubchem_compound_total_count", lambda **_: 200
    )
    hits = fetch_random_pubchem_molecules(
        1, seed=1, page_size=25, filters=RandomMoleculeFilters(nitrogen=IntBounds(minimum=1))
    )
    assert len(hits) == 1
    assert hits[0].molecule_id == "11"
    assert hits[0].fields["NitrogenCount"] == "1"


def test_fetch_rejects_bad_count():
    with pytest.raises(ValueError):
        fetch_random_pubchem_molecules(0)
    with pytest.raises(ValueError):
        fetch_random_zinc_molecules(501)


def test_random_molecule_dialog_source_field(qapp):  # noqa: ARG001
    pytest.importorskip("PyQt5.QtWidgets")
    from molmanager.ui.dialogs.random_molecule import RandomMoleculeDialog

    dlg = RandomMoleculeDialog(None)
    labels = [dlg.source_combo.itemText(i) for i in range(dlg.source_combo.count())]
    assert labels == ["ChEMBL", "PubChem", "ZINC"]
    p = dlg.params()
    assert p.source == SOURCE_CHEMBL
    assert p.count == 10
    assert dlg.btn_fetch.text() == "Fetch from ChEMBL"
    dlg.source_combo.setCurrentIndex(1)
    assert dlg.params().source == SOURCE_PUBCHEM
    assert dlg.btn_fetch.text() == "Fetch from PubChem"
    dlg.source_combo.setCurrentIndex(2)
    assert dlg.params().source == SOURCE_ZINC
    assert dlg.btn_fetch.text() == "Fetch from ZINC"
    assert p.filters.is_unconstrained()
    dlg._min_spins["nitrogen"].setValue(1)
    dlg._max_spins["heavy_atoms"].setValue(20)
    f = dlg.params().filters
    assert f.nitrogen.minimum == 1
    assert f.heavy_atoms.maximum == 20
    assert f.oxygen.is_unconstrained()
    dlg.close()


def test_random_molecule_help_lists_sources():
    from molmanager.ui.user_guides import guide_html

    h = guide_html("tools_random_molecule")
    assert "ChEMBL" in h
    assert "PubChem" in h
    assert "ZINC" in h
    assert "Source" in h
    assert "Heavy atoms" in h
    assert "Nitrogen" in h
    assert "Rotatable bonds" in h
    assert "Add to table" in h
    assert "Browser" in h
    assert "Topic unavailable" not in h
