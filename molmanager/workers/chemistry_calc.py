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
"""Custom calculator worker (AST calculator_expressions)."""

from __future__ import annotations

import logging
import math
import re
import threading
import time

from PySide6.QtCore import QRunnable

from ..platform_support.exception_policy import log_swallowed_exception
from ..table.calculator_expressions import eval_custom_calc_expression
from .signals import emit_partial_results_if_cancelled

logger = logging.getLogger(__name__)


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


class CustomCalcWorker(QRunnable):
    """Evaluate a numeric expression per row via the restricted calculator_expressions path.

    Only ``math`` helpers and rewritten column variables are in scope. This is not a
    full sandbox—do not run sessions with untrusted expressions on sensitive machines.
    """

    def __init__(
        self,
        row_data,
        expression,
        signals,
        cancel_event: threading.Event | None = None,
        progress_state=None,
    ):
        super().__init__()
        self.row_data, self.expression, self.signals = row_data, expression, signals
        self.cancel_event = cancel_event
        self.progress_state = progress_state

    def run(self):
        results = []
        expr_template = (self.expression or "").strip()
        # Support both bracketed refs ([MW]) and bare refs (MW).
        req_vars = re.findall(r"\\[(.*?)\\]", expr_template)
        math_scope = {k: getattr(math, k) for k in dir(math) if not k.startswith("_")}
        rows = list(self.row_data)
        tot = max(len(rows), 1)
        cancelled = False
        prog_last_emit = 0.0
        prog_last_done = -1
        done = 0
        for done, (idx, data_map) in enumerate(rows, start=1):
            if self.cancel_event is not None and self.cancel_event.is_set():
                cancelled = True
                break
            try:
                expr = expr_template
                local_scope = dict(math_scope)

                # Build stable variable bindings and rewrite the expression to use them.
                # We avoid injecting raw numbers repeatedly so we can also support bare variable tokens.
                var_keys = list(data_map.keys()) if isinstance(data_map, dict) else []
                # Include bracketed-only variables even if missing from row map.
                for v in req_vars:
                    if v not in var_keys:
                        var_keys.append(v)

                for i, var in enumerate(var_keys):
                    safe_name = f"__v{i}"
                    raw = data_map.get(var, 0) if isinstance(data_map, dict) else 0
                    try:
                        val = float(str(raw).strip()) if str(raw).strip() != "" else 0.0
                    except Exception:
                        val = 0.0
                    local_scope[safe_name] = val
                    expr = expr.replace(f"[{var}]", safe_name)
                    # Replace bare tokens that match the variable name (word-boundary safe).
                    expr = re.sub(rf"\\b{re.escape(var)}\\b", safe_name, expr)

                # Common convenience: if expression is just a variable label, allow it.
                if not expr:
                    res = "Empty expression (nothing to evaluate)."
                else:
                    res = eval_custom_calc_expression(expr, local_scope)
            except Exception as e:
                res = describe_custom_calc_error(e)
            results.append((idx, f"{res:.3f}" if isinstance(res, float) else str(res)))
            if self.progress_state is not None:
                self.progress_state.update("Calculator…", done, tot)
            now = time.monotonic()
            step = max(1, tot // 40)
            if (
                done <= 1
                or done >= tot
                or (done - prog_last_done) >= step
                or (now - prog_last_emit) >= 0.15
            ):
                prog_last_emit = now
                prog_last_done = done
                try:
                    self.signals.tool_progress.emit("Calculator…", done, tot)
                except Exception:
                    log_swallowed_exception(logger, "CustomCalcWorker progress emit failed")
        if self.progress_state is not None:
            self.progress_state.update("Calculator…", min(done, tot) if rows else 0, tot)
        emit_partial_results_if_cancelled(self.signals, "Calculator", len(results), tot, cancelled)
        self.signals.custom_calc.emit(results)
