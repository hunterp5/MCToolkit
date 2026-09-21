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
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with MCToolkit. If not, see <https://www.gnu.org/licenses/>.

"""Tests for dual-handle RangeSlider used by numeric filter cards."""

from mctoolkit.ui.filters.range_slider import RangeSlider


def test_range_slider_clamps_and_orders_values(qapp):
    slider = RangeSlider()
    slider.setRange(0, 100)
    slider.setValues(80, 20)
    assert slider.lowerValue() == 20
    assert slider.upperValue() == 80

    slider.setLowerValue(90)
    assert slider.lowerValue() == 80
    assert slider.upperValue() == 80

    slider.setUpperValue(50)
    assert slider.lowerValue() == 80
    assert slider.upperValue() == 80

    slider.setValues(10, 60)
    slider.setUpperValue(40)
    assert slider.lowerValue() == 10
    assert slider.upperValue() == 40


def test_filter_card_uses_single_range_slider(qapp):  # noqa: ARG001
    from mctoolkit.ui.filters.cards import FilterCard
    from mctoolkit.ui.filters.range_slider import RangeSlider
    from mctoolkit.ui.main_window import ChemistryWorkspaceWindow

    w = ChemistryWorkspaceWindow()
    w.global_bounds = {"MW": {"min": 100.0, "max": 500.0, "is_int": False}}
    card = FilterCard(["MW"], w, initial_property="MW")
    assert isinstance(card.range_slider, RangeSlider)
    assert card.min_edit.text() == "100.00"
    assert card.max_edit.text() == "500.00"
    cfg = card.get_cfg()
    assert cfg["min"] == 100.0
    assert cfg["max"] == 500.0

    card.min_edit.setText("150")
    card.max_edit.setText("400")
    card.sync_from_text()
    cfg = card.get_cfg()
    assert cfg["min"] == 150.0
    assert cfg["max"] == 400.0
