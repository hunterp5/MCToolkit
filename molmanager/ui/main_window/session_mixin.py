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

from ...session_codec import SESSION_VERSION_CURRENT
from .session_csv_mixin import SessionCsvMixin
from .session_plots_mixin import SessionPlotsMixin
from .session_restore_mixin import SessionRestoreMixin
from .session_save_mixin import SessionSaveMixin
from .session_table_layout_mixin import SessionTableLayoutMixin


class SessionMixin(
    SessionSaveMixin,
    SessionTableLayoutMixin,
    SessionPlotsMixin,
    SessionRestoreMixin,
    SessionCsvMixin,
):
    _SESSION_FORMAT = "molmanager_session"
    _SESSION_FORMAT_ALIASES = frozenset(
        {"molmanager_session", "MOLMANAGER_session", "chemmanager_session"}
    )
    _SESSION_VERSION = SESSION_VERSION_CURRENT
