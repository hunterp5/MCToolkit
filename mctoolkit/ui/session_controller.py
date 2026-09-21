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

"""``.mct`` session open/save/restore owned off the main-window MRO."""

from __future__ import annotations

from typing import Any, Protocol

from ..table.session_codec import SESSION_VERSION_CURRENT
from .app_roles import (
    JobScheduler,
    ProgressChrome,
    SessionState,
    StoreAccess,
    TableData,
    TableSelection,
)
from .session_csv import SessionCsv
from .session_plots import SessionPlots
from .session_restore import SessionRestore
from .session_save import SessionSave
from .session_table_layout import SessionTableLayout


class SessionLoadState(Protocol):
    """Parse/restore generation and the in-flight chunked-load contexts."""

    _session_parse_busy: bool
    _session_restore_ctx: dict | None
    _session_finalize_ctx: dict | None
    _csv_session_ctx: dict | None
    _session_load_generation: int
    _session_mutation_paused: bool
    _session_awaiting_ready: bool
    _session_waiting_for_render: bool


class SessionPendingState(Protocol):
    """Deferred chrome, layout, and follow-up flags until the workspace reveals."""

    _pending_session_clean_on_ready: bool
    _pending_session_column_order: list | None
    _pending_session_som_browse: Any
    _pending_session_table_layout: dict | None
    _pending_session_workspace_layout: Any
    _session_hold_workspace_surfaces: bool
    _session_plot_wait_deadline: float
    _session_search_want_visible: bool


class SessionSurfaceState(Protocol):
    """Live plot/protein hosts and table chrome the session document round-trips."""

    _protein_viewer_dialog: Any
    _protein_viewer_session: Any
    _plot_dialogs: list
    _floating_result_dialogs: list
    _plot_panel_splitter_sizes: Any
    _logarithmic_columns: set
    _workspace_layout: Any
    _session_sort: Any


class SessionWindowOps(Protocol):
    """Window/other-collaborator methods session save/restore still call."""

    def _filterable_data_column_names(self) -> list[str]: ...
    def _export_cell_text(self, row: int, col: int) -> str: ...
    def _register_plot_dialog(self, dlg: Any) -> None: ...
    def _bind_undocked_browser_dialog(self, dlg: Any) -> bool: ...
    def _register_floating_result_dialog(self, dlg: Any) -> None: ...
    def _sync_filter_panel_scroll_content(self) -> None: ...


class SessionHost(
    TableData,
    TableSelection,
    ProgressChrome,
    SessionState,
    JobScheduler,
    StoreAccess,
    SessionLoadState,
    SessionPendingState,
    SessionSurfaceState,
    SessionWindowOps,
    Protocol,
):
    """What session collect/restore needs from the window.

    Kernel table/progress/session/job/store members stay on the window, as do the
    plot/protein dialog handles the session document round-trips. Dimensionality-
    reduction dialog leftovers are reached with getattr.
    """

    def clear_all(self) -> None: ...
    def apply_filters(self) -> None: ...
    def calculate_global_bounds(self, *args: Any, **kwargs: Any) -> None: ...
    def chemistry_tool_structure_sources(self) -> list[str]: ...


class SessionController(
    SessionSave,
    SessionTableLayout,
    SessionPlots,
    SessionRestore,
    SessionCsv,
):
    """Session document collect/restore. Kernel holds sqlite, table, and plot hosts."""

    _SESSION_FORMAT = "mctoolkit_session"
    _SESSION_VERSION = SESSION_VERSION_CURRENT

    def __init__(self, app: SessionHost) -> None:
        self._app = app
