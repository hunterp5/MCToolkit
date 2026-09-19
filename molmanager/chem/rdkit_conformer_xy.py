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

"""Write x/y coordinates onto an RDKit 2D conformer."""

from __future__ import annotations

from collections.abc import Sequence


def set_conformer_xy(conf, xs: Sequence[float], ys: Sequence[float]) -> bool:
    """Set planar coordinates on *conf*. Returns False if RDKit Geometry is unavailable."""
    try:
        from rdkit.Geometry import Point3D
    except ImportError:
        return False
    n = conf.GetNumAtoms()
    for i in range(n):
        conf.SetAtomPosition(i, Point3D(float(xs[i]), float(ys[i]), 0.0))
    return True
