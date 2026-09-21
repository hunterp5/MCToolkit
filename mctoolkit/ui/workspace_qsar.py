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

"""QSAR tool window (Data menu)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox


class QsarTools:
    def __init__(self, app) -> None:
        self._app = app

    def open_qsar_dialog(self) -> None:
        if not self._app.headers or self._app._table_model.rowCount() == 0:
            QMessageBox.information(
                self._app,
                "QSAR",
                "Open a file or add rows with activity and descriptor data first.",
            )
            return
        from .dialogs.qsar import QSARDialog
        from .singleton_modeless_dialog import reuse_or_show_modeless_singleton

        def _factory():
            d = QSARDialog(self._app)
            self._app._prepare_tool_dialog(d)
            d.setAttribute(Qt.WA_DeleteOnClose, True)
            return d

        reuse_or_show_modeless_singleton(
            self._app,
            "_qsar_dialog",
            _factory,
            on_reused_visible=lambda dlg: self._app._sync_dialog_only_selected_scope(dlg),
        )
