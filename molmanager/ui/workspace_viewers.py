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

"""Open Plotter, Sketcher, Browser structure views, and Data analysis."""

from __future__ import annotations

from typing import Any, Protocol

from PySide6.QtWidgets import QMessageBox
from ..chem.molecule_conversion import is_rdkit_mol
from .analysis_job_support import ensure_table_ready_for_tool
from .singleton_modeless_dialog import reuse_or_show_modeless_singleton


class ViewerPlotOps(Protocol):
    """Plot-dialog helpers ViewerOpenersTools still calls on the window."""

    def _create_plot_dialog(self) -> Any: ...
    def _sync_active_plots_from_table_selection(self) -> None: ...
    def _workspace(self) -> Any: ...


class ViewerOpenersTools:
    def __init__(self, app: ViewerPlotOps) -> None:
        self._app = app

    def open_data_analysis(self):
        if not ensure_table_ready_for_tool(
            self._app,
            "Data",
            require_rows=True,
            empty_message="Open a file or add rows so the table has data to analyze.",
        ):
            return
        from .dialogs.data_analysis import DataAnalysisDialog

        def _factory() -> DataAnalysisDialog:
            dlg = DataAnalysisDialog(self._app)
            self._app._prepare_tool_dialog(dlg)
            return dlg

        def _on_reused(dlg: DataAnalysisDialog) -> None:
            self._app._sync_dialog_only_selected_scope(dlg)
            dlg._sync_selected_columns_only_scope()
            dlg.refresh_table_data()

        reuse_or_show_modeless_singleton(
            self._app, "_data_analysis_dialog", _factory, on_reused_visible=_on_reused
        )

    def open_plot(self):
        if not self._app.headers:
            return
        dlg = self._app._create_plot_dialog()
        self._app._register_plot_dialog(dlg)
        self._app._sync_dialog_only_selected_scope(dlg)
        self._app._sync_active_plots_from_table_selection()
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()

    def open_sketcher(self, mol=None):
        if mol is not None and (not is_rdkit_mol(mol)):
            mol = None
        from .sketcher import SketcherDialog

        def _on_reuse(dlg):
            if mol is not None:
                dlg.load_structure_from_mol(mol)

        reuse_or_show_modeless_singleton(
            self._app,
            "_sketcher_dialog",
            lambda: SketcherDialog(self._app, initial_mol=mol),
            on_reused_visible=_on_reuse if mol is not None else None,
        )

    def open_molecule_3d(self, mol=None, *, source_oid=None):
        if mol is not None and (not is_rdkit_mol(mol)):
            mol = None
        if mol is None and source_oid is None:
            return
        self._app.open_selection_browser(focus_oid=source_oid, preview_mode="3dmol_3d")

    def open_molecule_2d(self, mol=None, *, source_oid=None):
        if mol is not None and (not is_rdkit_mol(mol)):
            mol = None
        if mol is None and source_oid is None:
            return
        self._app.open_selection_browser(focus_oid=source_oid, preview_mode="3dmol_2d")
