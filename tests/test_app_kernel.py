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

"""Kernel / collaborator wiring for the main-window facade."""

from __future__ import annotations

from qt_helpers import qt_submenu

import types
from typing import Protocol

from mctoolkit.ui import app_roles
from mctoolkit.ui.app_kernel import (
    AppKernel,
    bind_mixin_methods,
    install_window_forwards,
    wrap_mixin_callable,
)
from mctoolkit.ui.gui_settings_mixin import GuiSettingsMixin
from mctoolkit.ui.main_window.app_lifecycle_mixin import AppLifecycleMixin
from mctoolkit.ui.main_window.app_menu_mixin import AppMenuMixin
from mctoolkit.ui.main_window.table_edit_mixin import TableEditMixin
from mctoolkit.ui.main_window.table_menu_mixin import TableMenuMixin
from mctoolkit.ui.main_window.table_search_mixin import TableSearchMixin
from mctoolkit.ui.main_window.table_ui_mixin import TableUIMixin
from mctoolkit.ui.table_write_service import TableWriteHost, TableWriteService
from mctoolkit.ui.tool_dialog_scope import ToolScopeHost

# Frozen allowlist: adding a ChemistryWorkspaceWindow mixin base must fail this set.
_ALLOWED_WINDOW_MIXIN_BASES = frozenset(
    {
        AppLifecycleMixin,
        AppMenuMixin,
        GuiSettingsMixin,
        TableEditMixin,
        TableMenuMixin,
        TableSearchMixin,
        TableUIMixin,
    }
)


# One role growing without bound would just be the kernel again under a new name.
_MAX_ROLE_MEMBERS = 8


def _protocol_members(cls: type) -> set[str]:
    """Attributes and methods a protocol declares itself (not inherited, no dunders)."""
    names = set(cls.__dict__.get("__annotations__", {}))
    names |= {
        name
        for name, obj in vars(cls).items()
        if isinstance(obj, types.FunctionType) and not name.startswith("__")
    }
    return names


def _kernel_roles() -> list[type]:
    return [
        obj
        for obj in vars(app_roles).values()
        if isinstance(obj, type) and getattr(obj, "_is_protocol", False) and obj is not Protocol
    ]


class _Mixin:
    def greet(self, name: str) -> str:
        return f"{self.prefix}{name}"


def test_app_kernel_is_exactly_the_union_of_named_roles() -> None:
    """New kernel surface has to land in a role in ``app_roles``, not in a flat kernel list."""
    assert _protocol_members(AppKernel) == set()
    assert set(AppKernel.__bases__) - {Protocol} == set(_kernel_roles())


def test_no_kernel_role_grows_into_a_second_god_object() -> None:
    oversized = {
        role.__name__: sorted(members)
        for role in _kernel_roles()
        if len(members := _protocol_members(role)) > _MAX_ROLE_MEMBERS
    }
    assert not oversized, f"split these roles further: {oversized}"


def test_bind_mixin_methods_uses_kernel_as_self() -> None:
    class Host:
        prefix = "Hi "

    collab = type("C", (), {})()
    bind_mixin_methods(collab, Host(), _Mixin)
    assert collab.greet("x") == "Hi x"


def test_install_window_forwards_delegates_to_collaborator() -> None:
    class Collab:
        def __init__(self) -> None:
            self.n = 0

        def bump(self) -> int:
            self.n += 1
            return self.n

    class Window:
        def __init__(self) -> None:
            self.collab = Collab()

    class _Src:
        def bump(self) -> int:
            raise AssertionError("mixin body unused")

    install_window_forwards(Window, "collab", (_Src,))
    w = Window()
    assert w.bump() == 1
    assert w.collab.n == 1


def test_lazy_collaborator_constructs_class_and_drops_triggered_bool() -> None:
    from mctoolkit.ui.workspace_tools import _LazyCollaborator

    class Tools:
        def __init__(self, app) -> None:
            self._app = app

        def greet(self) -> str:
            return f"{self._app.tag}hi"

    class _Kernel:
        tag = "k"

    host = _LazyCollaborator(_Kernel(), lambda: Tools)
    assert host.greet() == "khi"
    assert host.greet(False) == "khi"


def test_chemistry_workspace_window_collaborators_and_mro(qapp) -> None:  # noqa: ARG001
    from mctoolkit.ui.main_window import ChemistryWorkspaceWindow
    from mctoolkit.ui.workspace_cluster import ClusterTools
    from mctoolkit.ui.workspace_activity_cliff import ActivityCliffTools
    from mctoolkit.ui.workspace_conformers import ConformersTools
    from mctoolkit.ui.workspace_descriptors import DescriptorsTools
    from mctoolkit.ui.workspace_dock import DockTools
    from mctoolkit.ui.workspace_external import ExternalRecordsTools
    from mctoolkit.ui.workspace_fast_prepare import FastPrepareTools
    from mctoolkit.ui.workspace_fragment import FragmentTools
    from mctoolkit.ui.workspace_mmp import MmpTools
    from mctoolkit.ui.workspace_mmp_neighborhood import MmpNeighborhoodTools
    from mctoolkit.ui.workspace_mpo import MpoTools
    from mctoolkit.ui.workspace_predict import PredictTools
    from mctoolkit.ui.workspace_protonate import ProtonateTools
    from mctoolkit.ui.workspace_qsar import QsarTools
    from mctoolkit.ui.workspace_reaction import ReactionTools
    from mctoolkit.ui.workspace_sali import SaliTools
    from mctoolkit.ui.workspace_sql_load import SqlLoadTools
    from mctoolkit.ui.workspace_structure_edit import StructureEditTools
    from mctoolkit.ui.workspace_structure_writeback import StructureWritebackTools
    from mctoolkit.ui.workspace_table_calc import TableCalcTools
    from mctoolkit.ui.workspace_viewers import ViewerOpenersTools
    from mctoolkit.ui.filters.filter_panel import FilterPanel
    from mctoolkit.ui.table_build_export import TableBuildExport
    from mctoolkit.ui.workspace_plot import PlotSync

    w = ChemistryWorkspaceWindow()
    assert w.progress is not None
    assert w.tool_scope is not None
    assert w.table_write is not None
    assert w.table_session is not None
    assert w.build_pipeline is not None
    assert w.session is not None
    assert w.workspace_tools is not None
    assert w.filter_panel is not None
    assert w.plot_sync is not None
    assert w.plot_dock is not None
    mro = type(w).mro()
    off_mro = (
        ClusterTools,
        QsarTools,
        MpoTools,
        MmpTools,
        MmpNeighborhoodTools,
        ActivityCliffTools,
        SaliTools,
        ProtonateTools,
        FastPrepareTools,
        StructureEditTools,
        StructureWritebackTools,
        ViewerOpenersTools,
        ExternalRecordsTools,
        TableCalcTools,
        FragmentTools,
        ReactionTools,
        DescriptorsTools,
        ConformersTools,
        SqlLoadTools,
        DockTools,
        PredictTools,
        FilterPanel,
        TableBuildExport,
        PlotSync,
    )
    for cls in off_mro:
        assert cls not in mro
    project_mixins = {
        cls
        for cls in mro
        if cls.__module__.startswith("mctoolkit.") and cls is not ChemistryWorkspaceWindow
    }
    assert project_mixins == _ALLOWED_WINDOW_MIXIN_BASES
    assert hasattr(w, "_begin_tool_progress")
    assert hasattr(w, "on_calc_finished")
    assert hasattr(w, "_selected_oids_set")
    assert hasattr(w, "_ensure_columns")
    assert hasattr(w, "_abort_if_only_selected_but_empty")
    assert hasattr(w, "open_cluster_dialog")
    assert hasattr(w, "apply_filters")
    assert hasattr(w, "open_file_dialog")
    assert hasattr(w, "dock_plot_widget")
    assert hasattr(w, "_open_dimension_reduction_dialog")
    assert hasattr(w, "run_protonate")
    assert hasattr(w, "open_tautomer_generator")
    assert hasattr(w, "open_tautomer_browser")
    assert hasattr(w, "open_protomer_browser")
    assert hasattr(w, "run_fast_prepare")
    assert hasattr(w, "run_disconnect_fragments")
    assert hasattr(w, "run_neutralize")
    assert hasattr(w, "_write_mol_to_source_column")
    assert w.table_write._unique_table_column_names(["LogP"]) == ["LogP"]
    unsatisfied = {
        role.__name__: sorted(n for n in _protocol_members(role) if not hasattr(w, n))
        for role in (*_kernel_roles(), ToolScopeHost, TableWriteHost)
    }
    assert not {k: v for k, v in unsatisfied.items() if v}, unsatisfied
    w.close()


def test_wrap_mixin_callable_drops_qt_triggered_bool() -> None:
    class Host:
        prefix = "Hi "

    def greet(self, name: str) -> str:
        return f"{self.prefix}{name}"

    def open_tool(self) -> str:
        return "opened"

    bound_greet = wrap_mixin_callable(greet, Host())
    bound_open = wrap_mixin_callable(open_tool, Host())
    assert bound_greet("x") == "Hi x"
    assert bound_open() == "opened"
    assert bound_open(False) == "opened"


def test_qsar_menu_action_opens_with_triggered_bool(qapp) -> None:  # noqa: ARG001
    from rdkit import Chem

    from mctoolkit.ui.main_window import ChemistryWorkspaceWindow

    w = ChemistryWorkspaceWindow()
    w.headers = ["ID_HIDDEN", "Structure", "SMILES", "MW"]
    w._table_model.set_headers(list(w.headers))
    w._table_model.append_row(0, {"SMILES": "CCO", "MW": "46.07"})
    w.mols[0] = Chem.MolFromSmiles("CCO")
    w.next_oid = 1
    try:
        w.open_qsar_dialog(False)
        assert w._qsar_dialog is not None
        mb = w.menuBar()
        data = qt_submenu(mb, "Data")
        act = next(a for a in data.actions() if a.text().replace("&", "").startswith("QSAR"))
        act.trigger()
        assert w._qsar_dialog is not None
    finally:
        dlg = getattr(w, "_qsar_dialog", None)
        if dlg is not None:
            dlg.close()
        w.close()


def test_column_write_host_unique_names() -> None:
    host = types.SimpleNamespace(headers=["ID_HIDDEN", "Structure", "LogP"])
    assert TableWriteService(host)._unique_table_column_names(["LogP"]) == ["LogP (1)"]
