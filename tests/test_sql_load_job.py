# This file is part of mctoolkit.
# Copyright (C) 2026 Hunter Picard
#
# mctoolkit is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# mctoolkit is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with mctoolkit. If not, see <https://www.gnu.org/licenses/>.

"""SQL-load job helpers. No Qt, no qapp fixture, no main window."""

from __future__ import annotations

import sys

from mctoolkit.table.sql_load_job import cells_from_sql_mapping, mol_blob_from_smiles


def test_sql_load_job_does_not_pull_in_qt():
    for name in list(sys.modules):
        if name.startswith("mctoolkit.table.sql_load_job"):
            del sys.modules[name]
    qt_already_loaded = "PySide6.QtWidgets" in sys.modules
    import mctoolkit.table.sql_load_job  # noqa: F401

    if not qt_already_loaded:
        assert "PySide6.QtWidgets" not in sys.modules


def test_cells_from_sql_mapping_stringifies_nulls():
    assert cells_from_sql_mapping(["a", "b"], {"a": 1, "b": None}) == {"a": "1", "b": ""}


def test_mol_blob_from_smiles_rejects_empty_and_invalid():
    assert mol_blob_from_smiles("") is None
    assert mol_blob_from_smiles("not-a-smiles") is None
    blob = mol_blob_from_smiles("CCO")
    assert isinstance(blob, bytes) and blob
