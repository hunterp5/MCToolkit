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
"""Shared helpers for intentional exception swallowing."""

from __future__ import annotations

import logging
from typing import Any


def log_swallowed_exception(
    logger: logging.Logger,
    message: str,
    *,
    level: int = logging.DEBUG,
    exc_info: Any = True,
) -> None:
    """Log an exception that the caller intentionally does not re-raise.

    Prefer narrowing ``except`` clauses and re-raising unexpected failures.
    Use this only for best-effort UI/progress paths where failure is non-fatal.
    """
    logger.log(level, message, exc_info=exc_info)
