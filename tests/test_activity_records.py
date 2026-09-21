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

"""Unit tests for activity record helpers."""

from __future__ import annotations

from mctoolkit.services.activity_records import (
    build_oid_mol_activity_records,
    parse_activity_float,
)


def test_parse_activity_float() -> None:
    assert parse_activity_float("1.5") == 1.5
    assert parse_activity_float("  ") is None
    assert parse_activity_float("x") is None
    assert parse_activity_float(None) is None


def test_build_oid_mol_activity_records_skips_missing() -> None:
    mols = [(1, "m1"), (2, "m2"), (3, "m3")]
    activities = {1: 0.5, 3: 2.0}
    out = build_oid_mol_activity_records(
        mols,
        activity_for_oid=lambda oid: activities.get(oid),
    )
    assert out == [(1, "m1", 0.5), (3, "m3", 2.0)]
