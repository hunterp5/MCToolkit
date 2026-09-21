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

"""ACS 1996 sketch style parameters."""

from __future__ import annotations

from mctoolkit.ui.sketcher.acs_style import acs_sketch_style
from mctoolkit.ui.sketcher.constants import SKETCH_MEDIAN_BOND_PX


def test_acs_sketch_style_default_matches_sketch_bond_length() -> None:
    style = acs_sketch_style()
    assert style.median_bond_px == float(SKETCH_MEDIAN_BOND_PX)


def test_acs_sketch_style_scales_with_bond_length() -> None:
    small = acs_sketch_style(40.0)
    large = acs_sketch_style(80.0)
    assert large.label_font_pt >= small.label_font_pt
    assert large.double_bond_offset_px > small.double_bond_offset_px


def test_acs_sketch_style_readable_label_size() -> None:
    style = acs_sketch_style(SKETCH_MEDIAN_BOND_PX)
    assert style.label_font_pt >= 11
