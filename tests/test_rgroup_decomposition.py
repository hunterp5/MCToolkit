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

"""Unit tests for core-based decomposition table assembly."""

from mctoolkit.workers.rgroup_decomposition import (
    _assemble_table_rows,
    _collect_rg_columns,
    _rgroup_decomp_failure_message,
)


def test_collect_rg_columns_orders_core_then_r_groups():
    rows = [{"R2": "b", "Core": "c"}, {"R1": "a", "Core": "c2"}]
    assert _collect_rg_columns(rows) == ["Core", "R1", "R2"]


def test_rgroup_failure_message_prepare_core():
    msg = _rgroup_decomp_failure_message(
        RuntimeError("Invariant Violation\nCould not prepare at least one core\n...")
    )
    assert "could not prepare" in msg.lower() or "core" in msg.lower()


def test_assemble_table_rows_aligns_unmatched():
    oids = [10, 11, 12]
    rg_rows = [{"Core": "C1", "R1": "x"}, {"Core": "C2", "R1": "y"}]
    unmatched = [1]
    col_keys = ["Core", "R1"]
    out = _assemble_table_rows(oids, rg_rows, unmatched, col_keys, "P")
    assert len(out) == 3
    assert out[0][0] == 10 and out[0][1]["P_Core"] == "C1" and out[0][1]["P_R1"] == "x"
    assert out[1][0] == 11 and out[1][1]["P_Core"] == "N/A" and out[1][1]["P_R1"] == "N/A"
    assert out[2][0] == 12 and out[2][1]["P_Core"] == "C2" and out[2][1]["P_R1"] == "y"
