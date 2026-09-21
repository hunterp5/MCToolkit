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

"""Environment-variable lookup for ``MCTOOLKIT_*`` keys."""

from __future__ import annotations

import os

ENV_PREFIX = "MCTOOLKIT_"


def env_suffix(name: str) -> str:
    """Strip ``MCTOOLKIT_`` if present, otherwise return ``name`` unchanged."""
    if name.startswith(ENV_PREFIX):
        return name[len(ENV_PREFIX) :]
    return name


def env_get(name: str, default: str | None = None) -> str | None:
    """Return the ``MCTOOLKIT_*`` value, or *default* when unset/blank."""
    raw = os.environ.get(ENV_PREFIX + env_suffix(name))
    if raw is not None and str(raw).strip() != "":
        return raw
    return default


def env_set(name: str, value: str) -> None:
    """Write a ``MCTOOLKIT_*`` key."""
    os.environ[ENV_PREFIX + env_suffix(name)] = value


def env_pop(name: str, default: str | None = None) -> str | None:
    """Remove a ``MCTOOLKIT_*`` key and return the previous value."""
    return os.environ.pop(ENV_PREFIX + env_suffix(name), default)
