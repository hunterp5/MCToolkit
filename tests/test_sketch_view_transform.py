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

"""Sketcher view zoom transform (proportional paint scaling)."""

from __future__ import annotations

from PySide6.QtCore import QPoint

from mctoolkit.ui.sketcher.widget import SketchWidget


def test_widget_model_roundtrip_at_unit_scale(qapp) -> None:
    w = SketchWidget()
    w.resize(400, 400)
    w._view_scale = 1.0
    p = QPoint(120, 80)
    assert w._widget_point_to_model(p) == p


def test_zoom_scales_model_inverse(qapp) -> None:
    w = SketchWidget()
    w.resize(400, 400)
    w._view_scale = 2.0
    c = w.rect().center()
    p = QPoint(c.x() + 40, c.y() + 20)
    m = w._widget_point_to_model(p)
    assert m.x() == c.x() + 20
    assert m.y() == c.y() + 10
