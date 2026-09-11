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

from molmanager.session_codec import (
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
    }
    compact = compact_session_document(doc)
    assert compact["version"] == 2
    assert "rows" not in compact
    assert compact["ids"] == [1, 2]
    assert "zoomed_ids" not in compact
    assert "filters" not in compact
    assert "mmp_ledger" not in compact
    expanded = expand_session_document(compact)
    assert expanded["rows"][0]["cells"]["SMILES"] == "CC"
    assert expanded["rows"][1]["cells"]["MW"] == ""


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
