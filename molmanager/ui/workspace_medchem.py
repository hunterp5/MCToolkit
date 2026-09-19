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

"""BOILED-Egg and golden-triangle plots (Data menu)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox

from .singleton_modeless_dialog import reuse_or_show_modeless_singleton


class MedChemSpaceTools:
    def __init__(self, app) -> None:
        self._app = app

    def open_boiled_egg_plot(self) -> None:
        self._open_medchem_space_dialog(
            plot_kind="boiled_egg",
            title="BOILED-Egg plot",
            attr="_boiled_egg_dialog",
        )

    def open_golden_triangle_plot(self) -> None:
        self._open_medchem_space_dialog(
            plot_kind="golden_triangle",
            title="Golden Triangle plot",
            attr="_golden_triangle_dialog",
        )

    def _open_medchem_space_dialog(
        self,
        *,
        plot_kind: str,
        title: str,
        attr: str,
    ) -> None:
        if not self._app.headers or self._app._table_model.rowCount() == 0:
            QMessageBox.information(
                self._app,
                "Data",
                "Open a file or add rows with structures to plot medicinal chemistry space.",
            )
            return
        from .dialogs.medchem_space import MedChemSpaceDialog

        def _factory():
            d = MedChemSpaceDialog(self._app, plot_kind=plot_kind, window_title=title)
            self._app._prepare_tool_dialog(d)
            d.setAttribute(Qt.WA_DeleteOnClose, True)
            return d

        dlg = reuse_or_show_modeless_singleton(
            self._app,
            attr,
            _factory,
            on_reused_visible=self._app._sync_dialog_only_selected_scope,
        )
        dlg.raise_()
        dlg.activateWindow()
