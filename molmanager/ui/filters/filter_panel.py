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

"""Filter-panel collaborator: cards, apply, substructure, and bounds."""

from __future__ import annotations

from typing import Any, Protocol

from .filter_apply import FilterApply
from .filter_bounds import FilterBounds
from .filter_cards_ops import FilterCards
from .filter_substructure import FilterSubstructure


class FilterPanelChrome(Protocol):
    """Filter-panel widgets and the live card list."""

    f_panel: Any
    f_container: Any
    filters: list
    _filter_scroll: Any
    _filter_cards_host: Any


class FilterPanelJobs(Protocol):
    """Async filter-apply / substructure job tokens on the window."""

    _filter_job_gen: int
    _filter_bg_job_id: str | None
    _filter_pending_substructure: Any
    _substructure_job_gen: int
    _substructure_bg_job_id: str | None
    _substructure_job_queries: Any
    _substructure_job_smarts: Any
    _substructure_job_source: Any


class FilterPanelBoundsState(Protocol):
    """Chunked bounds-scan cursor used by filter sliders."""

    _bounds_on_complete: Any
    _bounds_chunk_gen: int
    _bounds_chunk_active: bool
    _bounds_chunk_headers: list
    _bounds_chunk_col_i: int
    _bounds_chunk_row_i: int
    _bounds_chunk_acc: dict
    _filter_target_smiles_cache: Any


class FilterPanelApplyState(Protocol):
    """Chunked apply cursor and SMARTS target cache."""

    _chunked_filter_state: Any
    _substructure_target_mol_cache: dict
    _apply_filters_timer: Any

    def _visible_source_row_indices(self) -> Any: ...
    def _schedule_active_plots_replot(self, *args: Any, **kwargs: Any) -> Any: ...
    def _refresh_active_plot_axis_columns(self) -> None: ...
    def _mol_for_structure_row(self, row: int) -> Any: ...
    def logical_row_for_oid(self, oid: int) -> int: ...


class FilterPanelHost(
    FilterPanelChrome,
    FilterPanelJobs,
    FilterPanelBoundsState,
    FilterPanelApplyState,
    Protocol,
):
    """What the filter-panel collaborator reads from the window."""


class FilterPanel(FilterCards, FilterApply, FilterSubstructure, FilterBounds):
    """Owns filter-card chrome, apply routing, SMARTS jobs, and bounds scans."""

    def __init__(self, app: FilterPanelHost) -> None:
        self._app = app
