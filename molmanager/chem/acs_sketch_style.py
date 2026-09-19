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

"""ACS Document 1996 drawing parameters (aligned with RDKit ``SetACS1996Mode``)."""

from __future__ import annotations

from dataclasses import dataclass

from rdkit.Chem.Draw import rdMolDraw2D

_ACS_MEAN_BOND_ANG = 1.5


@dataclass(frozen=True)
class AcsSketchStyle:
    """Screen-pixel drawing constants for the interactive sketch canvas."""

    median_bond_px: float
    bond_width_px: float
    double_bond_offset_px: float
    triple_bond_offset_px: float
    label_font_pt: int
    charge_font_pt: int
    wedge_half_width_px: float
    ink: tuple[int, int, int]
    selection_pen_width: float
    hover_pen_width: float
    atom_selection_radius_extra: float
    bond_selection_extra_width: float


def acs_sketch_style(median_bond_px: float) -> AcsSketchStyle:
    """Derive canvas style from RDKit ACS1996 options scaled to the sketch bond length."""
    op = rdMolDraw2D.MolDrawOptions()
    rdMolDraw2D.SetACS1996Mode(op, _ACS_MEAN_BOND_ANG)
    med = max(float(median_bond_px), 8.0)
    fixed = max(float(op.fixedBondLength), 1.0)
    bond_w = max(1.0, float(op.bondLineWidth) * med / fixed)
    multi = max(2.5, float(op.multipleBondOffset) * med)
    label_pt = max(11, int(round(med * 0.22)))
    return AcsSketchStyle(
        median_bond_px=med,
        bond_width_px=bond_w,
        double_bond_offset_px=multi,
        triple_bond_offset_px=multi * 1.55,
        label_font_pt=label_pt,
        charge_font_pt=max(7, label_pt - 3),
        wedge_half_width_px=max(3.5, med * float(op.multipleBondOffset)),
        ink=(0, 0, 0),
        selection_pen_width=2.0,
        hover_pen_width=1.5,
        atom_selection_radius_extra=4.0,
        bond_selection_extra_width=1.2,
    )
