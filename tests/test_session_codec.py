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

"""Unit tests for compact session codec."""

from __future__ import annotations

from molmanager.table.session_codec import (
    compact_session_document,
    dumps_session_document,
    expand_session_document,
    loads_session_bytes,
)


def test_compact_expand_roundtrip_preserves_cells():
    doc = {
        "format": "molmanager_session",
        "version": 1,
        "headers": ["ID_HIDDEN", "Structure", "SMILES", "MW"],
        "rows": [
            {"id": 1, "cells": {"SMILES": "CC", "MW": "30"}},
            {"id": 2, "cells": {"SMILES": "CCO", "MW": ""}},
        ],
        "next_oid": 3,
        "zoomed_ids": [],
        "filters": [],
        "mmp_ledger": None,
        "dock_results": None,
    }
    compact = compact_session_document(doc)
    assert compact["version"] == 2
    assert "rows" not in compact
    assert compact["ids"] == [1, 2]
    assert "zoomed_ids" not in compact
    assert "filters" not in compact
    assert "mmp_ledger" not in compact
    assert "dock_results" not in compact
    expanded = expand_session_document(compact)
    assert expanded["rows"][0]["cells"]["SMILES"] == "CC"
    assert expanded["rows"][1]["cells"]["MW"] == ""


def test_compact_expand_preserves_structure_smiles_not_protonated():
    doc = {
        "format": "molmanager_session",
        "version": 1,
        "headers": ["ID_HIDDEN", "Structure", "Protonated"],
        "rows": [{"id": 1, "cells": {"Protonated": "CC[NH3+]"}}],
        "structure_smiles": ["CCN"],
        "next_oid": 2,
    }
    compact = compact_session_document(doc)
    assert compact["structure_smiles"] == ["CCN"]
    expanded = expand_session_document(compact)
    assert expanded["rows"][0]["cells"]["Protonated"] == "CC[NH3+]"
    assert expanded["structure_smiles"] == ["CCN"]


def test_compact_does_not_treat_protonated_as_structure():
    doc = {
        "format": "molmanager_session",
        "version": 1,
        "headers": ["ID_HIDDEN", "Structure", "Protonated"],
        "rows": [{"id": 1, "cells": {"Protonated": "CC[NH3+]"}}],
        "next_oid": 2,
    }
    compact = compact_session_document(doc)
    assert compact["structure_smiles"] == [""]
    expanded = expand_session_document(compact)
    assert expanded["structure_smiles"] == [""]
    assert expanded["rows"][0]["cells"]["Protonated"] == "CC[NH3+]"


def test_expand_v1_does_not_invent_structure_from_protonated():
    v1 = {
        "format": "molmanager_session",
        "version": 1,
        "headers": ["ID_HIDDEN", "Structure", "Protonated"],
        "rows": [{"id": 1, "cells": {"Protonated": "CC[NH3+]"}}],
        "next_oid": 2,
    }
    expanded = expand_session_document(v1)
    assert expanded["structure_smiles"] == [""]


def test_gzip_dumps_loads_roundtrip():
    compact = compact_session_document(
        {
            "format": "molmanager_session",
            "version": 1,
            "headers": ["ID_HIDDEN", "Structure", "SMILES"],
            "rows": [{"id": 0, "cells": {"SMILES": "O"}}],
            "next_oid": 1,
        }
    )
    raw = dumps_session_document(compact)
    assert raw.startswith(b"\x1f\x8b")
    back = expand_session_document(loads_session_bytes(raw))
    assert back["rows"][0]["cells"]["SMILES"] == "O"


def test_compact_expand_preserves_structure_mols_and_bounds():
    from molmanager.table.session_codec import encode_mol_blob_b64
    from molmanager.chem.molecule_conversion import mol_graph_binary
    from rdkit import Chem

    blob_b64 = encode_mol_blob_b64(mol_graph_binary(Chem.MolFromSmiles("CCO")))
    compact = compact_session_document(
        {
            "format": "molmanager_session",
            "version": 1,
            "headers": ["ID_HIDDEN", "Structure", "SMILES", "MW"],
            "rows": [{"id": 4, "cells": {"SMILES": "CCO", "MW": "46.1"}}],
            "structure_smiles": ["CCO"],
            "structure_mols": [blob_b64],
            "global_bounds": {"MW": {"min": 10.0, "max": 99.5, "is_int": False}},
            "next_oid": 5,
        }
    )
    assert compact["version"] == 2
    assert compact["structure_mols"] == [blob_b64]
    assert compact["global_bounds"]["MW"]["max"] == 99.5
    expanded = expand_session_document(compact)
    assert expanded["structure_mols"] == [blob_b64]
    assert expanded["global_bounds"]["MW"]["min"] == 10.0
    raw = dumps_session_document(compact)
    roundtrip = expand_session_document(loads_session_bytes(raw))
    assert roundtrip["structure_mols"] == [blob_b64]


def test_compact_omits_empty_structure_mols_and_bounds():
    compact = compact_session_document(
        {
            "format": "molmanager_session",
            "version": 1,
            "headers": ["ID_HIDDEN", "Structure", "SMILES"],
            "rows": [{"id": 0, "cells": {"SMILES": "O"}}],
            "structure_mols": [""],
            "global_bounds": {},
            "next_oid": 1,
        }
    )
    assert "structure_mols" not in compact
    assert "global_bounds" not in compact


def test_session_zip_roundtrip_keeps_ensembles():
    from molmanager.table.session_codec import SESSION_ENSEMBLES_KEY

    compact = compact_session_document(
        {
            "format": "molmanager_session",
            "version": 1,
            "headers": ["ID_HIDDEN", "Structure", "SMILES"],
            "rows": [{"id": 0, "cells": {"SMILES": "O"}}],
            "next_oid": 1,
        }
    )
    compact[SESSION_ENSEMBLES_KEY] = b"SQLite-format-3\x00placeholder"
    raw = dumps_session_document(compact)
    assert raw.startswith(b"PK")
    assert compact[SESSION_ENSEMBLES_KEY] == b"SQLite-format-3\x00placeholder"
    back = loads_session_bytes(raw)
    assert back[SESSION_ENSEMBLES_KEY] == compact[SESSION_ENSEMBLES_KEY]
    expanded = expand_session_document(back)
    assert expanded["rows"][0]["cells"]["SMILES"] == "O"
    assert expanded[SESSION_ENSEMBLES_KEY] == compact[SESSION_ENSEMBLES_KEY]
