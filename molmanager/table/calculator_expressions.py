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
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with MolManager.  If not, see <https://www.gnu.org/licenses/>.

"""Restricted numeric evaluation for the custom calculator (no ``eval``)."""

from __future__ import annotations

import ast
import operator
from typing import Any

_BINOPS: dict[type[ast.operator], Any] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}

_UNARY: dict[type[ast.unaryop], Any] = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}


def eval_custom_calc_expression(expr: str, local_scope: dict[str, Any]) -> Any:
    """Evaluate a numeric expression using only ``ast`` operators and names in ``local_scope``.

    ``local_scope`` is expected to contain ``__v0``-style bindings and callables/values from
    ``math`` (same contract as the legacy ``eval`` path).
    """
    tree = ast.parse(expr, mode="eval")
    if not isinstance(tree, ast.Expression):
        raise ValueError("Expected a single expression")
    return _eval_node(tree.body, local_scope)


def _eval_node(node: ast.AST, scope: dict[str, Any]) -> Any:
    if isinstance(node, ast.Constant):
        v = node.value
        if isinstance(v, bool):
            return float(v)
        if isinstance(v, int):
            return v
        if isinstance(v, float):
            return v
        raise ValueError("Only numeric constants are allowed")

    if isinstance(node, ast.UnaryOp):
        op_t = type(node.op)
        fn = _UNARY.get(op_t)
        if fn is None:
            raise ValueError(f"Unsupported unary operator: {op_t.__name__}")
        return fn(_eval_node(node.operand, scope))

    if isinstance(node, ast.BinOp):
        op_t = type(node.op)
        fn = _BINOPS.get(op_t)
        if fn is None:
            raise ValueError(f"Unsupported binary operator: {op_t.__name__}")
        return fn(_eval_node(node.left, scope), _eval_node(node.right, scope))

    if isinstance(node, ast.Call):
        if node.keywords:
            raise ValueError("Keyword arguments are not allowed")
        for a in node.args:
            if isinstance(a, ast.Starred):
                raise ValueError("Star-args are not allowed")
        if not isinstance(node.func, ast.Name):
            raise ValueError("Only direct function calls (e.g. sqrt(...)) are allowed")
        name = node.func.id
        if name not in scope:
            raise NameError(name)
        callee = scope[name]
        if not callable(callee):
            raise TypeError(f'"{name}" is not callable')
        args = [_eval_node(a, scope) for a in node.args]
        return callee(*args)

    if isinstance(node, ast.Name):
        if node.id not in scope:
            raise NameError(node.id)
        val = scope[node.id]
        if callable(val):
            raise TypeError(f'Bare name "{node.id}" refers to a function; call it with parentheses')
        return val

    raise ValueError(f"Syntax not allowed in calculator expressions: {type(node).__name__}")
