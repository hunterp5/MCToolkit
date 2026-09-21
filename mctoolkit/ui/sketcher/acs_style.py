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

"""ACS Document 1996 drawing parameters (aligned with RDKit ``SetACS1996Mode``)."""

from __future__ import annotations

from ...chem.acs_sketch_style import AcsSketchStyle, acs_sketch_style as _acs_sketch_style
from .constants import SKETCH_MEDIAN_BOND_PX

__all__ = ["AcsSketchStyle", "acs_sketch_style"]


def acs_sketch_style(median_bond_px: float = SKETCH_MEDIAN_BOND_PX) -> AcsSketchStyle:
    """Derive canvas style from RDKit ACS1996 options scaled to the sketch bond length."""
    return _acs_sketch_style(median_bond_px)
