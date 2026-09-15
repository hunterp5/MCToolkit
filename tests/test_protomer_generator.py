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

"""Protomer grouping (dedupe) helpers — no Uni-pKa required."""

from __future__ import annotations

from rdkit import Chem

from molmanager.services.structure_grouping import group_rows_by_structure, structure_key


def test_structure_key_canonical_smiles_merges_tautomers_of_same_graph():
    m1 = Chem.MolFromSmiles("CCO")
    m2 = Chem.MolFromSmiles("C(C)O")
    assert m1 is not None and m2 is not None
    assert structure_key(m1) == structure_key(m2)


def test_group_protomer_rows_dedupes_same_structure_multiple_oids():
    m1 = Chem.MolFromSmiles("c1ccccc1")
    m2 = Chem.MolFromSmiles("c1ccccc1")
    assert m1 is not None and m2 is not None
    order, rep, oids = group_rows_by_structure([(10, m1), (20, m2), (30, None)])
    assert len(order) == 1
    k = order[0]
    assert len(oids[k]) == 2
    assert set(oids[k]) == {10, 20}
    assert rep[k] is not None


def test_group_protomer_rows_keeps_distinct_structures():
    m1 = Chem.MolFromSmiles("CC")
    m2 = Chem.MolFromSmiles("CCC")
    assert m1 is not None and m2 is not None
    order, _rep, oids = group_rows_by_structure([(1, m1), (2, m2)])
    assert len(order) == 2
    assert sum(len(oids[k]) for k in order) == 2
