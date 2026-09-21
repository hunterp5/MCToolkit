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
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with MCToolkit.  If not, see <https://www.gnu.org/licenses/>.

"""Central environment-driven settings (see README env table)."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from .env import env_get

logger = logging.getLogger(__name__)


def _env_str(name: str, default: str) -> str:
    raw = (env_get(name) or "").strip()
    return raw if raw else default


def _env_int(name: str, default: int, *, lo: int, hi: int | None = None) -> int:
    try:
        v = int((env_get(name) or "").strip() or str(default))
    except ValueError:
        v = default
    v = max(lo, v)
    if hi is not None:
        v = min(v, hi)
    return v


def _env_optional_positive_int(name: str, *, lo: int, hi: int) -> int | None:
    raw = (env_get(name) or "").strip()
    if not raw:
        return None
    try:
        v = int(raw)
    except ValueError:
        return None
    return max(lo, min(v, hi))


def _env_truthy(name: str) -> bool:
    return (env_get(name) or "").strip().lower() in ("1", "true", "yes", "on")


def _env_bool(name: str, default: bool) -> bool:
    raw = (env_get(name) or "").strip().lower()
    if not raw:
        return default
    if raw in ("0", "false", "no", "off"):
        return False
    if raw in ("1", "true", "yes", "on"):
        return True
    return default


def _env_float(name: str, default: float, *, lo: float) -> float:
    try:
        v = float((env_get(name) or "").strip() or str(default))
    except ValueError:
        v = default
    return max(lo, v)


def clamp_substructure_async_rows(raw: str | None) -> int:
    """Match ``FilterPanel`` / worker threshold semantics."""
    default = 400
    try:
        thresh = int((raw or "").strip() or str(default))
    except ValueError:
        thresh = default
    return max(64, min(thresh, 500_000))


@dataclass(frozen=True)
class MCToolkitConfig:
    log_level: str
    max_threadpool: int | None
    render_threadpool: int | None
    substructure_async_rows: int
    sql_max_rows_hard: int
    sql_precount_warn: int
    sqlite_timeout_s: float
    pg_connect_timeout: int
    conformer_threads: int | None
    descriptor_threads: int | None
    descriptor_process_pool_min_rows: int
    descriptor_fp_process_pool_min_rows: int
    descriptor_process_pool_batch_size: int
    fast_prepare_batch_size: int
    fast_prepare_process_pool_min_rows: int
    render2d_process_workers: int | None
    render2d_batch_size: int
    background_job_poll_ms: int
    bulk_update_defer_color_cache_rows: int
    protomer_process_workers: int | None
    pka_process_workers: int | None
    disable_custom_calc: bool
    filter_debounce_substructure_rows: int
    filter_debounce_substructure_ms: int
    filter_debounce_default_rows: int
    filter_debounce_default_ms: int
    filter_async_min_rows: int
    filter_chunk_rows: int
    bounds_async_min_rows: int
    bounds_chunk_rows: int
    ingest_gui_chunk_size: int
    session_gui_chunk_size: int
    ingest_gui_subslice_rows: int
    ingest_gui_time_budget_ms: int
    ingest_worker_batch_size: int
    ingest_csv_text_first: bool
    ingest_silent_model_append: bool
    ingest_sqlite_incremental: bool
    structure_render_lazy_after_ingest_min_rows: int
    perf_metrics_enabled: bool
    perf_log_every: int
    sqlite_backend_page_size: int
    auto_render_2d_max_rows: int
    structure_render_lazy_min_rows: int
    structure_render_pixmap_lru: int
    fingerprint_cache_max_entries: int
    tool_progress_poll_ms: int
    status_memory_enabled: bool
    status_memory_poll_ms: int
    table_selection_oid_override_min: int
    table_selection_chunk_rows: int
    plot_scattergl_min_points: int
    plot_selection_overlay_max_points: int
    table_delete_batch_min: int
    table_delete_chunk_rows: int
    table_undo_limit: int
    mol_cache_lru: int
    structure_render_png_max_entries: int
    memory_guard_conf_max_rows: int
    memory_guard_conf_max_row_confs: int
    memory_guard_cluster_max_rows: int
    memory_guard_diverse_max_rows: int
    memory_guard_diverse_max_kn: int
    diverse_subset_exact_max_rows: int
    diverse_subset_fast_candidate_cap: int
    memory_guard_fp_matrix_max_cells: int
    memory_guard_enum_max_products: int
    memory_guard_dimred_max_points: int
    recomp_constraint_candidate_multiplier: int
    recomp_constraint_min_candidates: int


def _warn_retired_custom_calc_legacy_eval() -> None:
    if _env_truthy("MCTOOLKIT_CUSTOM_CALC_LEGACY_EVAL"):
        logger.warning(
            "MCTOOLKIT_CUSTOM_CALC_LEGACY_EVAL is retired and ignored; "
            "custom calculator expressions always use the AST calculator_expressions path."
        )


def load_config() -> MCToolkitConfig:
    """Read current settings from ``os.environ`` (no process-wide cache — tests can monkeypatch)."""
    _warn_retired_custom_calc_legacy_eval()
    hard = _env_int("MCTOOLKIT_SQL_MAX_ROWS_HARD", 2_000_000, lo=1000, hi=50_000_000)
    precowarn = _env_int("MCTOOLKIT_SQL_PRECOUNT_WARN", 100_000, lo=1000, hi=hard)
    return MCToolkitConfig(
        log_level=_env_str("MCTOOLKIT_LOG_LEVEL", "INFO").upper(),
        max_threadpool=_env_optional_positive_int("MCTOOLKIT_MAX_THREADPOOL", lo=1, hi=64),
        render_threadpool=_env_optional_positive_int("MCTOOLKIT_RENDER_THREADPOOL", lo=1, hi=32),
        substructure_async_rows=clamp_substructure_async_rows(
            env_get("MCTOOLKIT_SUBSTRUCTURE_ASYNC_ROWS")
        ),
        sql_max_rows_hard=hard,
        sql_precount_warn=precowarn,
        sqlite_timeout_s=_env_float("MCTOOLKIT_SQLITE_TIMEOUT_S", 30.0, lo=0.1),
        pg_connect_timeout=_env_int("MCTOOLKIT_PG_CONNECT_TIMEOUT", 30, lo=1, hi=3600),
        conformer_threads=_env_optional_positive_int("MCTOOLKIT_CONFORMER_THREADS", lo=1, hi=16),
        descriptor_threads=_env_optional_positive_int("MCTOOLKIT_DESCRIPTOR_THREADS", lo=1, hi=32),
        descriptor_process_pool_min_rows=_env_int(
            "MCTOOLKIT_DESCRIPTOR_PROCESS_POOL_MIN_ROWS", 1500, lo=0, hi=10_000_000
        ),
        descriptor_fp_process_pool_min_rows=_env_int(
            "MCTOOLKIT_DESCRIPTOR_FP_PROCESS_POOL_MIN_ROWS", 64, lo=2, hi=10_000_000
        ),
        descriptor_process_pool_batch_size=_env_int(
            "MCTOOLKIT_DESCRIPTOR_PROCESS_POOL_BATCH_SIZE", 32, lo=1, hi=512
        ),
        render2d_process_workers=_env_optional_positive_int(
            "MCTOOLKIT_RENDER2D_PROCESS_WORKERS", lo=1, hi=32
        ),
        # Molecules per child-process render task. One-per-task made the parent process the
        # throughput ceiling, so extra workers bought nothing.
        render2d_batch_size=_env_int("MCTOOLKIT_RENDER2D_BATCH_SIZE", 64, lo=1, hi=4096),
        fast_prepare_batch_size=_env_int("MCTOOLKIT_FAST_PREPARE_BATCH_SIZE", 64, lo=1, hi=2048),
        # Below this row count, child-process startup costs more than the work it saves.
        fast_prepare_process_pool_min_rows=_env_int(
            "MCTOOLKIT_FAST_PREPARE_PROCESS_POOL_MIN_ROWS", 250, lo=2, hi=10_000_000
        ),
        background_job_poll_ms=_env_int("MCTOOLKIT_BACKGROUND_JOB_POLL_MS", 500, lo=100, hi=5000),
        bulk_update_defer_color_cache_rows=_env_int(
            "MCTOOLKIT_BULK_UPDATE_DEFER_COLOR_CACHE_ROWS", 5000, lo=0, hi=10_000_000
        ),
        protomer_process_workers=_env_optional_positive_int(
            "MCTOOLKIT_PROTOMER_PROCESSES", lo=1, hi=8
        ),
        pka_process_workers=_env_optional_positive_int("MCTOOLKIT_PKA_PROCESS_WORKERS", lo=1, hi=8),
        disable_custom_calc=_env_truthy("MCTOOLKIT_DISABLE_CUSTOM_CALC"),
        filter_debounce_substructure_rows=_env_int(
            "MCTOOLKIT_FILTER_DEBOUNCE_SUBSTRUCTURE_ROWS", 120, lo=1, hi=1_000_000
        ),
        filter_debounce_substructure_ms=_env_int(
            "MCTOOLKIT_FILTER_DEBOUNCE_SUBSTRUCTURE_MS", 85, lo=0, hi=60_000
        ),
        filter_debounce_default_rows=_env_int(
            "MCTOOLKIT_FILTER_DEBOUNCE_DEFAULT_ROWS", 0, lo=0, hi=1_000_000
        ),
        filter_debounce_default_ms=_env_int(
            "MCTOOLKIT_FILTER_DEBOUNCE_DEFAULT_MS", 80, lo=0, hi=60_000
        ),
        filter_async_min_rows=_env_int(
            "MCTOOLKIT_FILTER_ASYNC_MIN_ROWS", 5000, lo=1, hi=10_000_000
        ),
        filter_chunk_rows=_env_int("MCTOOLKIT_FILTER_CHUNK_ROWS", 2000, lo=64, hi=100_000),
        bounds_async_min_rows=_env_int(
            "MCTOOLKIT_BOUNDS_ASYNC_MIN_ROWS", 5000, lo=1, hi=10_000_000
        ),
        bounds_chunk_rows=_env_int("MCTOOLKIT_BOUNDS_CHUNK_ROWS", 2000, lo=64, hi=100_000),
        ingest_gui_chunk_size=_env_int("MCTOOLKIT_INGEST_GUI_CHUNK", 512, lo=16, hi=10_000),
        session_gui_chunk_size=_env_int("MCTOOLKIT_SESSION_GUI_CHUNK", 4096, lo=64, hi=50_000),
        ingest_gui_subslice_rows=_env_int("MCTOOLKIT_INGEST_GUI_SUBSLICE", 128, lo=16, hi=10_000),
        ingest_gui_time_budget_ms=_env_int("MCTOOLKIT_INGEST_GUI_TIME_MS", 30, lo=5, hi=200),
        ingest_worker_batch_size=_env_int("MCTOOLKIT_INGEST_WORKER_BATCH", 2000, lo=64, hi=20_000),
        ingest_csv_text_first=_env_bool("MCTOOLKIT_INGEST_CSV_TEXT_FIRST", True),
        ingest_silent_model_append=_env_bool("MCTOOLKIT_INGEST_SILENT_MODEL_APPEND", True),
        ingest_sqlite_incremental=_env_bool("MCTOOLKIT_INGEST_SQLITE_INCREMENTAL", True),
        structure_render_lazy_after_ingest_min_rows=_env_int(
            "MCTOOLKIT_STRUCTURE_RENDER_LAZY_AFTER_INGEST", 200, lo=0, hi=10_000_000
        ),
        perf_metrics_enabled=_env_truthy("MCTOOLKIT_PERF_METRICS"),
        perf_log_every=_env_int("MCTOOLKIT_PERF_LOG_EVERY", 25, lo=1, hi=10_000),
        sqlite_backend_page_size=_env_int(
            "MCTOOLKIT_SQLITE_BACKEND_PAGE_SIZE", 5000, lo=100, hi=200_000
        ),
        auto_render_2d_max_rows=_env_int(
            "MCTOOLKIT_AUTO_RENDER_2D_MAX_ROWS", 25_000, lo=0, hi=10_000_000
        ),
        structure_render_lazy_min_rows=_env_int(
            "MCTOOLKIT_STRUCTURE_RENDER_LAZY_MIN_ROWS", 5_000, lo=500, hi=10_000_000
        ),
        structure_render_pixmap_lru=_env_int(
            "MCTOOLKIT_STRUCTURE_RENDER_PIXMAP_LRU", 384, lo=32, hi=4096
        ),
        fingerprint_cache_max_entries=_env_int(
            "MCTOOLKIT_FINGERPRINT_CACHE_MAX_ENTRIES", 50_000, lo=0, hi=5_000_000
        ),
        tool_progress_poll_ms=_env_int("MCTOOLKIT_TOOL_PROGRESS_POLL_MS", 200, lo=50, hi=2000),
        status_memory_enabled=_env_bool("MCTOOLKIT_STATUS_MEMORY", True),
        status_memory_poll_ms=_env_int("MCTOOLKIT_STATUS_MEMORY_POLL_MS", 2000, lo=500, hi=60_000),
        table_selection_oid_override_min=_env_int(
            "MCTOOLKIT_TABLE_SELECTION_OID_OVERRIDE_MIN", 2500, lo=100, hi=10_000_000
        ),
        table_selection_chunk_rows=_env_int(
            "MCTOOLKIT_TABLE_SELECTION_CHUNK_ROWS", 2000, lo=64, hi=100_000
        ),
        # WebGL scatter above this count (pan/zoom/select stay responsive on large sets).
        plot_scattergl_min_points=_env_int(
            "MCTOOLKIT_PLOT_SCATTERGL_MIN_POINTS", 2000, lo=0, hi=10_000_000
        ),
        # SVG overlay highlight is nicer for small lassos; above this use selectedpoints.
        plot_selection_overlay_max_points=_env_int(
            "MCTOOLKIT_PLOT_SELECTION_OVERLAY_MAX", 400, lo=0, hi=100_000
        ),
        table_delete_batch_min=_env_int(
            "MCTOOLKIT_TABLE_DELETE_BATCH_MIN", 50, lo=1, hi=10_000_000
        ),
        table_delete_chunk_rows=_env_int(
            "MCTOOLKIT_TABLE_DELETE_CHUNK_ROWS", 2000, lo=64, hi=100_000
        ),
        table_undo_limit=_env_int("MCTOOLKIT_TABLE_UNDO_LIMIT", 50, lo=1, hi=500),
        mol_cache_lru=_env_int("MCTOOLKIT_MOL_CACHE_LRU", 256, lo=8, hi=4096),
        structure_render_png_max_entries=_env_int(
            # 0 = unlimited PNG bytes in the lazy structure store (decoded QPixmaps stay LRU-capped).
            # A positive cap was dropping Fast Prepare / Render 2D drawings beyond this limit.
            "MCTOOLKIT_STRUCTURE_RENDER_PNG_MAX",
            0,
            lo=0,
            hi=10_000_000,
        ),
        memory_guard_conf_max_rows=_env_int(
            "MCTOOLKIT_MEMORY_GUARD_CONF_MAX_ROWS", 5_000, lo=1, hi=10_000_000
        ),
        memory_guard_conf_max_row_confs=_env_int(
            "MCTOOLKIT_MEMORY_GUARD_CONF_MAX_ROW_CONFS", 1_000_000, lo=100, hi=50_000_000
        ),
        memory_guard_cluster_max_rows=_env_int(
            "MCTOOLKIT_MEMORY_GUARD_CLUSTER_MAX_ROWS", 25_000, lo=100, hi=10_000_000
        ),
        memory_guard_diverse_max_rows=_env_int(
            "MCTOOLKIT_MEMORY_GUARD_DIVERSE_MAX_ROWS", 200_000, lo=100, hi=10_000_000
        ),
        memory_guard_diverse_max_kn=_env_int(
            "MCTOOLKIT_MEMORY_GUARD_DIVERSE_MAX_KN",
            50_000_000,
            lo=1_000,
            hi=2_000_000_000,
        ),
        diverse_subset_exact_max_rows=_env_int(
            "MCTOOLKIT_DIVERSE_SUBSET_EXACT_MAX_ROWS", 50_000, lo=100, hi=10_000_000
        ),
        diverse_subset_fast_candidate_cap=_env_int(
            "MCTOOLKIT_DIVERSE_SUBSET_FAST_CANDIDATE_CAP", 10_000, lo=100, hi=500_000
        ),
        memory_guard_fp_matrix_max_cells=_env_int(
            "MCTOOLKIT_MEMORY_GUARD_FP_MATRIX_MAX_CELLS",
            # 25k dimred rows × 2048-bit fingerprints (float64 working matrix).
            25_000 * 2048,
            lo=100_000,
            hi=2_000_000_000,
        ),
        memory_guard_enum_max_products=_env_int(
            "MCTOOLKIT_MEMORY_GUARD_ENUM_MAX_PRODUCTS", 10_000, lo=10, hi=50_000
        ),
        memory_guard_dimred_max_points=_env_int(
            "MCTOOLKIT_MEMORY_GUARD_DIMRED_MAX_POINTS", 25_000, lo=100, hi=50_000
        ),
        recomp_constraint_candidate_multiplier=_env_int(
            "MCTOOLKIT_RECOMP_CONSTRAINT_CANDIDATE_MULT", 100, lo=10, hi=10_000
        ),
        recomp_constraint_min_candidates=_env_int(
            "MCTOOLKIT_RECOMP_CONSTRAINT_MIN_CANDIDATES", 10_000, lo=1000, hi=10_000_000
        ),
    )
