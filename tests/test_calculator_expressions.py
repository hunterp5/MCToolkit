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

"""Restricted AST evaluation for custom calculator expressions."""

from __future__ import annotations

import math

import pytest

from mctoolkit.table.calculator_expressions import eval_custom_calc_expression


def _scope():
    s = {k: getattr(math, k) for k in dir(math) if not k.startswith("_")}
    s["__v0"] = 10.0
    s["__v1"] = 3.0
    return s


def test_arithmetic_and_precedence():
    assert eval_custom_calc_expression("__v0 + __v1 * 2", _scope()) == pytest.approx(16.0)


def test_math_call():
    assert eval_custom_calc_expression("sqrt(__v0)", _scope()) == pytest.approx(math.sqrt(10))


def test_rejects_bare_function_name():
    with pytest.raises(TypeError):
        eval_custom_calc_expression("sqrt", _scope())


def test_rejects_unknown_name():
    with pytest.raises(NameError):
        eval_custom_calc_expression("__import__('os')", _scope())


def test_rejects_attribute_access():
    with pytest.raises(ValueError):
        eval_custom_calc_expression("(1).__class__", _scope())


def test_rejects_list_literal():
    with pytest.raises(ValueError):
        eval_custom_calc_expression("[1]", _scope())
