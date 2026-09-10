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

"""Qt WebEngine / Chromium process flags (must run before WebEngine loads)."""

from __future__ import annotations

import os

_QTWEBENGINE_CHROMIUM_FLAGS_ENV = "QTWEBENGINE_CHROMIUM_FLAGS"
_QUIET_LOG_LEVEL_FLAG = "--log-level=3"


def configure_qtwebengine_quiet_logs() -> str:
    """
    Hide Chromium GPU ERROR spam on stderr (SharedImage / GLES while rotating WebGL).

    Must run before ``QtWebEngineWidgets`` is imported. Leaves an existing
    ``--log-level=`` value alone so a user can still raise Chromium verbosity.
    """
    current = (os.environ.get(_QTWEBENGINE_CHROMIUM_FLAGS_ENV) or "").strip()
    parts = current.split()
    if not any(part.startswith("--log-level=") for part in parts):
        parts.append(_QUIET_LOG_LEVEL_FLAG)
    flags = " ".join(parts)
    os.environ[_QTWEBENGINE_CHROMIUM_FLAGS_ENV] = flags
    return flags
