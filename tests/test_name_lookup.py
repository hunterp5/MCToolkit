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

"""PubChem common-name / synonym helpers for Calculate Descriptors."""

from __future__ import annotations

from rdkit import Chem

from molmanager.medchem_descriptors import mol_inchi_key
from molmanager.name_lookup import (
    CompoundNames,
    fetch_pubchem_names_for_inchikeys,
    format_synonym_list,
    int_fns_need_name_lookup,
    lookup_names_for_mols,
    names_cell_value,
    split_name_lookup_descriptors,
)


def test_format_synonym_list_dedupes_and_caps() -> None:
    text = format_synonym_list(
        ["aspirin", "Aspirin", "acetylsalicylic acid", "", "ASA"],
        limit=2,
    )
    assert text == "aspirin; acetylsalicylic acid"


def test_names_cell_value_na_when_missing() -> None:
    assert names_cell_value(None, "COMMON_NAME") == "N/A"
    assert names_cell_value(CompoundNames(), "COMMON_NAME") == "N/A"
    assert names_cell_value(CompoundNames(common_name="ethanol"), "COMMON_NAME") == "ethanol"
    assert names_cell_value(CompoundNames(synonyms="a; b"), "SYNONYMS") == "a; b"


def test_split_name_lookup_descriptors() -> None:
    local_d, local_f, name_d, name_f = split_name_lookup_descriptors(
        ["LogP", "Common Name", "Synonyms"],
        ["MolLogP", "COMMON_NAME", "SYNONYMS"],
    )
    assert local_d == ["LogP"]
    assert local_f == ["MolLogP"]
    assert name_d == ["Common Name", "Synonyms"]
    assert name_f == ["COMMON_NAME", "SYNONYMS"]
    assert int_fns_need_name_lookup(("MolWt", "COMMON_NAME"))
    assert not int_fns_need_name_lookup(("MolWt", "SMILES"))


def test_fetch_pubchem_names_for_inchikeys_maps_title_and_synonyms() -> None:
    props = [
        {"CID": 2244, "InChIKey": "BSYNRYMUTXBXSQ-UHFFFAOYSA-N", "Title": "aspirin"},
        {"CID": 702, "InChIKey": "LFQSCWFLJHTTHZ-UHFFFAOYSA-N", "Title": "ethanol"},
    ]
    syns = [
        {"CID": 2244, "Synonym": ["aspirin", "Acetylsalicylic acid", "ASA"]},
        {"CID": 702, "Synonym": ["ethanol", "ethyl alcohol"]},
    ]
    out = fetch_pubchem_names_for_inchikeys(
        ["BSYNRYMUTXBXSQ-UHFFFAOYSA-N", "LFQSCWFLJHTTHZ-UHFFFAOYSA-N"],
        want_common=True,
        want_synonyms=True,
        before_request=lambda: None,
        get_properties=lambda *_a, **_k: props,
        get_synonyms=lambda *_a, **_k: syns,
    )
    asp = out["BSYNRYMUTXBXSQ-UHFFFAOYSA-N"]
    assert asp.common_name == "aspirin"
    assert asp.synonyms.startswith("aspirin; Acetylsalicylic acid")
    eth = out["LFQSCWFLJHTTHZ-UHFFFAOYSA-N"]
    assert eth.common_name == "ethanol"
    assert "ethyl alcohol" in eth.synonyms


def test_fetch_uses_first_synonym_when_title_missing() -> None:
    props = [{"CID": 1, "InChIKey": "AAAAAAAAAAAAAA-UHFFFAOYSA-N", "Title": ""}]
    syns = [{"CID": 1, "Synonym": ["trivial name", "other"]}]
    out = fetch_pubchem_names_for_inchikeys(
        ["AAAAAAAAAAAAAA-UHFFFAOYSA-N"],
        want_common=True,
        want_synonyms=True,
        before_request=lambda: None,
        get_properties=lambda *_a, **_k: props,
        get_synonyms=lambda *_a, **_k: syns,
    )
    rec = out["AAAAAAAAAAAAAA-UHFFFAOYSA-N"]
    assert rec.common_name == "trivial name"
    assert rec.synonyms == "trivial name; other"


def test_lookup_names_for_mols_dedupes_by_inchikey() -> None:
    mol = Chem.MolFromSmiles("CCO")
    assert mol is not None
    key = mol_inchi_key(mol)
    calls: list[list[str]] = []

    def fetch(keys, want_common, want_synonyms):
        calls.append(list(keys))
        return {
            k: CompoundNames(common_name="ethanol", synonyms="ethanol; ethyl alcohol") for k in keys
        }

    rows = lookup_names_for_mols(
        [mol, mol, None],
        want_common=True,
        want_synonyms=True,
        fetch_inchikey_batch=fetch,
        fetch_smiles_one=lambda *_a, **_k: None,
        min_interval_s=0.0,
    )
    assert calls == [[key]]
    assert rows[0] is not None and rows[0].common_name == "ethanol"
    assert rows[1] is rows[0] or (rows[1] is not None and rows[1].common_name == "ethanol")
    assert rows[2] is None


def test_lookup_names_skips_network_when_cancelled() -> None:
    mol = Chem.MolFromSmiles("CCO")
    assert mol is not None
    calls: list[int] = []

    class _Cancel:
        def is_set(self) -> bool:
            return True

    def fetch(keys, want_common, want_synonyms):
        calls.append(1)
        return {}

    rows = lookup_names_for_mols(
        [mol],
        want_common=True,
        want_synonyms=False,
        cancel_event=_Cancel(),
        fetch_inchikey_batch=fetch,
        min_interval_s=0.0,
    )
    assert calls == []
    assert rows == [None]


def test_calc_worker_fills_pubchem_name_columns(monkeypatch) -> None:
    from molmanager.workers.chemistry_tools import CalcWorker
    from molmanager.workers.signals import WorkerSignals

    sigs = WorkerSignals()
    out: dict[str, object] = {}
    sigs.calculated.connect(lambda rows, headers: out.update({"rows": rows, "headers": headers}))

    def fake_lookup(mols, *, want_common, want_synonyms, **_kwargs):
        assert want_common and want_synonyms
        rec = CompoundNames(common_name="ethanol", synonyms="ethanol; ethyl alcohol")
        return [rec for _ in mols]

    monkeypatch.setattr(
        "molmanager.workers.chemistry_descriptors.lookup_names_for_mols",
        fake_lookup,
    )
    worker = CalcWorker(
        data=[(1, "CCO"), (2, "CCO")],
        disp_headers=["Common Name", "Synonyms"],
        int_fns=["COMMON_NAME", "SYNONYMS"],
        is_smiles=True,
        signals=sigs,
    )
    worker.run()
    rows = {oid: data for oid, data in out["rows"]}  # type: ignore[union-attr]
    assert out["headers"] == ["Common Name", "Synonyms"]
    assert rows[1]["Common Name"] == "ethanol"
    assert "ethyl alcohol" in rows[1]["Synonyms"]
    assert rows[2]["Common Name"] == "ethanol"


def test_calc_worker_name_lookup_with_local_descriptor(monkeypatch) -> None:
    from molmanager.workers.chemistry_tools import CalcWorker
    from molmanager.workers.signals import WorkerSignals

    sigs = WorkerSignals()
    out: dict[str, object] = {}
    sigs.calculated.connect(lambda rows, headers: out.update({"rows": rows, "headers": headers}))

    monkeypatch.setattr(
        "molmanager.workers.chemistry_descriptors.lookup_names_for_mols",
        lambda mols, **_k: [CompoundNames(common_name="ethanol") for _ in mols],
    )
    worker = CalcWorker(
        data=[(7, "CCO")],
        disp_headers=["Mol Weight", "Common Name"],
        int_fns=["MolWt", "COMMON_NAME"],
        is_smiles=True,
        signals=sigs,
    )
    worker.run()
    oid, row = out["rows"][0]  # type: ignore[index]
    assert oid == 7
    assert float(row["Mol Weight"]) > 40.0
    assert row["Common Name"] == "ethanol"
