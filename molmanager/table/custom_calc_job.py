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
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with MolManager. If not, see <https://www.gnu.org/licenses/>.

"""Evaluate custom-calculator rows without Qt."""

from __future__ import annotations

import math
import re
import threading
from collections.abc import Callable, Sequence

from .calculator_expressions import eval_custom_calc_expression

ProgressFn = Callable[[str, int, int], None]


def describe_custom_calc_error(exc: BaseException) -> str:
    """Human-readable explanation for failed custom calculator evaluation."""
    if isinstance(exc, ZeroDivisionError):
        return "Division by zero (the denominator evaluates to zero)."
    if isinstance(exc, OverflowError):
        return "Numeric overflow (the result is too large to represent)."
    if isinstance(exc, ValueError):
        msg = str(exc).strip()
        if msg:
            return f"Invalid value: {msg}"
        return "Invalid value for this operation (for example, square root of a negative number)."
    if isinstance(exc, TypeError):
        msg = str(exc).strip()
        if msg:
            return f"Incompatible types: {msg}"
        return "Incompatible types for this operation."
    if isinstance(exc, NameError):
        name = getattr(exc, "name", None) or ""
        if name:
            return f'Unknown name "{name}" (only math helpers and column variables are allowed).'
        return f"Unknown name in expression: {exc}"
    if isinstance(exc, SyntaxError):
        msg = getattr(exc, "msg", None) or str(exc)
        return f"Invalid expression syntax: {msg}"
    if isinstance(exc, ArithmeticError):
        return f"Arithmetic error: {exc}"
    return f"Could not evaluate: {exc.__class__.__name__}: {exc}"


def evaluate_custom_calc_rows(
    row_data: Sequence[tuple[object, dict]],
    expression: str,
    *,
    cancel_event: threading.Event | None = None,
    on_progress: ProgressFn | None = None,
) -> tuple[list[tuple[object, str]], bool]:
    """Return ``(results, cancelled)`` for each ``(oid, column_map)`` row."""
    results: list[tuple[object, str]] = []
    expr_template = (expression or "").strip()
    req_vars = re.findall(r"\[(.*?)\]", expr_template)
    math_scope = {k: getattr(math, k) for k in dir(math) if not k.startswith("_")}
    rows = list(row_data)
    tot = max(len(rows), 1)
    cancelled = False
    done = 0
    for done, (idx, data_map) in enumerate(rows, start=1):
        if cancel_event is not None and cancel_event.is_set():
            cancelled = True
            break
        try:
            expr = expr_template
            local_scope = dict(math_scope)
            var_keys = list(data_map.keys()) if isinstance(data_map, dict) else []
            for var in req_vars:
                if var not in var_keys:
                    var_keys.append(var)
            for i, var in enumerate(var_keys):
                safe_name = f"__v{i}"
                raw = data_map.get(var, 0) if isinstance(data_map, dict) else 0
                try:
                    val = float(str(raw).strip()) if str(raw).strip() != "" else 0.0
                except (TypeError, ValueError):
                    val = 0.0
                local_scope[safe_name] = val
                expr = expr.replace(f"[{var}]", safe_name)
                expr = re.sub(rf"\b{re.escape(var)}\b", safe_name, expr)
            if not expr:
                res: object = "Empty expression (nothing to evaluate)."
            else:
                res = eval_custom_calc_expression(expr, local_scope)
        except Exception as exc:
            res = describe_custom_calc_error(exc)
        results.append((idx, f"{res:.3f}" if isinstance(res, float) else str(res)))
        if on_progress is not None:
            on_progress("Calculator…", done, tot)
    if on_progress is not None:
        on_progress("Calculator…", min(done, tot) if rows else 0, tot)
    return results, cancelled
