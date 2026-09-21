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

"""Filter card config helpers (no Qt)."""

from __future__ import annotations

from typing import Any, Mapping


def cfg_column(cfg: Mapping[str, Any] | None) -> str:
    """Column name from a filter card config.

    Prefers ``column``; accepts legacy ``p`` from older in-memory configs.
    """
    if not cfg:
        return ""
    col = cfg.get("column")
    if col is None or col == "":
        col = cfg.get("p")
    return str(col or "")
