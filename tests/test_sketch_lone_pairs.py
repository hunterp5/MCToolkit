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
# along with MCToolkit.  If not, see <https://www.gnu.org/licenses/>.

"""Lone-pair count helpers for sketcher display."""

from __future__ import annotations

from mctoolkit.ui.sketcher.chem import sketch_lone_pair_count


def test_sketch_lone_pair_counts() -> None:
    # Water / alcohol O (one drawn bond + one implicit H)
    assert sketch_lone_pair_count("O", bond_order_sum=1, implicit_h=1) == 2
    # Carbonyl / ether O
    assert sketch_lone_pair_count("O", bond_order_sum=2, implicit_h=0) == 2
    # Ammonia N
    assert sketch_lone_pair_count("N", bond_order_sum=3, implicit_h=0) == 1
    # Fluorine
    assert sketch_lone_pair_count("F", bond_order_sum=1, implicit_h=0) == 3
    # Carbon / hydrogen
    assert sketch_lone_pair_count("C", bond_order_sum=4, implicit_h=0) == 0
    assert sketch_lone_pair_count("H", bond_order_sum=1, implicit_h=0) == 0
    # Charged oxygen (alkoxide): one bond, no H
    assert sketch_lone_pair_count("O", formal_charge=-1, bond_order_sum=1, implicit_h=0) == 3
