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

"""PubChem similarity filtering and retrieve-field helpers."""

from __future__ import annotations

from types import SimpleNamespace

from molmanager.ui.external.pubchem import (
    FIELD_COMMON_NAME,
    FIELD_SYNONYMS,
    _PUBCHEM_FIELD_DEFS,
    _extract_medchem_fields,
    pubchem_hit_passes_tanimoto_threshold,
)


def test_passes_at_threshold() -> None:
    assert pubchem_hit_passes_tanimoto_threshold(0.85, 0.85) is True


def test_rejects_below_threshold() -> None:
    assert pubchem_hit_passes_tanimoto_threshold(0.84, 0.85) is False


def test_rejects_missing_score() -> None:
    assert pubchem_hit_passes_tanimoto_threshold(None, 0.7) is False


def test_field_defs_include_common_name_and_synonyms() -> None:
    keys = [k for k, *_ in _PUBCHEM_FIELD_DEFS]
    assert FIELD_COMMON_NAME in keys
    assert FIELD_SYNONYMS in keys


def test_extract_common_name_and_synonyms(monkeypatch) -> None:
    comp = SimpleNamespace(
        cid=702,
        iupac_name="ethanol",
        synonyms=["ethanol", "ethyl alcohol", "alcohol"],
    )
    monkeypatch.setattr(
        "molmanager.ui.external.pubchem._compound_title",
        lambda _c: "Ethanol",
    )
    out = _extract_medchem_fields(comp, selected=["IUPAC", FIELD_COMMON_NAME, FIELD_SYNONYMS])
    assert out["IUPAC"] == "ethanol"
    assert out[FIELD_COMMON_NAME] == "Ethanol"
    assert out[FIELD_SYNONYMS].startswith("ethanol; ethyl alcohol")


def test_extract_common_name_falls_back_to_first_synonym(monkeypatch) -> None:
    comp = SimpleNamespace(cid=1, synonyms=["trivial name", "other"])
    monkeypatch.setattr("molmanager.ui.external.pubchem._compound_title", lambda _c: "")
    out = _extract_medchem_fields(comp, selected=[FIELD_COMMON_NAME])
    assert out[FIELD_COMMON_NAME] == "trivial name"


def test_pubchem_dialog_has_name_checkboxes(qapp) -> None:  # noqa: ARG001
    from molmanager.ui.external.pubchem import PubChemDialog

    dlg = PubChemDialog()
    assert FIELD_COMMON_NAME in dlg.field_checks
    assert FIELD_SYNONYMS in dlg.field_checks
    assert dlg.field_checks[FIELD_COMMON_NAME].text() == "Common Name"
    assert dlg.field_checks[FIELD_SYNONYMS].text() == "Synonyms"
    dlg.close()
