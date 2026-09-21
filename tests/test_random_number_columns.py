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

"""Tests for Tools → Utilities → Random → Number generation helpers."""

import pytest

from mctoolkit.table.random_number_columns import (
    RANDOM_NUMBER_DISTRIBUTION_LABELS,
    RandomNumberParams,
    generate_random_values,
)


def test_uniform_reproducible_with_seed():
    p = RandomNumberParams(distribution="uniform", low=0.0, high=1.0, seed=42, decimals=4)
    a = generate_random_values(5, p)
    b = generate_random_values(5, p)
    assert a == b
    assert len(a) == 5
    for text in a:
        v = float(text)
        assert 0.0 <= v < 1.0


def test_integer_inclusive_range():
    p = RandomNumberParams(distribution="integer", low=2, high=2, seed=1)
    vals = generate_random_values(10, p)
    assert vals == ["2"] * 10


def test_integer_rejects_inverted_range():
    p = RandomNumberParams(distribution="integer", low=5, high=1)
    with pytest.raises(ValueError, match="Maximum"):
        generate_random_values(3, p)


def test_normal_clip():
    p = RandomNumberParams(
        distribution="normal",
        low=0.0,
        high=1.0,
        mean=0.5,
        std=10.0,
        seed=7,
        clip_normal=True,
        decimals=3,
    )
    vals = [float(x) for x in generate_random_values(50, p)]
    assert all(0.0 <= v <= 1.0 for v in vals)


def test_normal_requires_positive_std():
    p = RandomNumberParams(distribution="normal", low=0.0, high=1.0, mean=0.0, std=0.0)
    with pytest.raises(ValueError, match="Standard deviation"):
        generate_random_values(1, p)


def test_empty_count():
    p = RandomNumberParams(distribution="uniform", low=0.0, high=1.0, seed=0)
    assert generate_random_values(0, p) == []


def test_random_number_dialog_distribution_uses_item_data(qapp):  # noqa: ARG001
    from mctoolkit.ui.dialogs.random_number import RandomNumberDialog

    dlg = RandomNumberDialog(0)
    try:
        keys = [dlg.dist_combo.itemData(i) for i in range(dlg.dist_combo.count())]
        assert keys == [k for k, _ in RANDOM_NUMBER_DISTRIBUTION_LABELS]
        dlg.dist_combo.setCurrentIndex(keys.index("normal"))
        assert dlg._distribution_key() == "normal"
        assert dlg.mean_sb.isEnabled()
        assert dlg.decimals_sb.isEnabled()
        dlg.dist_combo.setCurrentIndex(keys.index("integer"))
        assert dlg._distribution_key() == "integer"
        assert not dlg.decimals_sb.isEnabled()
        assert not dlg.mean_sb.isEnabled()
    finally:
        dlg.close()
