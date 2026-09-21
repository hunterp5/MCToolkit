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
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with mctoolkit.  If not, see <https://www.gnu.org/licenses/>.

"""Wedge/hash bond tuple orientation: tip (first atom) must not be multiply-bonded."""

from mctoolkit.ui.sketcher.bonds import _bond_make, reorient_wedged_bonds_tip_away_from_multiples


def test_reorient_swaps_when_tip_on_double_bonded_atom():
    # Nodes: 0 = sp3 (chiral side), 1 = alkene C (incident double to 2), 2 = other alkene C
    bonds = [
        _bond_make(1, 0, 1, 1),  # wrong: wedge tip (1) on alkene carbon
        _bond_make(1, 2, 2, 0),
    ]
    out = reorient_wedged_bonds_tip_away_from_multiples(bonds)
    assert out[0] == _bond_make(0, 1, 1, 1)
    assert out[1] == bonds[1]


def test_reorient_keeps_tip_on_sp3_when_base_is_alkene():
    bonds = [
        _bond_make(0, 1, 1, 2),  # hash: tip at 0 (sp3), base at 1 (alkene)
        _bond_make(1, 2, 2, 0),
    ]
    out = reorient_wedged_bonds_tip_away_from_multiples(bonds)
    assert out[0] == bonds[0]


def test_reorient_strips_when_both_endpoints_multiply_bonded():
    bonds = [
        _bond_make(3, 4, 1, 1),  # hypothetical single between two alkene-like centers
        _bond_make(3, 1, 2, 0),
        _bond_make(4, 2, 2, 0),
    ]
    out = reorient_wedged_bonds_tip_away_from_multiples(bonds)
    assert out[0] == _bond_make(3, 4, 1, 0)


def test_reorient_tip_at_more_substituted_atom():
    # 0 has three neighbors; 1 has two — tip should be at 0.
    bonds = [
        _bond_make(1, 0, 1, 1),  # tip wrongly at less-substituted 1
        _bond_make(0, 2, 1, 0),
        _bond_make(0, 3, 1, 0),
        _bond_make(1, 4, 1, 0),
    ]
    out = reorient_wedged_bonds_tip_away_from_multiples(bonds)
    assert out[0] == _bond_make(0, 1, 1, 1)
