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

import logging
import sys
import threading
import time

from PyQt5.QtCore import QThreadPool, QTimer, Qt, pyqtSlot
from PyQt5.QtGui import QCloseEvent, QKeySequence
from PyQt5.QtWidgets import (
    QAction,
    QActionGroup,
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QToolButton,
    QUndoStack,
    QVBoxLayout,
    QWidget,
)

from ...config import load_config
from ...exception_policy import log_swallowed_exception

logger = logging.getLogger(__name__)
from ...memory_usage import format_process_memory_status
from ...performance import PerformanceTracker
from ...tool_progress import ToolProgressState, format_tool_progress_text
from ...storage import SqliteTableStore
from ...workers import (
    FilterApplySignals,
    RenderWorker,
    SqliteRebuildSignals,
    SubstructureFilterSignals,
    WorkerSignals,
)
from ..background_activity import BackgroundActivityHub
from ..compound_table_model import (
    CompoundTableModel,
    CompoundTableView,
    StructureDelegate,
    STRUCTURE_COLUMN_HORIZONTAL_PADDING,
    structure_column_minimum_width,
    structure_depiict_height,
    structure_depiict_width,
    structure_row_default_height,
)
from ..filter_proxy_model import FilterProxyModel
from ..filters.cards import FilterCardsHost
from ..table_selection_delegate import RowHighlightDelegate
from ..process_queue import ProcessQueueManager
from ..citations_dialog import open_citations_dialog
from ..user_guides import open_user_guide_dialog
from .cluster_mixin import ClusterMixin
from .dimension_reduction_mixin import DimensionReductionMixin
from .medchem_space_mixin import MedChemSpaceMixin
from .qsar_mixin import QsarMixin
from .mpo_mixin import MpoMixin
from .session_mixin import SessionMixin
from .table_ui_mixin import TableUIMixin
from .ingest_export_mixin import IngestExportMixin
from .chemistry_mixin import ChemistryMixin
from ..gui_settings_mixin import GuiSettingsMixin


_FILTER_PANEL_BTN_H = 28
_FILTER_PANEL_BTN_SPACING = 6


def _configure_filter_panel_button(btn: QPushButton) -> None:
    """Compact fixed-height action button for the filter panel footer."""
    btn.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
    btn.setFixedHeight(_FILTER_PANEL_BTN_H)
    btn.setMinimumWidth(0)


class _FilterCardsScrollArea(QScrollArea):
    """Keeps filter cards within the scroll viewport width (no horizontal spill past the panel)."""

    def __init__(self, host: QWidget, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._host = host
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setWidget(host)

    def resizeEvent(self, event) -> None:  # noqa: N802 — Qt API name
        super().resizeEvent(event)
        self._clamp_host_width()

    def _clamp_host_width(self) -> None:
        vp = self.viewport()
        if vp is not None and self._host is not None:
            self._host.setMaximumWidth(max(1, vp.width()))


class ChemicalTableApp(
    QMainWindow,
    SessionMixin,
    TableUIMixin,
    IngestExportMixin,
    ChemistryMixin,
    ClusterMixin,
    DimensionReductionMixin,
    MedChemSpaceMixin,
    QsarMixin,
    MpoMixin,
    GuiSettingsMixin,
):
    """Main PyQt window: compound table, structure column, tools, and RDKit-backed chemistry.

    Each row stores **one explicit structure** (connectivity + stereo as encoded). Isomerism scope
    (E/Z, R/S, tautomers, atropisomers, diastereomers) is summarized for developers in
    ``docs/STEREO_AND_ISOMERISM.md``. Valence, bond order, aromaticity handling, and atom typing in
    the sketcher are summarized in ``docs/VALENCE_BONDS_AND_AROMATICITY.md``.
    """

    def __init__(self):
        super().__init__()
        self.setWindowTitle("MolManager")
        # Avoid modal exit prompts during pytest teardown / headless runs.
        self._suppress_exit_session_prompt = "pytest" in sys.modules
        # Unsaved workspace vs last save / successful open (file or session).
        self._session_dirty = False
        self._session_mutation_paused = False
        self._pending_session_clean_on_ready = False
        self.resize(1500, 900)
        self.threadpool = QThreadPool()
        cfg = load_config()
        # Cap via MOLMANAGER_MAX_THREADPOOL (1–64); otherwise scale gently with CPU count.
        if cfg.max_threadpool is not None:
            cap = cfg.max_threadpool
        else:
            ideal = max(1, QThreadPool.globalInstance().maxThreadCount() or 4)
            cap = max(4, min(ideal * 2, 16))
        self.threadpool.setMaxThreadCount(cap)
        # Dedicated pool so 2D rendering does not compete with descriptor/calc/IO workers.
        self._render_threadpool = QThreadPool()
        if cfg.render_threadpool is not None:
            ren_cap = cfg.render_threadpool
        else:
            ren_cap = max(2, min(cap, 8))
        self._render_threadpool.setMaxThreadCount(ren_cap)
        self.mols, self.headers, self.filters, self.global_bounds = {}, [], [], {}
        self._logarithmic_columns: set[str] = set()
        self.zoomed_ids = set()
        self.signals = WorkerSignals()
        _qc = Qt.QueuedConnection
        self.signals.mols_loaded.connect(self.on_file_loaded, _qc)
        self.signals.structure_source_probe.connect(self._on_structure_source_probe, _qc)
        self.signals.rendered.connect(self.on_row_ready, _qc)
        self.signals.rendered_batch.connect(self.on_render2d_rows_ready, _qc)
        self.signals.washed.connect(self.on_wash_finished, _qc)
        self.signals.neutralized.connect(self.on_neutralize_finished, _qc)
        self.signals.fast_prepared.connect(self.on_fast_prepare_finished, _qc)
        self.signals.explicit_hydrogens_added.connect(self.on_add_explicit_hydrogens_finished, _qc)
        self.signals.explicit_hydrogens_removed.connect(
            self.on_remove_explicit_hydrogens_finished, _qc
        )
        self.signals.calculated.connect(self.on_calc_finished, _qc)
        self.signals.conformers_finished.connect(self.on_conformers_finished, _qc)
        self.signals.superpose_finished.connect(self.on_superpose_finished, _qc)
        self.signals.custom_calc.connect(self.on_custom_calc_finished, _qc)
        self.signals.partial_results.connect(self._on_partial_results_notice, _qc)
        self.signals.rgroup_decomp_finished.connect(self.on_rgroup_decomp_finished, _qc)
        self.signals.rgroup_decomp_failed.connect(self.on_rgroup_decomp_failed, _qc)
        self.signals.fragment_decomp_finished.connect(self.on_fragment_decomp_finished, _qc)
        self.signals.fragment_decomp_failed.connect(self.on_fragment_decomp_failed, _qc)
        self.signals.fragment_recomp_finished.connect(self.on_fragment_recomp_finished, _qc)
        self.signals.fragment_recomp_failed.connect(self.on_fragment_recomp_failed, _qc)
        self.signals.reaction_enum_finished.connect(self.on_reaction_enum_finished, _qc)
        self.signals.reaction_enum_failed.connect(self.on_reaction_enum_failed, _qc)
        self.signals.mmp_finished.connect(self.on_mmp_finished, _qc)
        self.signals.mmp_failed.connect(self.on_mmp_failed, _qc)
        self.signals.activity_cliff_finished.connect(self.on_activity_cliff_finished, _qc)
        self.signals.activity_cliff_failed.connect(self.on_activity_cliff_failed, _qc)
        self.signals.mmp_neighborhood_finished.connect(self.on_mmp_neighborhood_finished, _qc)
        self.signals.mmp_neighborhood_failed.connect(self.on_mmp_neighborhood_failed, _qc)
        self.signals.sali_finished.connect(self.on_sali_finished, _qc)
        self.signals.sali_failed.connect(self.on_sali_failed, _qc)
        self.signals.cluster_failed.connect(self.on_cluster_failed, _qc)
        self.signals.cluster_explore_finished.connect(self.on_cluster_explore_finished, _qc)
        self.signals.easydock_finished.connect(self.on_easydock_finished, _qc)
        self.signals.easydock_failed.connect(self.on_easydock_failed, _qc)
        self.signals.export_finished.connect(self._on_export_finished_message, _qc)
        self.signals.tool_progress.connect(self._on_tool_progress, _qc)
        self._substructure_filter_signals = SubstructureFilterSignals()
        self._substructure_filter_signals.finished.connect(self._on_substructure_filter_finished)
        self._substructure_filter_signals.failed.connect(self._on_substructure_filter_failed)
        self._filter_apply_signals = FilterApplySignals()
        self._filter_apply_signals.finished.connect(self._on_filter_apply_finished)
        self._filter_apply_signals.failed.connect(self._on_filter_apply_failed)
        self._substructure_job_gen = 0
        self._filter_job_gen = 0
        self._filter_pending_substructure = None
        self._filter_bg_job_id = None
        self._substructure_job_smarts = None
        self._substructure_target_mol_cache = {}
        self._partial_results_notice = None
        self._ingest_loading = False
        self._ingest_prep_before_reveal = False
        self._ingest_sqlite_bulk_active = False
        self._ingest_sqlite_paused_dirty = False
        self._ingest_sqlite_bulk_headers = None
        self._structures_queued = 0
        self._import_progress_active = False
        self._import_render_done = 0
        self._import_render_goal = 0
        self._import_building_progress_shown = False
        self._undo_stack = QUndoStack(self)
        self._undo_stack.setUndoLimit(load_config().table_undo_limit)
        self._filter_proxy_model: FilterProxyModel | None = None
        self.init_ui()
        self._apply_filters_timer = QTimer(self)
        self._apply_filters_timer.setSingleShot(True)
        self._apply_filters_timer.timeout.connect(self._apply_filters_impl)
        self._chunked_filter_timer = QTimer(self)
        self._chunked_filter_timer.setSingleShot(True)
        self._chunked_filter_timer.timeout.connect(self._chunked_filter_step)
        self._chunked_filter_state = None
        self._bounds_recalc_timer = QTimer(self)
        self._bounds_recalc_timer.setSingleShot(True)
        self._bounds_recalc_timer.timeout.connect(self.calculate_global_bounds)
        self._init_gui_settings()
        self.init_menubar()
        self._refresh_structure_delegate_theme()
        self.next_oid = 0
        self._structure_field_override = None
        self._structure_choice_event = threading.Event()
        self._structure_choice_event.set()
        # incremental batch processing state to avoid UI freezes
        self._pending_batches = []  # list of (mols_list, is_last)
        self._processing_batches = False
        self._last_batch_received = False
        self._plot_dialogs: list = []
        self._floating_result_dialogs: list = []
        self._dock_result_windows: list = []
        self._last_dock_results: dict | None = None
        self._dock_results_mode = False
        self._scope_sync_targets: list = []
        self._cached_plot_selected_oids: frozenset[int] | None = None
        self._selected_oids_override: frozenset[int] | None = None
        self._in_programmatic_table_selection = False
        self._table_selection_job_gen = 0
        self._table_selection_ctx = None
        self._column_selection_anchor: int | None = None
        self._plot_table_sync_timer = QTimer(self)
        self._plot_table_sync_timer.setSingleShot(True)
        self._plot_table_sync_timer.timeout.connect(self._sync_active_plots_from_table_selection)
        self._selection_browser_dialog = None
        self._som_browser_dialog = None
        self._som_browse_records = []
        self._mmp_browser_dialog = None
        self._mmp_ledger_dialog = None
        self._mmp_last_pairs = []
        self._mmp_last_activity_column = ""
        self._activity_cliff_map_dialog = None
        self._mmp_neighborhood_map_dialog = None
        self._sali_map_dialog = None
        self._sali_browser_dialog = None
        self._sketcher_dialog = None
        self._protein_viewer_dialog = None
        self._calculator_dialog = None
        self._data_analysis_dialog = None
        self._cluster_dialog = None
        self._external_db_dialog = None
        self._pubchem_dialog = None
        self._chembl_dialog = None
        self._patent_query_dialog = None
        self._smina_dock_dialog = None
        self._pdbqt_generator_dialog = None
        self._pdb_fixer_dialog = None
        self._export_busy = False
        self._export_prep = None
        self._render2d_queue = None
        self._render2d_batch_active = False
        self._render2d_saved_sort_enabled = None
        self._render2d_row_by_oid = None
        self._render2d_cancel_event = None
        self._render2d_pixmap_target = None
        self._render2d_column_pixmap_mode = True
        self._render2d_session_id = 0
        self._render2d_accept_session = None
        self._render2d_batch_session_tag = 0
        self._render2d_pending = {}
        self._render2d_batch_oids_ordered = []
        self._render2d_snapshot = None
        self._render2d_lazy_flush = False
        self._structure_lazy_scroll_hooked = False
        self._render2d_batch_done_event = threading.Event()
        self._render2d_batch_done_event.set()
        self._render2d_queue_payload = None
        self._render2d_queue_cancel_event = None
        self._ingest_append_mode = False
        self.process_queue = ProcessQueueManager(self)
        self._background_jobs: dict[str, str] = {}
        self.background_activity = BackgroundActivityHub(self)
        self.background_activity.attach()
        self._plot_replot_timer = QTimer(self)
        self._plot_replot_timer.setSingleShot(True)
        self._plot_replot_timer.timeout.connect(self._replot_active_plots)
        self._processes_dialog = None
        self._perf = PerformanceTracker(
            enabled=cfg.perf_metrics_enabled,
            log_every=cfg.perf_log_every,
        )
        # Local SQLite cache for text/numeric filter pushdown and column search at 100k+ rows.
        self._sqlite_store = SqliteTableStore()
        self._sqlite_store_dirty = False
        self._sqlite_rebuild_in_progress = False
        self._sqlite_rebuild_gen = 0
        self._sqlite_rebuild_pending_path = None
        self._sqlite_rebuild_pending_filters = False
        self._sqlite_rebuild_stale = False
        self._sqlite_rebuild_signals = SqliteRebuildSignals()
        self._sqlite_rebuild_signals.finished.connect(self._on_sqlite_rebuild_finished, _qc)
        self._sqlite_rebuild_signals.failed.connect(self._on_sqlite_rebuild_failed, _qc)
        self._wire_sqlite_store_dirty_tracking()
        self._wire_table_plot_refresh()
        self._tool_progress_state = ToolProgressState()
        self._tool_progress_poll_timer = QTimer(self)
        self._tool_progress_poll_interval_ms = int(cfg.tool_progress_poll_ms)
        self._tool_progress_poll_timer.setInterval(self._tool_progress_poll_interval_ms)
        self._tool_progress_poll_timer.timeout.connect(self._poll_tool_progress_state)
        self._background_job_ui_depth = 0
        self._last_tool_progress_status = ""
        self._init_status_memory_tracker(cfg)

    def _init_status_memory_tracker(self, cfg) -> None:
        self._memory_status_timer = QTimer(self)
        self._memory_status_timer.timeout.connect(self._refresh_status_memory_label)
        if cfg.status_memory_enabled:
            self._memory_status_timer.setInterval(int(cfg.status_memory_poll_ms))
            host = getattr(self, "_status_host", None)
            if host is None or host.isVisible():
                self._memory_status_timer.start()
            self._refresh_status_memory_label()
        else:
            self._memory_status_label.hide()

    def _refresh_status_memory_label(self) -> None:
        label = getattr(self, "_memory_status_label", None)
        if label is None or not label.isVisible():
            return
        text = format_process_memory_status()
        if text is None:
            label.setText("")
            label.setToolTip("Process memory unavailable on this platform.")
            return
        label.setText(text)

    def _begin_tool_progress(self, message: str, total: int) -> None:
        """Start polled status updates for a long-running queued tool."""
        total_i = max(1, int(total))
        self._tool_progress_active_label = str(message or "")
        self._tool_progress_state.begin(message, total_i)
        self._on_tool_progress(message, 0, total_i)
        if not self._tool_progress_poll_timer.isActive():
            self._tool_progress_poll_timer.start()

    def _poll_tool_progress_state(self) -> None:
        message, done, total, active = self._tool_progress_state.snapshot()
        if not active:
            self._tool_progress_poll_timer.stop()
            return
        self._on_tool_progress(message, done, total)

    def _background_job_ui_active(self) -> bool:
        return int(getattr(self, "_background_job_ui_depth", 0)) > 0

    def _enter_background_job_ui(self) -> None:
        """Reduce main-thread churn while a queued tool holds the machine busy."""
        self._background_job_ui_depth = int(getattr(self, "_background_job_ui_depth", 0)) + 1
        if self._background_job_ui_depth != 1:
            return
        cfg = load_config()
        self._tool_progress_poll_timer.setInterval(int(cfg.background_job_poll_ms))

    def _exit_background_job_ui(self) -> None:
        self._background_job_ui_depth = max(
            0, int(getattr(self, "_background_job_ui_depth", 0)) - 1
        )
        if self._background_job_ui_depth != 0:
            return
        ms = int(getattr(self, "_tool_progress_poll_interval_ms", 200))
        self._tool_progress_poll_timer.setInterval(ms)

    def _finish_tool_progress(
        self,
        message: str | None = None,
        *,
        status_message: str | None = "Ready.",
    ) -> None:
        """Show 100% once, then stop polling and optionally reset the status line."""
        msg, _done, total, active = self._tool_progress_state.snapshot()
        if active:
            stored = getattr(self, "_tool_progress_active_label", "") or ""
            final_msg = message or msg or stored
            self._on_tool_progress(final_msg, total, total)
        self._tool_progress_state.end()
        self._tool_progress_active_label = ""
        self._tool_progress_poll_timer.stop()
        if status_message is not None:
            self.status_label.setText(status_message)

    def render2d_batch_active(self) -> bool:
        """True while Tools → Render 2D batch is running (sorting frozen, etc.)."""
        return self._render2d_batch_active

    @pyqtSlot()
    def _begin_render2d_batch_from_queue(self) -> None:
        """GUI-thread entry for :class:`Render2DBatchHeldJob` (see ``_render2d_queue_payload``)."""
        payload = getattr(self, "_render2d_queue_payload", None)
        cancel_event = getattr(self, "_render2d_queue_cancel_event", None)
        if not payload:
            return
        renders, row_by_oid, src, column_pixmap_mode = payload
        self._begin_render2d_batch_impl(
            renders,
            row_by_oid,
            src,
            column_pixmap_mode=column_pixmap_mode,
            cancel_event=cancel_event,
        )

    def smina_dock_active(self) -> bool:
        """True while Tools → Dock has a ``smina`` subprocess running."""
        dlg = getattr(self, "_smina_dock_dialog", None)
        if dlg is None:
            return False
        try:
            fn = getattr(dlg, "is_smina_running", None)
            return bool(fn()) if callable(fn) else False
        except RuntimeError:
            return False

    def cancel_smina_dock(self) -> bool:
        """Stop the Smina ``QProcess`` if the dialog exists and a run is active."""
        dlg = getattr(self, "_smina_dock_dialog", None)
        if dlg is None:
            return False
        try:
            fn = getattr(dlg, "cancel_smina", None)
            return bool(fn()) if callable(fn) else False
        except RuntimeError:
            return False

    def start_render_worker(
        self,
        oid,
        mol,
        w=None,
        h=None,
        cancel_event=None,
        skip_mol_props=False,
        render_batch_session=0,
    ):
        """Queue 2D structure rendering on the render-only thread pool."""
        if w is None:
            w = structure_depiict_width()
        if h is None:
            h = structure_depiict_height()
        self._render_threadpool.start(
            RenderWorker(
                oid,
                mol,
                self.signals,
                w,
                h,
                cancel_event=cancel_event,
                skip_mol_props=skip_mol_props,
                render_batch_session=render_batch_session,
            )
        )

    def init_ui(self):
        cw = QWidget()
        self.setCentralWidget(cw)
        main_v = QVBoxLayout(cw)
        content_h = QHBoxLayout()
        self._table_model = CompoundTableModel([])
        self.table = CompoundTableView()
        self.table.set_compound_model(self._table_model)
        # Always route the view through the filter proxy: per-row setRowHidden does not scale
        # past ~20k rows, and the filter pipeline already collapses to a single OID set.
        self._filter_proxy_model = FilterProxyModel(self)
        self._filter_proxy_model.setSourceModel(self._table_model)
        self.table.setModel(self._filter_proxy_model)
        self._structure_delegate = StructureDelegate(self.table, self._table_model)
        self._row_highlight_delegate = RowHighlightDelegate(self._table_model, self.table)
        self.table.setItemDelegate(self._row_highlight_delegate)
        self.table.setItemDelegateForColumn(
            CompoundTableModel.STRUCTURE_COL, self._structure_delegate
        )
        self.table.setColumnHidden(0, True)
        self.table.setAlternatingRowColors(True)
        vh = self.table.verticalHeader()
        vh.setDefaultSectionSize(structure_row_default_height())
        vh.setDefaultAlignment(Qt.AlignCenter)
        vh.setContextMenuPolicy(Qt.CustomContextMenu)
        vh.customContextMenuRequested.connect(self.show_row_header_menu)
        # Reorder rows by dragging row numbers (same idea as movable column headers).
        vh.setSectionsMovable(True)
        self.table.horizontalHeader().setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.horizontalHeader().customContextMenuRequested.connect(self.show_header_menu)
        # Allow rearranging columns by dragging the header (keep ID/Structure pinned).
        self.table.horizontalHeader().setSectionsMovable(True)
        self.table.horizontalHeader().setFirstSectionMovable(False)
        self.table.horizontalHeader().sectionMoved.connect(self._on_column_moved)
        self.table.horizontalHeader().sectionClicked.connect(
            self._on_horizontal_header_section_clicked
        )
        self.table.setColumnWidth(
            CompoundTableModel.STRUCTURE_COL,
            structure_depiict_width() + STRUCTURE_COLUMN_HORIZONTAL_PADDING,
        )
        self.table.set_structure_column_minimum_width(structure_column_minimum_width())
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.show_table_menu)
        self.table.doubleClicked.connect(self._on_table_double_clicked)
        sm = self.table.selectionModel()
        if sm is not None:
            sm.selectionChanged.connect(self._on_user_table_selection_changed)
        self._table_stack = QStackedWidget()
        self._table_stack.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._loading_page = QWidget()
        load_lyt = QVBoxLayout(self._loading_page)
        load_lyt.addStretch()
        self._loading_detail = QLabel("")
        self._loading_detail.setAlignment(Qt.AlignCenter)
        self._loading_detail.setWordWrap(True)
        self._loading_detail.setStyleSheet("font-size: 14px; color: palette(mid); padding: 24px;")
        load_lyt.addWidget(self._loading_detail)
        load_lyt.addStretch()
        self._table_stack.addWidget(self._loading_page)
        self._table_stack.addWidget(self.table)
        self._table_stack.setCurrentIndex(1)
        self._search_panel = QFrame(cw)
        self._search_panel.setVisible(False)
        self._search_panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        self._init_table_search_panel(self._search_panel)
        self._table_area = QWidget(cw)
        self._table_area.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        table_area_lyt = QVBoxLayout(self._table_area)
        table_area_lyt.setContentsMargins(0, 0, 0, 0)
        table_area_lyt.setSpacing(0)
        table_area_lyt.addWidget(self._table_stack, 1)

        from .workspace_layout import WorkspaceLayoutManager

        self._workspace_layout = WorkspaceLayoutManager(self._table_area, cw)
        self._workspace_layout.pane_close_requested.connect(self.close_plot_pane)
        self._workspace_layout.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        # Search spans the full workspace width (above table+plots), stopping at the filter panel.
        self._workspace_column = QWidget(cw)
        self._workspace_column.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        workspace_col_lyt = QVBoxLayout(self._workspace_column)
        workspace_col_lyt.setContentsMargins(0, 0, 0, 0)
        workspace_col_lyt.setSpacing(4)
        workspace_col_lyt.addWidget(self._search_panel)
        workspace_col_lyt.addWidget(self._workspace_layout, 1)
        self._content_h = content_h
        content_h.addWidget(self._workspace_column, 1)
        # Wide enough for filter cards and footer actions (avoids clipping).
        _filter_panel_w = 320
        self.f_panel = QFrame()
        self.f_panel.setObjectName("FilterPanel")
        self.f_panel.setFixedWidth(_filter_panel_w)
        self.f_panel.setVisible(False)
        sb_lyt = QVBoxLayout(self.f_panel)
        # Left/right inset only: top/bottom 0 so cards and footer align with the table edges.
        sb_lyt.setContentsMargins(5, 0, 5, 0)
        sb_lyt.setSpacing(5)

        # When search is open above the table, pad so the first card lines up with the table top.
        self._filter_table_top_pad = QWidget()
        self._filter_table_top_pad.setFixedHeight(0)
        self._filter_table_top_pad.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        sb_lyt.addWidget(self._filter_table_top_pad)

        self._filter_cards_host = FilterCardsHost(on_reorder=self.reorder_filter_card)
        # Ignored horizontal policy: scroll viewport sets width (prevents cards wider than panel).
        self._filter_cards_host.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Minimum)
        self.f_container = QVBoxLayout(self._filter_cards_host)
        self.f_container.setContentsMargins(0, 0, 0, 0)
        self.f_container.setSpacing(6)
        self.f_container.setAlignment(Qt.AlignTop)
        self._filter_scroll = _FilterCardsScrollArea(self._filter_cards_host)
        self._filter_scroll.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        sb_lyt.addWidget(self._filter_scroll, 1)
        QTimer.singleShot(0, self._sync_filter_panel_scroll_content)

        panel_btns = QHBoxLayout()
        panel_btns.setSpacing(_FILTER_PANEL_BTN_SPACING)
        panel_btns.setContentsMargins(0, 0, 0, 0)
        btn_add = QPushButton("+")
        btn_add.setToolTip("Add a filter…")
        btn_add.setFixedSize(_FILTER_PANEL_BTN_H, _FILTER_PANEL_BTN_H)
        btn_add.clicked.connect(self.open_add_filter_dialog)
        btn_close_panel = QPushButton("Close")
        btn_close_panel.setToolTip(
            "Hide the filter panel. Active filters keep affecting the table."
        )
        btn_close_panel.clicked.connect(self.close_filter_panel_keep_filters)
        btn_enable_all = QPushButton("Enable All")
        btn_enable_all.setToolTip("Turn on every filter card in this panel.")
        btn_enable_all.clicked.connect(self.enable_all_filters_keep_panel)
        btn_disable_all = QPushButton("Disable All")
        btn_disable_all.setToolTip(
            "Turn off every filter while keeping this panel open. Use On on each card to enable again."
        )
        btn_disable_all.clicked.connect(self.disable_all_filters_keep_panel)
        for btn in (btn_close_panel, btn_enable_all, btn_disable_all):
            _configure_filter_panel_button(btn)
        panel_btns.addStretch(1)
        panel_btns.addWidget(btn_add, 0, Qt.AlignBottom)
        panel_btns.addWidget(btn_close_panel, 0, Qt.AlignBottom)
        panel_btns.addWidget(btn_enable_all, 0, Qt.AlignBottom)
        panel_btns.addWidget(btn_disable_all, 0, Qt.AlignBottom)
        panel_btns.addStretch(1)
        sb_lyt.addLayout(panel_btns)
        content_h.addWidget(self.f_panel)
        main_v.addLayout(content_h, 1)
        status_row = QHBoxLayout()
        status_row.setContentsMargins(0, 0, 0, 0)
        status_row.setSpacing(8)
        self.status_label = QLabel("Ready")
        self.status_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self._memory_status_label = QLabel("")
        self._memory_status_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._memory_status_label.setToolTip(
            "MolManager process resident memory (working set). "
            "Background render worker processes are not included."
        )
        status_row.addWidget(self.status_label, 1)
        status_row.addWidget(self._memory_status_label, 0)
        self._status_host = QWidget()
        self._status_host.setLayout(status_row)
        main_v.addWidget(self._status_host)
        apply_bar = getattr(self, "_apply_status_bar_visible", None)
        if callable(apply_bar):
            from ..theme import load_status_bar_visible

            apply_bar(load_status_bar_visible(), persist=False)

    def init_menubar(self):
        mb = self.menuBar()
        file_menu = mb.addMenu("&File")
        file_menu.addAction(
            self._bind_hotkey(
                "file.open",
                QAction("&Open File...", self, triggered=self.open_file_dialog),
            )
        )
        file_menu.addAction(
            self._bind_hotkey(
                "file.export_all",
                QAction("&Save File...", self, triggered=lambda: self.run_export(False)),
            )
        )
        file_menu.addAction(
            QAction("Save Selected...", self, triggered=lambda: self.run_export(True))
        )
        file_menu.addAction(
            QAction("Import &Data...", self, triggered=self.open_import_file_dialog)
        )
        file_menu.addSeparator()
        file_menu.addAction(QAction("Open Session…", self, triggered=self.open_session_file))
        file_menu.addAction(QAction("Save Session…", self, triggered=self.save_session_as))
        file_menu.addAction(QAction("New Session", self, triggered=self.new_session))
        file_menu.addAction(QAction("Duplicate Session", self, triggered=self.duplicate_session))
        edit = mb.addMenu("&Edit")
        act_undo = self._bind_hotkey("edit.undo", self._undo_stack.createUndoAction(self))
        act_redo = self._bind_hotkey("edit.redo", self._undo_stack.createRedoAction(self))
        edit.addAction(act_undo)
        edit.addAction(act_redo)
        self.addAction(act_undo)
        self.addAction(act_redo)
        edit.addSeparator()
        edit.addAction(
            self._bind_hotkey("edit.copy", QAction("&Copy", self, triggered=self.edit_copy))
        )
        edit.addAction(
            self._bind_hotkey("edit.paste", QAction("&Paste", self, triggered=self.edit_paste))
        )
        edit.addAction(
            self._bind_hotkey(
                "edit.delete_selection",
                QAction("Delete &Selection", self, triggered=self.edit_delete_selection),
            )
        )
        edit.addSeparator()
        act_invert_sel = self._bind_hotkey(
            "edit.invert_selection",
            QAction("Invert Selection", self, triggered=self.invert_table_selection),
        )
        act_invert_sel.setToolTip(
            "Select all rows that are not currently selected (entire table, including rows hidden by filters)."
        )
        edit.addAction(act_invert_sel)
        act_clear_sel = self._bind_hotkey(
            "edit.clear_selection",
            QAction("Clear Selection", self, triggered=self.clear_table_selection),
        )
        act_clear_sel.setToolTip("Clear the current cell/row selection (Ctrl+Shift+D).")
        edit.addAction(act_clear_sel)
        edit.addAction(
            self._bind_hotkey(
                "edit.clear_table",
                QAction("Clear Table…", self, triggered=self.clear_table_after_confirm),
            )
        )
        tools = mb.addMenu("&Tools")
        tools.setToolTipsVisible(True)

        act_calc_desc = self._bind_hotkey(
            "tools.calculate_descriptors",
            QAction("Calculate Descriptors…", self, triggered=self.open_calc),
        )
        act_calc_desc.setToolTip(
            "Compute RDKit molecular descriptors and append them as columns (selected or visible rows)."
        )
        tools.addAction(act_calc_desc)
        tools.addSeparator()

        prepare_menu = tools.addMenu("&Prepare Structures")
        prepare_menu.setToolTipsVisible(True)
        for title, slot, tip, hk_id in (
            (
                "Fast Prepare…",
                self.run_fast_prepare,
                "Disconnect largest fragment, optionally neutralize, and redraw 2D images in one background job.",
                None,
            ),
            (
                None,
                None,
                None,
                None,
            ),
            (
                "Disconnect Largest Fragments…",
                self.run_disconnect_fragments,
                "Split disconnected structure fragments into separate rows, keeping the heaviest fragment.",
                None,
            ),
            (
                "Add Explicit Hydrogens…",
                self.run_add_explicit_hydrogens,
                "Expand implicit hydrogens to explicit H atoms in the target column (RDKit AddHs).",
                None,
            ),
            (
                "Remove Explicit Hydrogens…",
                self.run_remove_explicit_hydrogens,
                "Remove explicit H atoms from structures in the target column (RDKit RemoveHs).",
                None,
            ),
            (
                "Render 2D…",
                self.run_render_2d_structures,
                "Regenerate 2D structure drawings for selected rows as a background batch (see Processes).",
                "tools.render_2d",
            ),
        ):
            if title is None:
                prepare_menu.addSeparator()
                continue
            act = QAction(title, self, triggered=slot)
            if hk_id:
                self._bind_hotkey(hk_id, act)
            act.setToolTip(tip)
            prepare_menu.addAction(act)

        protonate_menu = prepare_menu.addMenu("Protonate Structures")
        protonate_menu.setToolTipsVisible(True)
        for title, slot, tip in (
            (
                "Protonate…",
                self.run_protonate,
                "Generate the dominant protomer (Uni-pKa) into a column and optionally render it like Structure.",
            ),
            (
                "Generate Protomers…",
                self.open_protomer_generator,
                "Enumerate protomers or tautomers from structures and add results to the table.",
            ),
            (
                "Neutralize…",
                self.run_neutralize,
                "Adjust protonation so the net formal charge is zero (RDKit Uncharger); updates the target column.",
            ),
        ):
            act = QAction(title, self, triggered=slot)
            act.setToolTip(tip)
            protonate_menu.addAction(act)

        self._act_custom_calc = self._bind_hotkey(
            "tools.calculator",
            QAction("Calculator…", self, triggered=self.open_calculator),
        )
        self._act_custom_calc.setToolTip(
            "Add a numeric column from a math expression using existing column names (e.g. sqrt, log10, exp)."
        )
        if load_config().disable_custom_calc:
            self._act_custom_calc.setEnabled(False)
            self._act_custom_calc.setToolTip(
                "Calculator disabled by MOLMANAGER_DISABLE_CUSTOM_CALC."
            )

        conformations_menu = tools.addMenu("&Conformations")
        conformations_menu.setToolTipsVisible(True)
        gen_conf_menu = conformations_menu.addMenu("Generate Conformations")
        gen_conf_menu.setToolTipsVisible(True)
        act_gen_conf = QAction(
            "Stochastic…",
            self,
            triggered=self.open_generate_conformations,
        )
        act_gen_conf.setToolTip(
            "Build ensembles with RDKit ETKDG (stochastic distance geometry), then minimize and prune."
        )
        gen_conf_menu.addAction(act_gen_conf)
        act_sys_conf = QAction(
            "Systematic…",
            self,
            triggered=self.open_systematic_conformations,
        )
        act_sys_conf.setToolTip(
            "Build ensembles with Open Babel Confab (systematic torsion search)."
        )
        gen_conf_menu.addAction(act_sys_conf)

        superpose_menu = conformations_menu.addMenu("&Superpose")
        superpose_menu.setToolTipsVisible(True)
        act_sp_conf = QAction("Conformers…", self, triggered=self.open_superpose_conformers)
        act_sp_conf.setToolTip(
            "Align conformer ensembles within each row and open a 3D results window with energies and RMSD."
        )
        superpose_menu.addAction(act_sp_conf)
        act_sp_struct = QAction("Structures…", self, triggered=self.open_superpose_structures)
        act_sp_struct.setToolTip(
            "Align selected table structures onto a reference and open a 3D results window with energies."
        )
        superpose_menu.addAction(act_sp_struct)

        fp_menu = tools.addMenu("&Fingerprints")
        fp_menu.setToolTipsVisible(True)

        act_fp_sim = self._bind_hotkey(
            "tools.fingerprint_similarity",
            QAction("Fingerprint Similarity...", self, triggered=self.open_fp_similarity),
        )
        act_fp_sim.setToolTip("Search the table by 2D fingerprint similarity to a query structure.")
        fp_menu.addAction(act_fp_sim)

        act_diverse = QAction("Diverse Subset…", self, triggered=self.open_diverse_subset)
        act_diverse.setToolTip(
            "Pick a maximally diverse subset of compounds (MaxMin on fingerprint Tanimoto distance)."
        )
        fp_menu.addAction(act_diverse)

        act_cluster = self._bind_hotkey(
            "data.cluster",
            QAction("Cluster…", self, triggered=self.open_cluster_dialog),
        )
        act_cluster.setToolTip(
            "Cluster compounds by fingerprint (K-Means, Butina, sphere exclusion, etc.)."
        )
        fp_menu.addAction(act_cluster)

        predict_menu = tools.addMenu("&Predict")
        predict_menu.setToolTipsVisible(True)
        for title, slot, tip in (
            (
                "pKa…",
                self.open_pka_predictor,
                "Estimate ionization / pKa-related properties when the predictor is available.",
            ),
            (
                "Permeability…",
                self.open_permeability_predictor,
                "Predict Caco-2 and MDCK permeability / efflux endpoints (optional Chemprop install).",
            ),
            (
                "SOM…",
                self.open_som_predictor,
                "Predict sites of metabolism with FAME3R and draw a highlighted atom map.",
            ),
        ):
            act = QAction(title, self, triggered=slot)
            act.setToolTip(tip)
            predict_menu.addAction(act)

        dock_menu = tools.addMenu("&Dock")
        dock_menu.setToolTipsVisible(True)
        prepare_menu = dock_menu.addMenu("Prepare")
        prepare_menu.setToolTipsVisible(True)
        act_dock_prepare = QAction("PDBQT…", self, triggered=self.open_dock_prepare)
        act_dock_prepare.setToolTip(
            "Generate receptor and/or ligand PDBQT (receptor PDB; ligand SDF, PDB, SMILES, or table rows)."
        )
        prepare_menu.addAction(act_dock_prepare)
        act_dock_prepare_pdb = QAction("Receptor PDB…", self, triggered=self.open_dock_prepare_pdb)
        act_dock_prepare_pdb.setToolTip(
            "Clean a receptor PDB with PDBFixer (remove ligands/waters, add atoms and hydrogens) "
            "before PDBQT conversion or docking."
        )
        prepare_menu.addAction(act_dock_prepare_pdb)
        dock_menu.addSeparator()
        act_dock = QAction("EasyDock…", self, triggered=self.open_easydock)
        act_dock.setToolTip(
            "Dock table ligands with EasyDock (Smina or Vina): scores and poses written to the table."
        )
        dock_menu.addAction(act_dock)
        act_dock_smina = QAction("Smina…", self, triggered=self.open_smina_dock)
        act_dock_smina.setToolTip(
            "Run Smina as a file-based CLI on PDBQT inputs (log only; no table writeback)."
        )
        dock_menu.addAction(act_dock_smina)
        dock_menu.addSeparator()
        act_dock_viewer = QAction("Viewer", self, triggered=self.open_dock_results_viewer)
        act_dock_viewer.setToolTip(
            "Show the last docking results window, even after it has been closed."
        )
        act_dock_viewer.setEnabled(False)
        self._act_dock_viewer = act_dock_viewer
        dock_menu.addAction(act_dock_viewer)

        decomp_menu = tools.addMenu("&R-Group Decomposition")
        decomp_menu.setToolTipsVisible(True)
        for title, slot, tip in (
            (
                "Core-Based Decomposition…",
                self.open_core_based_decomposition,
                "Decompose structures against a labeled core scaffold (substituent columns).",
            ),
            (
                "BRICS Decomposition…",
                self.open_brics_decomposition,
                "Split structures into BRICS retrosynthetic fragments (new SMILES columns).",
            ),
            (
                "BRICS Recomposition…",
                self.open_brics_recomposition,
                "Combine BRICS fragment columns into new product structures (new rows).",
            ),
            (
                "RECAP Decomposition…",
                self.open_recap_decomposition,
                "Split structures into RECAP retrosynthetic fragments (new SMILES columns).",
            ),
            (
                "RECAP Recomposition…",
                self.open_recap_recomposition,
                "Combine RECAP fragment columns into new product structures (new rows).",
            ),
        ):
            act = QAction(title, self, triggered=slot)
            act.setToolTip(tip)
            decomp_menu.addAction(act)

        act_reaction_enum = QAction(
            "Reaction Based Enumeration…",
            self,
            triggered=self.open_reaction_enumeration,
        )
        act_reaction_enum.setToolTip(
            "Run a named reaction (Suzuki, Buchwald, amide coupling, etc.) across two reactant "
            "pools from structure files or pasted SMILES, then append products to the table "
            "and/or an SDF file."
        )
        tools.addAction(act_reaction_enum)

        tools.addSeparator()
        tools.addAction(self._act_custom_calc)
        random_menu = tools.addMenu("&Random")
        random_menu.setToolTipsVisible(True)
        act_random_number = QAction("Number…", self, triggered=self.open_random_number_dialog)
        act_random_number.setToolTip(
            "Fill a column with random numbers (uniform, integer, or normal) for all or selected rows."
        )
        random_menu.addAction(act_random_number)
        act_random_molecule = QAction("Molecule…", self, triggered=self.open_random_molecule_dialog)
        act_random_molecule.setToolTip(
            "Fetch a specified number of random small molecules from ChEMBL and add them to the table."
        )
        random_menu.addAction(act_random_molecule)

        tools.addSeparator()
        filter_menu = tools.addMenu("&Filter")
        filter_menu.setToolTipsVisible(True)
        self._act_toggle_filter_panel = self._bind_hotkey(
            "tools.toggle_filter_panel",
            QAction("Toggle Panel", self, triggered=self.toggle_filter_panel),
        )
        self._act_toggle_filter_panel.setToolTip("Show or hide the filter panel (Ctrl+Shift+L).")
        self.addAction(self._act_toggle_filter_panel)
        filter_menu.addAction(self._act_toggle_filter_panel)
        filter_menu.addSeparator()
        act_sub = QAction(
            "Add Substructure", self, triggered=lambda: self.add_substructure_filter_card()
        )
        act_sub.setToolTip(
            "Add a filter card that matches a SMARTS substructure in the Structure column."
        )
        filter_menu.addAction(act_sub)
        act_slider = QAction("Add Slider", self, triggered=lambda: self.add_filter_card())
        act_slider.setToolTip("Add a numeric range slider filter for a column.")
        filter_menu.addAction(act_slider)
        act_txt = QAction("Add Text", self, triggered=lambda: self.add_text_filter_card())
        act_txt.setToolTip("Add a text contains / equals filter for a column.")
        filter_menu.addAction(act_txt)
        act_cat = QAction("Add Category", self, triggered=lambda: self.add_category_filter_card())
        act_cat.setToolTip("Add a categorical multi-select filter for a column.")
        filter_menu.addAction(act_cat)
        filter_menu.addSeparator()
        act_enable_all_filters = QAction(
            "Enable All Filters", self, triggered=self.enable_all_filters_keep_panel
        )
        act_enable_all_filters.setToolTip("Turn on every filter card in the panel.")
        filter_menu.addAction(act_enable_all_filters)
        act_disable_all_filters = QAction(
            "Disable All Filters", self, triggered=self.disable_all_filters_keep_panel
        )
        act_disable_all_filters.setToolTip(
            "Turn off every filter card. Cards stay in the panel; use On on each card to enable again."
        )
        filter_menu.addAction(act_disable_all_filters)
        act_delete_all_filters = QAction(
            "Delete All Filters", self, triggered=self.delete_all_filters_from_panel
        )
        act_delete_all_filters.setToolTip("Remove every filter card from the panel.")
        filter_menu.addAction(act_delete_all_filters)
        act_search = self._bind_hotkey(
            "tools.search",
            QAction("&Search…", self, triggered=self.toggle_table_search_panel),
        )
        act_search.setToolTip("Open or focus the in-table search panel (Ctrl+F).")
        tools.addAction(act_search)

        tools.addSeparator()
        act_sketch = self._bind_hotkey(
            "tools.sketcher",
            QAction("&Sketcher…", self, triggered=self.open_sketcher),
        )
        act_sketch.setToolTip("Open the structure sketcher to draw or edit molecules.")
        tools.addAction(act_sketch)

        protein_menu = mb.addMenu("&Protein")
        protein_menu.setToolTipsVisible(True)
        act_protein_viewer = QAction("&Viewer", self, triggered=self.open_protein_viewer)
        act_protein_viewer.setToolTip(
            "Load a PDB, mmCIF, or other crystallographic file and inspect chains in 3D."
        )
        protein_menu.addAction(act_protein_viewer)

        data_menu = mb.addMenu("&Data")
        data_menu.addAction(
            self._bind_hotkey(
                "data.analyze_table",
                QAction("Analyze Table…", self, triggered=self.open_data_analysis),
            )
        )
        act_split_col = self._bind_hotkey(
            "data.split_column",
            QAction("Split Column…", self, triggered=self.open_split_column_dialog),
        )
        act_split_col.setToolTip(
            "Split a delimited column (comma, tab, space, semicolon, …) into new columns."
        )
        data_menu.addAction(act_split_col)
        data_menu.addSeparator()
        act_qsar = QAction("QSAR…", self, triggered=self.open_qsar_dialog)
        act_qsar.setToolTip(
            "Train regression or classification models on activity vs descriptors or fingerprints."
        )
        data_menu.addAction(act_qsar)
        act_mpo = QAction("MPO Scoring…", self, triggered=self.open_mpo_scoring_dialog)
        act_mpo.setToolTip(
            "Score rows with linear, Gaussian, or step desirability functions and combine into an overall MPO score."
        )
        data_menu.addAction(act_mpo)
        data_menu.addSeparator()
        data_menu.addAction(
            QAction("Principal Component Analysis…", self, triggered=self.open_pca_dialog)
        )
        data_menu.addAction(QAction("t-SNE Visualization…", self, triggered=self.open_tsne_dialog))
        data_menu.addAction(QAction("UMAP Visualization…", self, triggered=self.open_umap_dialog))
        data_menu.addAction(
            QAction(
                "Self-Organizing Map…",
                self,
                triggered=self.open_som_dialog,
            )
        )
        data_menu.addSeparator()
        data_menu.addAction(QAction("BOILED-Egg plot…", self, triggered=self.open_boiled_egg_plot))
        data_menu.addAction(
            QAction("Golden Triangle plot…", self, triggered=self.open_golden_triangle_plot)
        )
        act_sali = QAction("SALI…", self, triggered=self.open_sali_dialog)
        act_sali.setToolTip(
            "Plot fingerprint similarity vs |Δactivity| colored by SALI "
            "(|Δ| / (1 − similarity)). Click a point to select the pair."
        )
        data_menu.addAction(act_sali)
        act_mmp = QAction("&MMP…", self, triggered=self.open_mmp_dialog)
        act_mmp.setToolTip(
            "Find matched molecular pairs (RDKit MMPA) and open the transform ledger "
            "ranked by support and activity effect."
        )
        data_menu.addAction(act_mmp)
        data_menu.addSeparator()
        act_plot = self._bind_hotkey(
            "data.plotter",
            QAction("&Plotter…", self, triggered=self.open_plot),
        )
        act_plot.setToolTip("Open the plotter or show the docked plot panel.")
        data_menu.addAction(act_plot)
        data_menu.addSeparator()
        act_browser = self._bind_hotkey(
            "file.browser",
            QAction("&Browser…", self, triggered=self.open_selection_browser),
        )
        act_browser.setToolTip("Open the selection browser to review and act on selected rows.")
        data_menu.addAction(act_browser)

        ext_menu = mb.addMenu("E&xternal")
        ext_menu.addAction(
            QAction("Connect to SQL database…", self, triggered=self.open_external_db)
        )
        ext_menu.addSeparator()
        ext_menu.addAction(QAction("Query PubChem…", self, triggered=self.open_pubchem))
        ext_menu.addAction(QAction("Query ChEMBL…", self, triggered=self.open_chembl))
        ext_menu.addAction(QAction("Query Patents…", self, triggered=self.open_patent_query))

        self._init_settings_menu(mb)

        help_menu = mb.addMenu("&Help")
        self._act_user_guide = self._bind_hotkey(
            "help.user_guides",
            QAction("&Help", self),
        )
        self._act_user_guide.setToolTip("Open MolManager help (F1).")
        self._act_user_guide.triggered.connect(lambda: open_user_guide_dialog(self))
        self.addAction(self._act_user_guide)
        help_menu.addAction(self._act_user_guide)

        self._act_user_guide_page = QAction("&User Guide", self)
        self._act_user_guide_page.setToolTip("Open the MolManager user guide (same as Help).")
        self._act_user_guide_page.triggered.connect(lambda: open_user_guide_dialog(self))
        help_menu.addAction(self._act_user_guide_page)

        help_menu.addSeparator()

        self._act_citations = self._bind_hotkey(
            "help.citations",
            QAction("&Citations…", self),
        )
        self._act_citations.setToolTip("Papers and licenses for tools used in MolManager.")
        self._act_citations.triggered.connect(lambda: open_citations_dialog(self))
        self.addAction(self._act_citations)
        help_menu.addAction(self._act_citations)

        # Native Windows menu bars can swallow clicks meant for the corner widget; use in-window bar.
        if sys.platform == "win32":
            mb.setNativeMenuBar(False)

        corner = QWidget(mb)
        corner_ly = QHBoxLayout(corner)
        corner_ly.setContentsMargins(0, 0, 4, 0)

        btn_layout = QToolButton(corner)
        btn_layout.setText("Layout")
        btn_layout.setToolTip("Choose how the table and plot panes are arranged.")
        btn_layout.setToolButtonStyle(Qt.ToolButtonTextOnly)
        btn_layout.setAutoRaise(True)
        btn_layout.setFocusPolicy(Qt.NoFocus)
        btn_layout.setFont(mb.font())
        btn_layout.clicked.connect(self.open_workspace_layout_picker)
        self._btn_workspace_layout = btn_layout
        corner_ly.addWidget(btn_layout)

        btn_proc = QToolButton(corner)
        btn_proc.setText("Processes")
        btn_proc.setToolTip(
            "View queued background jobs (conformers, descriptors, import, export, …)."
        )
        btn_proc.setToolButtonStyle(Qt.ToolButtonTextOnly)
        btn_proc.setAutoRaise(True)
        btn_proc.setFocusPolicy(Qt.NoFocus)
        btn_proc.setFont(mb.font())
        btn_proc.clicked.connect(self.open_processes_dialog)
        self._btn_processes = btn_proc
        corner_ly.addWidget(btn_proc)
        mb.setCornerWidget(corner, Qt.TopRightCorner)
        self._sync_main_toolbar_for_table_ready()

    def apply_dock_results_chrome(self) -> None:
        """Keep File → Save File / Save Selected; drop the rest of the toolbar."""
        self._dock_results_mode = True
        mb = self.menuBar()
        mb.clear()
        file_menu = mb.addMenu("&File")
        export_all = (getattr(self, "_hotkey_actions", {}) or {}).get("file.export_all")
        if export_all is None:
            export_all = self._bind_hotkey(
                "file.export_all",
                QAction("&Save File...", self, triggered=lambda: self.run_export(False)),
            )
        else:
            export_all.setText("&Save File...")
        file_menu.addAction(export_all)
        file_menu.addAction(
            QAction("Save Selected...", self, triggered=lambda: self.run_export(True))
        )
        self._add_dock_view_menu(mb)
        keep = {"file.export_all"}
        for action_id, action in list(getattr(self, "_hotkey_actions", {}).items()):
            if action_id in keep or action is None:
                continue
            try:
                action.setShortcut(QKeySequence())
                action.setEnabled(False)
            except RuntimeError:
                pass
        for btn in (
            getattr(self, "_btn_workspace_layout", None),
            getattr(self, "_btn_processes", None),
        ):
            if btn is not None:
                btn.hide()
        corner = mb.cornerWidget(Qt.TopRightCorner)
        if corner is not None:
            corner.hide()
        if sys.platform == "win32":
            mb.setNativeMenuBar(False)

    def _add_dock_view_menu(self, mb) -> None:
        """View → Render submenu for receptor / ligand / pocket drawing styles."""
        from ..dock_complex_viewer import (
            DEFAULT_RENDER_STYLES,
            RENDER_COMPONENT_LABELS,
            RENDER_STYLE_CHOICES,
        )

        view_menu = mb.addMenu("&View")
        render_menu = view_menu.addMenu("&Render")
        render_menu.setToolTipsVisible(True)
        render_menu.setToolTip("Choose how each component of the 3D complex is drawn.")
        self._dock_render_groups = {}
        for component, choices in RENDER_STYLE_CHOICES.items():
            sub = render_menu.addMenu(RENDER_COMPONENT_LABELS[component])
            group = QActionGroup(self)
            group.setExclusive(True)
            default = DEFAULT_RENDER_STYLES[component]
            for style_id, label in choices:
                act = QAction(label, self)
                act.setCheckable(True)
                act.setChecked(style_id == default)
                act.setData((component, style_id))
                group.addAction(act)
                sub.addAction(act)
            group.triggered.connect(self._on_dock_render_style_triggered)
            self._dock_render_groups[component] = group
        view_menu.addSeparator()
        pocket_act = QAction("Pocket View", self)
        pocket_act.setToolTip(
            "Show nearby amino acids as ball-and-stick with residue labels, and zoom to the ligand."
        )
        pocket_act.triggered.connect(self._on_dock_pocket_view)
        view_menu.addAction(pocket_act)

    def _sync_dock_render_menu_checks(self, styles: dict) -> None:
        groups = getattr(self, "_dock_render_groups", None) or {}
        for component, group in groups.items():
            want = (styles or {}).get(component)
            group.blockSignals(True)
            try:
                for act in group.actions():
                    data = act.data()
                    act.setChecked(bool(data) and data[1] == want)
            finally:
                group.blockSignals(False)

    def _on_dock_pocket_view(self) -> None:
        viewer = getattr(self, "_dock_complex_viewer", None)
        apply = getattr(viewer, "apply_pocket_view", None) if viewer is not None else None
        if callable(apply):
            apply()
        if viewer is not None:
            self._sync_dock_render_menu_checks(viewer.render_styles())

    def _on_dock_render_style_triggered(self, action: QAction) -> None:
        data = action.data() if action is not None else None
        if not data or len(data) != 2:
            return
        component, style = data
        viewer = getattr(self, "_dock_complex_viewer", None)
        setter = getattr(viewer, "set_render_style", None) if viewer is not None else None
        if callable(setter):
            setter(str(component), str(style))

    def _set_ingest_loading(self, loading: bool) -> None:
        """Track file/import ingest and gray out the main toolbar until the table is ready."""
        self._ingest_loading = bool(loading)
        self._sync_main_toolbar_for_table_ready()

    def _sync_main_toolbar_for_table_ready(self) -> None:
        """Disable File/Edit/Tools menus and Layout while ``_ingest_loading``; keep Processes usable."""
        if getattr(self, "_dock_results_mode", False):
            return
        enabled = not bool(getattr(self, "_ingest_loading", False))
        mb = self.menuBar()
        for action in mb.actions():
            menu = action.menu()
            if menu is not None:
                menu.setEnabled(enabled)
            else:
                action.setEnabled(enabled)
        calc = getattr(self, "_act_custom_calc", None)
        calc_blocked = bool(load_config().disable_custom_calc)
        for action in getattr(self, "_hotkey_actions", {}).values():
            if action is None:
                continue
            if action is calc and calc_blocked:
                action.setEnabled(False)
            else:
                action.setEnabled(enabled)
        layout_btn = getattr(self, "_btn_workspace_layout", None)
        if layout_btn is not None:
            layout_btn.setEnabled(enabled)
        # Processes stays enabled so the user can cancel a long open/import.

    def open_protein_viewer(self) -> None:
        """Open the Protein Viewer window (3Dmol.js + chain Manager)."""
        from ..protein_viewer import ProteinViewerDialog
        from ..singleton_modeless_dialog import reuse_or_show_modeless_singleton

        def _on_destroyed() -> None:
            self._protein_viewer_dialog = None

        reuse_or_show_modeless_singleton(
            self,
            "_protein_viewer_dialog",
            lambda: ProteinViewerDialog(self),
            _on_destroyed,
        )

    def open_workspace_layout_picker(self) -> None:
        """Show the graphic layout picker and apply the chosen preset."""
        from ..dialogs.workspace_layout_picker import WorkspaceLayoutPickerDialog

        mgr = getattr(self, "_workspace_layout", None)
        current = mgr.layout_id if mgr is not None else None
        dlg = WorkspaceLayoutPickerDialog(self, current_layout_id=current)
        dlg.layout_chosen.connect(self.apply_workspace_layout)
        dlg.exec_()

    def apply_workspace_layout(self, layout_id: str) -> None:
        """Apply a workspace layout preset and undock plots that no longer fit."""
        mgr = getattr(self, "_workspace_layout", None)
        if mgr is None:
            return
        extras = mgr.apply_layout(layout_id, preserve_plots=True)
        for w in extras:
            self._float_released_plot_widget(w)
        mark = getattr(self, "_mark_session_dirty", None)
        if callable(mark):
            mark()
        self.status_label.setText(f"Layout: {layout_id.replace('_', ' ')}.")

    def _on_processes_dialog_destroyed(self) -> None:
        self._processes_dialog = None

    def open_processes_dialog(self) -> None:
        from ..processes_dialog import ProcessesDialog

        dlg = getattr(self, "_processes_dialog", None)
        if dlg is not None:
            try:
                dlg.show()
                dlg.raise_()
                dlg.activateWindow()
                dlg._reload()
                return
            except RuntimeError:
                self._processes_dialog = None
        w = ProcessesDialog(self)
        self._processes_dialog = w
        w.destroyed.connect(self._on_processes_dialog_destroyed)
        w.show()

    def _wire_table_plot_refresh(self) -> None:
        """Replot open Plotly views when table cell data changes."""
        model = getattr(self, "_table_model", None)
        if model is None:
            return

        def _on_data_changed(top_left, bottom_right, roles=()) -> None:
            # Structure pixmap paints while scrolling emit DecorationRole (etc.) only —
            # those must not replot, or plot↔table selection sync fights the scrollbar.
            structure_col = CompoundTableModel.STRUCTURE_COL
            if (
                top_left.isValid()
                and bottom_right.isValid()
                and top_left.column() == structure_col
                and bottom_right.column() == structure_col
            ):
                paint_roles = {
                    Qt.DecorationRole,
                    Qt.SizeHintRole,
                    Qt.DisplayRole,
                    Qt.ToolTipRole,
                }
                if not roles or set(roles) <= paint_roles:
                    return
            self._schedule_active_plots_replot()

        model.dataChanged.connect(_on_data_changed)

    def _wire_sqlite_store_dirty_tracking(self) -> None:
        model = getattr(self, "_table_model", None)
        if model is None:
            return
        mark = self._mark_sqlite_store_dirty
        model.dataChanged.connect(lambda *_args: mark())
        model.rowsInserted.connect(lambda *_args: mark())
        model.rowsRemoved.connect(lambda *_args: mark())
        model.columnsInserted.connect(lambda *_args: mark())
        model.columnsRemoved.connect(lambda *_args: mark())
        model.modelReset.connect(lambda *_args: mark())
        model.layoutChanged.connect(lambda *_args: mark())

    def _mark_sqlite_store_dirty(self) -> None:
        if getattr(self, "_ingest_sqlite_paused_dirty", False):
            return
        if self._sqlite_store is None:
            self._mark_session_dirty()
            return
        self._sqlite_store_dirty = True
        if self._sqlite_rebuild_in_progress:
            self._sqlite_rebuild_stale = True
        self._mark_session_dirty()

    def _mark_session_dirty(self) -> None:
        """Record that the workspace differs from the last save or successful open."""
        if getattr(self, "_session_mutation_paused", False):
            return
        if getattr(self, "_ingest_sqlite_paused_dirty", False):
            return
        self._session_dirty = True

    def _clear_session_dirty(self) -> None:
        self._session_dirty = False

    def _session_has_unsaved_changes(self) -> bool:
        return bool(getattr(self, "_session_dirty", False))

    def _finish_session_clean_if_pending(self) -> None:
        """Clear dirty after a replace-open finishes revealing the table."""
        self._session_mutation_paused = False
        if getattr(self, "_pending_session_clean_on_ready", False):
            self._clear_session_dirty()
            self._pending_session_clean_on_ready = False

    def _ensure_sqlite_store_current(self) -> bool:
        """Return True when the SQLite mirror is ready for filter/search pushdown."""
        if self._sqlite_store is None:
            return False
        if not self._sqlite_store_dirty:
            return True
        if self._sqlite_rebuild_in_progress:
            return False
        schedule = getattr(self, "_schedule_sqlite_rebuild", None)
        if callable(schedule):
            schedule()
        return False

    def closeEvent(self, event: QCloseEvent) -> None:
        if getattr(self, "_dock_results_mode", False):
            if not getattr(self, "_dock_results_force_close", False):
                self.hide()
                event.ignore()
                return
            super().closeEvent(event)
            return
        # Skip modal prompt under pytest / headless teardown, or when nothing changed.
        if not getattr(self, "_suppress_exit_session_prompt", False):
            if self._session_has_unsaved_changes():
                from PyQt5.QtWidgets import QMessageBox

                reply = QMessageBox.question(
                    self,
                    "Save Session",
                    "Save the current session before exiting?",
                    QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
                    QMessageBox.Save,
                )
                if reply == QMessageBox.Cancel:
                    event.ignore()
                    return
                if reply == QMessageBox.Save:
                    save = getattr(self, "save_session_as", None)
                    if callable(save) and not save():
                        event.ignore()
                        return
        self._prepare_application_shutdown()
        super().closeEvent(event)

    def _prepare_application_shutdown(self) -> None:
        """Stop timers, cancel background work, close modeless dialogs, drain thread pools."""
        t = getattr(self, "_apply_filters_timer", None)
        if t is not None:
            t.stop()
        mem_t = getattr(self, "_memory_status_timer", None)
        if mem_t is not None:
            mem_t.stop()

        self.background_activity.prepare_for_quit()

        pq = getattr(self, "process_queue", None)
        if pq is not None:
            # Must be first: kill process pools and cancel running/queued jobs so
            # long-running Uni-pKa/descriptor work does not keep the interpreter alive
            # after the window closes.
            try:
                pq.shutdown_for_exit()
            except Exception:
                log_swallowed_exception(
                    logger, "process_queue.shutdown_for_exit failed during quit"
                )

        for dlg in list(getattr(self, "_plot_dialogs", [])):
            try:
                dlg.close()
            except RuntimeError:
                pass
        self._plot_dialogs = []

        for attr in (
            "_processes_dialog",
            "_selection_browser_dialog",
            "_som_browser_dialog",
            "_mmp_browser_dialog",
            "_mmp_ledger_dialog",
            "_activity_cliff_map_dialog",
            "_mmp_neighborhood_map_dialog",
            "_sali_map_dialog",
            "_sali_browser_dialog",
            "_sketcher_dialog",
            "_protein_viewer_dialog",
            "_calculator_dialog",
            "_data_analysis_dialog",
            "_cluster_dialog",
            "_external_db_dialog",
            "_pubchem_dialog",
            "_chembl_dialog",
            "_patent_query_dialog",
            "_smina_dock_dialog",
            "_pdbqt_generator_dialog",
            "_pdb_fixer_dialog",
        ):
            dlg = getattr(self, attr, None)
            if dlg is None:
                continue
            setattr(self, attr, None)
            try:
                dlg.destroyed.disconnect()
            except (TypeError, RuntimeError):
                pass
            try:
                dlg.hide()
                dlg.close()
            except RuntimeError:
                pass
            try:
                dlg.setParent(None)
            except RuntimeError:
                pass

        for dlg in list(getattr(self, "_floating_result_dialogs", [])):
            try:
                dlg.close()
            except RuntimeError:
                pass
        self._floating_result_dialogs = []

        from ..qt_widget_utils import qobject_is_deleted

        for win in list(getattr(self, "_dock_result_windows", [])):
            if qobject_is_deleted(win):
                continue
            try:
                win._dock_results_force_close = True
                win.close()
            except RuntimeError:
                pass
        self._dock_result_windows = []

        QApplication.processEvents()

        # Brief drain after cancel/kill; this should be near-instant on app close.
        shutdown_wait_ms = 750
        deadline = time.monotonic() + shutdown_wait_ms / 1000.0
        while time.monotonic() < deadline:
            QApplication.processEvents()
            if pq is None or (not pq.has_running_job() and not pq.snapshot().get("fast_running")):
                break
            time.sleep(0.05)

        tp = getattr(self, "threadpool", None)
        if tp is not None:
            clear = getattr(tp, "clear", None)
            if callable(clear):
                clear()

        rtp = getattr(self, "_render_threadpool", None)
        if rtp is not None:
            clear = getattr(rtp, "clear", None)
            if callable(clear):
                clear()

        # Avoid blocking on shutdown; cooperative cancel + pool termination should be enough.
        try:
            from ...fingerprint_cache import clear as clear_fingerprint_cache

            clear_fingerprint_cache()
        except Exception:
            log_swallowed_exception(logger, "fingerprint_cache.clear failed during quit")
        try:
            from ...microstate_cache import clear as clear_microstate_cache

            clear_microstate_cache()
        except Exception:
            log_swallowed_exception(logger, "microstate_cache.clear failed during quit")
        store = getattr(self, "_sqlite_store", None)
        if store is not None:
            try:
                store.close()
            except Exception:
                log_swallowed_exception(logger, "sqlite_store.close failed during quit")

    def _on_export_finished_message(self, message: str) -> None:
        self._export_busy = False
        self._clear_tool_progress(status_message=None)
        self.status_label.setText(message)

    def _on_tool_progress(self, message: str, done: int, total: int) -> None:
        if total >= 0 and message:
            self._tool_progress_state.update(message, done, total)
        text = format_tool_progress_text(message, done, total)
        if text and text == getattr(self, "_last_tool_progress_status", ""):
            return
        self._last_tool_progress_status = text
        if text:
            self.status_label.setText(text)
        hub = getattr(self, "background_activity", None)
        if hub is not None:
            hub.notify_changed()

    def _on_partial_results_notice(self, tool_label: str, done: int, total: int) -> None:
        d = max(0, int(done))
        t = max(1, int(total))
        self._partial_results_notice = (
            f"Cancelled — applied partial results for {tool_label} ({d}/{t})."
        )

    def _consume_partial_results_notice(self) -> str | None:
        note = self._partial_results_notice
        self._partial_results_notice = None
        return note

    def _clear_tool_progress(self, *, status_message: str | None = "Ready.") -> None:
        """Stop polled tool progress; reset status line unless ``status_message`` is ``None``."""
        self._tool_progress_state.end()
        self._tool_progress_active_label = ""
        self._last_tool_progress_status = ""
        if self._tool_progress_poll_timer.isActive():
            self._tool_progress_poll_timer.stop()
        if status_message is not None:
            self.status_label.setText(status_message)
        hub = getattr(self, "background_activity", None)
        if hub is not None:
            hub.notify_changed()

    def _on_table_double_clicked(self, index) -> None:
        if index.isValid():
            self.on_cell_double_click(index.row(), index.column())
