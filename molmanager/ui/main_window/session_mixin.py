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

"""Compat grouping for session file-splits. Implementation lives on ``SessionController``."""

from __future__ import annotations

from ...table.session_codec import SESSION_VERSION_CURRENT
from ..session_csv import SessionCsv
from ..session_plots import SessionPlots
from ..session_restore import SessionRestore
from ..session_save import SessionSave
from ..session_table_layout import SessionTableLayout


class SessionMixin(
    SessionSave,
    SessionTableLayout,
    SessionPlots,
    SessionRestore,
    SessionCsv,
):
    _SESSION_FORMAT = "molmanager_session"
    _SESSION_FORMAT_ALIASES = frozenset(
        {"molmanager_session", "MOLMANAGER_session", "chemmanager_session", "mctoolkit_session"}
    )
    _SESSION_VERSION = SESSION_VERSION_CURRENT
