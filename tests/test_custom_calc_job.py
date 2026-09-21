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

"""Custom-calculator job body. No Qt, no qapp fixture, no main window."""

from __future__ import annotations

import math
import sys
import threading

from mctoolkit.table.custom_calc_job import describe_custom_calc_error, evaluate_custom_calc_rows


def test_custom_calc_job_does_not_pull_in_qt():
    for name in list(sys.modules):
        if name.startswith("mctoolkit.table.custom_calc_job"):
            del sys.modules[name]
    qt_already_loaded = "PySide6.QtWidgets" in sys.modules
    import mctoolkit.table.custom_calc_job  # noqa: F401

    if not qt_already_loaded:
        assert "PySide6.QtWidgets" not in sys.modules


def test_evaluate_custom_calc_rows_computes_column_math():
    results, cancelled = evaluate_custom_calc_rows(
        [(1, {"MW": "12.0"}), (2, {"MW": "3"})],
        "[MW] * 2",
    )
    assert cancelled is False
    assert results == [(1, "24.000"), (2, "6.000")]


def test_evaluate_custom_calc_rows_accepts_column_snapshot():
    results, cancelled = evaluate_custom_calc_rows(
        ([1, 2], {"MW": ["12.0", "3"]}),
        "[MW] * 2",
    )
    assert cancelled is False
    assert results == [(1, "24.000"), (2, "6.000")]


def test_evaluate_custom_calc_rows_honors_cancel_event():
    cancel = threading.Event()
    cancel.set()
    results, cancelled = evaluate_custom_calc_rows(
        [(1, {"MW": "12"}), (2, {"MW": "3"})],
        "[MW] * 2",
        cancel_event=cancel,
    )
    assert cancelled is True
    assert results == []


def test_describe_custom_calc_error_explains_zero_division():
    assert "zero" in describe_custom_calc_error(ZeroDivisionError()).lower()
    assert "overflow" in describe_custom_calc_error(OverflowError()).lower()
    assert math.sqrt(4.0) == 2.0
