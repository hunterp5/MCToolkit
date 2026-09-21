# This file is part of MCToolkit.
# Copyright (C) 2026 Hunter Picard
#
# MCToolkit is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# MCToolkit is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with MCToolkit. If not, see <https://www.gnu.org/licenses/>.

"""Session snapshot assembly without Qt."""

from __future__ import annotations

from mctoolkit.chem.molecule_conversion import mol_from_smiles, mol_graph_binary
from mctoolkit.table.session_codec import SESSION_ENSEMBLES_KEY
from mctoolkit.table.session_document_build import (
    assemble_session_document,
    fill_structure_session_fields,
)


def test_fill_structure_session_fields_from_smiles_only():
    smiles, b64 = fill_structure_session_fields([None], ["CCO"])
    assert smiles == ["CCO"]
    assert b64[0]


def test_assemble_session_document_preserves_ensembles_and_drops_blobs():
    blob = mol_graph_binary(mol_from_smiles("CC"))
    doc = assemble_session_document(
        {
            "format": "mctoolkit_session",
            "version": 1,
            "headers": ["ID_HIDDEN", "Structure", "SMILES"],
            "rows": [{"id": 1, "cells": {"SMILES": "CC"}}],
            "structure_smiles": ["CC"],
            "structure_blobs": [blob],
            SESSION_ENSEMBLES_KEY: b"sqlite-bytes",
        }
    )
    assert doc[SESSION_ENSEMBLES_KEY] == b"sqlite-bytes"
    assert "structure_blobs" not in doc
    assert doc["ids"] == [1]
    assert doc.get("structure_mols")
