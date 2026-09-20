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

"""Lazy leaf-tool collaborators (cluster, dimred, QSAR, MPO, medchem, MMP/SALI, structure-prep, viewers, calc, fragments, reactions, descriptors, conformers, SQL, dock, predict).

Importing this module does not import the tool bodies or their dialogs.
First use of a property constructs that collaborator with the window as ``self._app``.

New tools belong here (or as module functions + ``install_window_forwards``),
not as ``ChemistryWorkspaceWindow`` bases.
"""

from __future__ import annotations

import types
from collections.abc import Callable
from typing import Any, Protocol

from .app_roles import JobScheduler, ProgressChrome, SessionState, TableData, TableSelection


class WorkspaceToolDialogOps(Protocol):
    """Dialog scope, selection, and writeback the leaf tools still call on the window."""

    def _prepare_tool_dialog(self, dialog: Any) -> None: ...
    def _sync_dialog_only_selected_scope(self, dlg: Any) -> None: ...
    def _abort_if_only_selected_but_empty(
        self, only_selected: bool, allowed: set | frozenset | None, title: str
    ) -> bool: ...
    def _selected_logical_rows(self) -> list: ...
    def _all_oids_in_table_order(self) -> list[int]: ...
    def logical_row_for_oid(self, oid: int) -> int: ...
    def chemistry_tool_structure_sources(self) -> list[str]: ...
    def on_calc_finished(self, *args: Any, **kwargs: Any) -> Any: ...


class WorkspaceToolMolOps(Protocol):
    """Progress chrome and mol/render helpers structure-prep still reaches through the facade."""

    def _consume_partial_results_notice(self) -> str | None: ...
    def _clear_tool_progress(self, *, status_message: str | None = None) -> None: ...
    def _table_cell_text(self, row: int, col: int) -> str: ...
    def _canonical_smiles_header_for_updates(self) -> str | None: ...
    def _start_render_2d_batch(self, *args: Any, **kwargs: Any) -> None: ...
    def _build_render2d_tasks_in_table_order(self, *args: Any, **kwargs: Any) -> Any: ...
    def _mol_for_structure_row(self, row: int) -> Any: ...
    def _mol_from_structure_text(self, raw: str) -> Any: ...


class WorkspaceProtonateState(Protocol):
    """In-flight protomer job handle and writeback context."""

    _protonate_signals: Any
    _protonate_run_ctx: Any


class WorkspaceFastPrepareState(Protocol):
    """Fast Prepare output column and scope remembered until the worker finishes."""

    _fast_prepare_source: str
    _fast_prepare_allowed_oids: Any
    _fast_prepare_fragments_col: str
    _fast_prepare_update_target: bool


class WorkspaceDisconnectState(Protocol):
    """Disconnect-fragments column names and render flag for the queued job."""

    _disconnect_source: str
    _disconnect_update_target: bool
    _disconnect_largest_col: Any
    _disconnect_fragments_col: str
    _disconnect_no_render_2d: bool


class WorkspaceHydrogenState(Protocol):
    """Add/remove explicit-H source column and render flag for the queued job."""

    _add_explicit_hydrogens_source: str
    _add_explicit_hydrogens_no_render_2d: bool
    _remove_explicit_hydrogens_source: str
    _remove_explicit_hydrogens_no_render_2d: bool


class WorkspaceNeutralizeState(Protocol):
    """Neutralize source column and render flag for the queued job."""

    _neutralize_source: str
    _neutralize_no_render_2d: bool


class WorkspaceMmpState(Protocol):
    """Last MMP run so Transform Ledger can reopen in this session."""

    _mmp_last_pairs: Any
    _mmp_last_activity_column: str


class WorkspaceToolsHost(
    TableData,
    TableSelection,
    ProgressChrome,
    SessionState,
    JobScheduler,
    WorkspaceToolDialogOps,
    WorkspaceToolMolOps,
    WorkspaceProtonateState,
    WorkspaceFastPrepareState,
    WorkspaceDisconnectState,
    WorkspaceHydrogenState,
    WorkspaceNeutralizeState,
    WorkspaceMmpState,
    Protocol,
):
    """What lazy workspace tools need from the window.

    Kernel table/progress/session/job members stay on the window, as do the
    in-flight structure-prep job flags. Dialog singleton handles are reached
    with getattr so session restore and lifecycle teardown keep seeing them
    on the facade.
    """

    def calculate_global_bounds(self, *args: Any, **kwargs: Any) -> None: ...


def _drop_extra_positional(fn: Callable) -> Callable:
    """Drop Qt ``triggered(bool)`` extras the way ``wrap_mixin_callable`` did.

    Menu actions call window forwards, which call into the lazy collaborator.
    Leaf openers still declare no extra args.
    """
    code = getattr(getattr(fn, "__func__", fn), "__code__", None)
    accepts_varargs = bool(getattr(code, "co_flags", 0) & 0x04)
    max_pos = None
    if code is not None and not accepts_varargs:
        max_pos = max(0, int(code.co_argcount) - 1)

    def call(*args: Any, **kwargs: Any):
        if max_pos is not None and len(args) > max_pos:
            args = args[:max_pos]
        return fn(*args, **kwargs)

    call.__name__ = getattr(fn, "__name__", "call")
    call.__doc__ = fn.__doc__
    call.__wrapped__ = fn  # type: ignore[attr-defined]
    return call


class _LazyCollaborator:
    """Construct one collaborator class the first time a method is needed."""

    def __init__(self, app: WorkspaceToolsHost, import_cls) -> None:
        self._app = app
        self._import_cls = import_cls
        self._bound: Any = None

    def _ensure(self) -> Any:
        if self._bound is None:
            self._bound = self._import_cls()(self._app)
        return self._bound

    def __getattr__(self, name: str):
        attr = getattr(self._ensure(), name)
        if isinstance(attr, types.MethodType):
            return _drop_extra_positional(attr)
        return attr


class WorkspaceTools:
    """On-demand tool adapters so the window class need not inherit leaf mixins."""

    def __init__(self, app: WorkspaceToolsHost) -> None:
        self._app = app
        self.cluster = _LazyCollaborator(
            app, lambda: _load("molmanager.ui.workspace_cluster", "ClusterTools")
        )
        self.dimension_reduction = _LazyCollaborator(
            app,
            lambda: _load("molmanager.ui.workspace_dimred", "DimensionReductionTools"),
        )
        self.medchem_space = _LazyCollaborator(
            app, lambda: _load("molmanager.ui.workspace_medchem", "MedChemSpaceTools")
        )
        self.qsar = _LazyCollaborator(
            app, lambda: _load("molmanager.ui.workspace_qsar", "QsarTools")
        )
        self.mpo = _LazyCollaborator(app, lambda: _load("molmanager.ui.workspace_mpo", "MpoTools"))
        self.mmp = _LazyCollaborator(app, lambda: _load("molmanager.ui.workspace_mmp", "MmpTools"))
        self.mmp_neighborhood = _LazyCollaborator(
            app, lambda: _load("molmanager.ui.workspace_mmp_neighborhood", "MmpNeighborhoodTools")
        )
        self.activity_cliff = _LazyCollaborator(
            app, lambda: _load("molmanager.ui.workspace_activity_cliff", "ActivityCliffTools")
        )
        self.sali = _LazyCollaborator(app, lambda: _load("molmanager.ui.workspace_sali", "SaliTools"))
        self.structure_prep = _LazyCollaborator(app, _load_structure_prep)
        self.viewers = _LazyCollaborator(
            app, lambda: _load("molmanager.ui.workspace_viewers", "ViewerOpenersTools")
        )
        self.external = _LazyCollaborator(
            app, lambda: _load("molmanager.ui.workspace_external", "ExternalRecordsTools")
        )
        self.table_calc = _LazyCollaborator(
            app, lambda: _load("molmanager.ui.workspace_table_calc", "TableCalcTools")
        )
        self.fragment = _LazyCollaborator(
            app, lambda: _load("molmanager.ui.workspace_fragment", "FragmentTools")
        )
        self.reaction = _LazyCollaborator(
            app, lambda: _load("molmanager.ui.workspace_reaction", "ReactionTools")
        )
        self.descriptors = _LazyCollaborator(
            app, lambda: _load("molmanager.ui.workspace_descriptors", "DescriptorsTools")
        )
        self.conformers = _LazyCollaborator(
            app, lambda: _load("molmanager.ui.workspace_conformers", "ConformersTools")
        )
        self.sql_load = _LazyCollaborator(
            app, lambda: _load("molmanager.ui.workspace_sql_load", "SqlLoadTools")
        )
        self.dock = _LazyCollaborator(
            app, lambda: _load("molmanager.ui.workspace_dock", "DockTools")
        )
        self.predict = _LazyCollaborator(
            app, lambda: _load("molmanager.ui.workspace_predict", "PredictTools")
        )


def _load(module: str, name: str):
    import importlib

    return getattr(importlib.import_module(module), name)


def _load_structure_prep():
    ProtonateTools = _load("molmanager.ui.workspace_protonate", "ProtonateTools")
    FastPrepareTools = _load("molmanager.ui.workspace_fast_prepare", "FastPrepareTools")
    StructureEditTools = _load("molmanager.ui.workspace_structure_edit", "StructureEditTools")
    StructureWritebackTools = _load(
        "molmanager.ui.workspace_structure_writeback", "StructureWritebackTools"
    )

    class StructurePrepTools(
        ProtonateTools, FastPrepareTools, StructureEditTools, StructureWritebackTools
    ):
        def __init__(self, app: WorkspaceToolsHost) -> None:
            self._app = app

    return StructurePrepTools
