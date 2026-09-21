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

"""Ingest chunks, SQLite mirror rebuild, and Render 2D batch/result flush."""

from __future__ import annotations

from typing import Any, Protocol

from PySide6.QtCore import QObject

from .app_roles import (
    JobScheduler,
    ProgressChrome,
    SessionState,
    StoreAccess,
    TableData,
    TableSelection,
)
from .table_build_export import TableBuildExport, TableBuildExportState
from .table_build_ingest import TableBuildIngest
from .table_build_layout import TableBuildLayout
from .table_build_render import TableBuildRender
from .table_build_render_results import TableBuildRenderResults
from .table_build_sqlite import TableBuildSqlite


class TableBuildIngestState(Protocol):
    """Chunked file-ingest queue and incremental SQLite flags."""

    _pending_batches: list
    _processing_batches: bool
    _last_batch_received: bool
    _ingest_append_mode: bool
    _ingest_sqlite_bulk_active: bool
    _ingest_sqlite_paused_dirty: bool
    _ingest_sqlite_bulk_headers: list[str] | None
    _ingest_waiting_for_render: bool


class TableBuildIngestChrome(Protocol):
    """Loading overlay and post-ingest color-cache leftovers on the window."""

    _ingest_prep_before_reveal: bool
    _loading_detail: Any
    _table_stack: Any
    _import_building_progress_shown: bool
    _structures_queued: int
    _post_ingest_color_headers: list
    _post_ingest_color_idx: int
    _structure_field_override: Any


class TableBuildSqliteState(Protocol):
    """SQLite mirror rebuild generation, job id, and dirty flags."""

    _sqlite_rebuild_in_progress: bool
    _sqlite_store_dirty: bool
    _sqlite_export_ctx: dict | None
    _sqlite_rebuild_pending_path: Any
    _sqlite_rebuild_bg_job_id: str | None
    _sqlite_rebuild_gen: int
    _sqlite_rebuild_pending_filters: bool
    _sqlite_rebuild_stale: bool


class TableBuildRenderFlags(Protocol):
    """Render 2D batch session, pending results, and sort freeze."""

    _render2d_batch_active: bool
    _render2d_pending: dict
    _render2d_snapshot: Any
    _render2d_pixmap_target: str | None
    _render2d_accept_session: int | None
    _render2d_batch_oids_ordered: list
    _render2d_column_pixmap_mode: bool
    _render2d_saved_sort_enabled: bool | None


class TableBuildRenderFlush(Protocol):
    """Eager/lazy Structure flush and cancel token for a Render 2D batch."""

    _render2d_eager_flush_idx: int
    _render2d_eager_flush_queue: list | None
    _render2d_eager_uniform_height: bool
    _render2d_lazy_flush: bool
    _render2d_flush_max_width: int
    _render2d_cancel_event: Any
    _render2d_batch_session_tag: int
    _render2d_session_id: int


class TableBuildRenderProgress(Protocol):
    """Import-progress counters and per-oid lookup for a Render 2D batch."""

    _render2d_after_ingest: bool
    _render2d_progress_last_done: int
    _render2d_progress_last_emit: float
    _render2d_queue: Any
    _render2d_row_by_oid: dict | None
    _import_progress_active: bool
    _import_render_goal: int
    _import_render_done: int


class TableBuildLayoutState(Protocol):
    """Whether the Structure column lazy-scroll hook is already on the view."""

    _structure_lazy_scroll_hooked: bool


class TableBuildWindowOps(Protocol):
    """Hottest window/other-collaborator methods ingest and Render 2D still call."""

    def _mol_for_structure_row(self, row: int) -> Any: ...
    def _on_tool_progress(self, message: str, done: int, total: int) -> None: ...
    def _clear_tool_progress(self, *, status_message: str | None = None) -> None: ...
    def _resolve_structure_row_for_oid(self, oid: int) -> int: ...
    def _merge_import_headers(self, incoming: list[str]) -> None: ...
    def _prepare_tool_dialog(self, dialog: Any) -> None: ...
    def _row_cells_from_mol(self, mol: Any) -> dict[str, str]: ...
    def _abort_if_only_selected_but_empty(
        self, only_selected: bool, allowed: set | frozenset | None, title: str
    ) -> bool: ...


class TableBuildWindowChrome(Protocol):
    """Remaining window forwards ingest needs that do not fit ``TableBuildWindowOps``."""

    def _mol_from_structure_text(self, raw: str) -> Any: ...
    def _clear_filter_target_smiles_cache(self) -> None: ...
    def _set_ingest_loading(self, loading: bool) -> None: ...
    def _set_workspace_stack_index(self, index: int) -> None: ...
    def _migrate_legacy_confs_cells_to_sidecar(self) -> None: ...


class TableBuildHost(
    TableData,
    TableSelection,
    ProgressChrome,
    SessionState,
    JobScheduler,
    StoreAccess,
    TableBuildIngestState,
    TableBuildIngestChrome,
    TableBuildSqliteState,
    TableBuildRenderFlags,
    TableBuildRenderFlush,
    TableBuildRenderProgress,
    TableBuildLayoutState,
    TableBuildWindowOps,
    TableBuildWindowChrome,
    TableBuildExportState,
    Protocol,
):
    """What table ingest, SQLite rebuild, and Render 2D need from the window.

    Kernel table/progress/session/job/store members stay on the window. Ingest and
    render flags also stay there because ``render2d_batch_active`` and HeldJob read
    them on the facade. Overflow session-restore hooks are reached with getattr.
    """

    def cell_text(self, row: int, col: int) -> str: ...
    def chemistry_tool_structure_sources(self) -> list[str]: ...
    def start_render_worker(self, *args: Any, **kwargs: Any) -> None: ...
    def apply_filters(self) -> None: ...
    def calculate_global_bounds(self, *args: Any, **kwargs: Any) -> None: ...


class TableBuildPipeline(
    QObject,
    TableBuildIngest,
    TableBuildSqlite,
    TableBuildLayout,
    TableBuildRender,
    TableBuildRenderResults,
    TableBuildExport,
):
    """GUI-thread table-build owner. Timers and generation counters stay on the kernel."""

    def __init__(self, app: TableBuildHost) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self._app = app
