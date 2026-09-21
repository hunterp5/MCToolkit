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

"""RDKit default MolDraw2D palette mapping for sketcher labels."""

from mctoolkit.ui.sketcher.element_colors import rdkit_default_element_rgb


def test_rdkit_default_colors_common_heteroatoms():
    assert rdkit_default_element_rgb("C") == (0, 0, 0)
    assert rdkit_default_element_rgb("H") == (0, 0, 0)
    assert rdkit_default_element_rgb("D") == (0, 0, 0)
    assert rdkit_default_element_rgb("N") == (0, 0, 255)
    assert rdkit_default_element_rgb("O") == (255, 0, 0)
    assert rdkit_default_element_rgb("F") == (51, 204, 204)
    assert rdkit_default_element_rgb("Cl") == (0, 204, 0)
    assert rdkit_default_element_rgb("Br") == (128, 77, 26)
    assert rdkit_default_element_rgb("I") == (161, 31, 239)


def test_unknown_symbol_falls_back_to_black():
    assert rdkit_default_element_rgb("Xx") == (0, 0, 0)
