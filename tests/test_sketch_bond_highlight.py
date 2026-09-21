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

"""Bond highlight underlay sizing for multi-order bonds."""

from __future__ import annotations

from PySide6.QtCore import QPoint
from PySide6.QtGui import QColor, QImage, QPainter

from mctoolkit.ui.sketcher.acs_style import acs_sketch_style
from mctoolkit.ui.sketcher.bonds import _bond_make
from mctoolkit.ui.sketcher.widget import SketchWidget


def test_bond_highlight_width_covers_multiple_bonds(qapp) -> None:  # noqa: ARG001
    w = SketchWidget()
    style = acs_sketch_style()
    single = w._bond_highlight_stroke_width(style, 1, selected=True)
    double = w._bond_highlight_stroke_width(style, 2, selected=True)
    triple = w._bond_highlight_stroke_width(style, 3, selected=True)
    assert double > single
    assert triple >= double
    assert double >= style.double_bond_offset_px


def test_double_bond_highlight_does_not_redraw_as_blue_double(qapp) -> None:  # noqa: ARG001
    """Highlights use a translucent centerline underlay, not thickened multi-line bonds."""
    w = SketchWidget()
    w.nodes = [
        {"id": 1, "pos": QPoint(40, 40), "element": "C"},
        {"id": 2, "pos": QPoint(100, 40), "element": "C"},
    ]
    w.bonds = [_bond_make(1, 2, 2, 0)]
    w.selected_bond_indices = {0}
    style = w._acs_style()
    img = QImage(140, 80, QImage.Format_ARGB32_Premultiplied)
    img.fill(QColor(255, 255, 255))
    p = QPainter(img)
    w._paint_sketch_bond_highlights(p, style)
    p.end()
    # Sample near the bond axis: underlay should leave a bluish tint.
    c = img.pixelColor(70, 40)
    assert c.blue() > c.red()
