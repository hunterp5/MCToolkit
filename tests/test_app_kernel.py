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

"""Kernel / collaborator wiring for the main-window facade."""

from __future__ import annotations

from molmanager.ui.app_kernel import (
    bind_mixin_methods,
    install_window_forwards,
    wrap_mixin_callable,
)
from molmanager.ui.main_window.column_write_mixin import ColumnWriteMixin


class _Mixin:
    def greet(self, name: str) -> str:
        return f"{self.prefix}{name}"


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


def test_chemistry_workspace_window_collaborators_and_mro(qapp) -> None:  # noqa: ARG001
    from molmanager.ui.main_window import ChemistryWorkspaceWindow
    from molmanager.ui.main_window.chemistry_mixin import ChemistryMixin
    from molmanager.ui.main_window.cluster_mixin import ClusterMixin
    from molmanager.ui.main_window.mpo_mixin import MpoMixin
    from molmanager.ui.main_window.qsar_mixin import QsarMixin
    from molmanager.ui.main_window.session_mixin import SessionMixin

    w = ChemistryWorkspaceWindow()
    assert w.progress is not None
    assert w.tool_scope is not None
    assert w.table_write is not None
    assert w.table_session is not None
    assert w.build_pipeline is not None
    assert w.session is not None
    assert w.workspace_tools is not None
    mro = type(w).mro()
    for cls in (ChemistryMixin, SessionMixin, ClusterMixin, QsarMixin, MpoMixin):
        assert cls not in mro
    assert hasattr(w, "_begin_tool_progress")
    assert hasattr(w, "on_calc_finished")
    assert hasattr(w, "_selected_oids_set")
    assert hasattr(w, "_ensure_columns")
    assert hasattr(w, "_abort_if_only_selected_but_empty")
    assert hasattr(w, "open_cluster_dialog")
    assert hasattr(w, "_open_dimension_reduction_dialog")
    assert w.table_write._unique_table_column_names(["LogP"]) == ["LogP"]
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

    from molmanager.ui.main_window import ChemistryWorkspaceWindow

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
        data = next(a.menu() for a in mb.actions() if a.text().replace("&", "") == "Data")
        act = next(a for a in data.actions() if a.text().replace("&", "").startswith("QSAR"))
        act.trigger()
        assert w._qsar_dialog is not None
    finally:
        dlg = getattr(w, "_qsar_dialog", None)
        if dlg is not None:
            dlg.close()
        w.close()


def test_column_write_host_unique_names() -> None:
    host = type("H", (ColumnWriteMixin,), {})()
    host.headers = ["ID_HIDDEN", "Structure", "LogP"]
    assert host._unique_table_column_names(["LogP"]) == ["LogP (1)"]
