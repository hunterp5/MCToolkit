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
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with MCToolkit. If not, see <https://www.gnu.org/licenses/>.

"""Tests for descriptor/fingerprint reuse helpers."""

from __future__ import annotations

from rdkit import Chem

from mctoolkit.descriptors.descriptor_cache_reuse import (
    column_complete_for_oids,
    is_valid_descriptor_cell,
)
from mctoolkit.chem.fingerprint_cache import clear as clear_fp_cache
from mctoolkit.chem.fingerprint_cache import store_from_mol
from mctoolkit.chem.rdkit_fingerprints import (
    fingerprint_bitvect_for_row,
    spec_for_label,
)


def test_is_valid_descriptor_cell():
    assert is_valid_descriptor_cell("12.3")
    assert not is_valid_descriptor_cell("")
    assert not is_valid_descriptor_cell("N/A")


def test_fingerprint_bitvect_for_row_uses_cache():
    clear_fp_cache()
    mol = Chem.MolFromSmiles("CCO")
    spec = spec_for_label("Morgan (r=2, n=2048)")
    assert spec is not None
    store_from_mol(7, spec.internal_key, mol)
    fp = fingerprint_bitvect_for_row(7, mol, spec.label)
    assert fp is not None
    assert int(fp.GetNumOnBits()) > 0


def test_column_complete_for_oids_false_when_any_missing():
    headers = ["MW"]
    assert not column_complete_for_oids(
        "MW",
        [1, 2],
        headers=headers,
        cell_text=lambda row, col: "1.0" if row == 0 else "",
        row_for_oid=lambda oid: oid - 1,
    )
