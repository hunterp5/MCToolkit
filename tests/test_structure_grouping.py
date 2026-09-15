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

"""Structure deduplication for ionization-backed workers."""

from __future__ import annotations

from rdkit import Chem

from molmanager.services.structure_grouping import group_rows_by_structure


def test_group_rows_by_structure_deduplicates_identical_smiles() -> None:
    m1 = Chem.MolFromSmiles("CCO")
    m2 = Chem.MolFromSmiles("CCO")
    assert m1 is not None and m2 is not None
    rows = [(10, m1), (20, m2), (30, Chem.MolFromSmiles("CCN"))]
    order, rep, oids_map = group_rows_by_structure(rows)
    assert len(order) == 2
    assert len(oids_map[order[0]]) == 2
    assert 10 in oids_map[order[0]] and 20 in oids_map[order[0]]
    assert oids_map[order[1]] == [30]
