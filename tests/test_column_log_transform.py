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

"""Tests for column log10 transform helpers."""

from __future__ import annotations

import math

from mctoolkit.table.column_log_transform import (
    column_can_apply_log10,
    column_can_apply_precision,
    format_number_precision,
    format_transformed_number,
    transform_column_values_log10,
    transform_column_values_precision,
)


def test_column_can_apply_log10_requires_positive_numerics() -> None:
    assert column_can_apply_log10(["1", "10", "100"])
    assert column_can_apply_log10(["", "2.5", "N/A"])
    assert not column_can_apply_log10([])
    assert not column_can_apply_log10(["", "abc"])
    assert not column_can_apply_log10(["1", "0"])
    assert not column_can_apply_log10(["1", "-3"])


def test_transform_column_values_log10_roundtrip() -> None:
    src = {1: "100", 2: "10", 3: "", 4: "N/A"}
    logged = transform_column_values_log10(src, to_log=True)
    assert logged[1] == "2"
    assert logged[2] == "1"
    assert 3 not in logged
    assert 4 not in logged

    restored = transform_column_values_log10({**src, **logged}, to_log=False)
    assert float(restored[1]) == 100.0
    assert float(restored[2]) == 10.0


def test_format_transformed_number_handles_edge_cases() -> None:
    assert format_transformed_number(0.0) == "0"
    assert format_transformed_number(math.inf) == ""
    assert format_transformed_number(1.25) == "1.25"


def test_column_can_apply_precision_requires_numeric() -> None:
    assert column_can_apply_precision(["1.234", "N/A"])
    assert column_can_apply_precision(["-3"])
    assert not column_can_apply_precision([])
    assert not column_can_apply_precision(["", "abc"])


def test_transform_column_values_precision() -> None:
    src = {1: "1.23456", 2: "10", 3: "", 4: "N/A"}
    changed = transform_column_values_precision(src, decimals=2)
    assert changed[1] == "1.23"
    assert changed[2] == "10.00"
    assert 3 not in changed
    assert 4 not in changed
    assert format_number_precision(1.999, 0) == "2"
    assert format_number_precision(-0.0, 2) == "0.00"
