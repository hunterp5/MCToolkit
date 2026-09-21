# This file is part of mctoolkit.
# Copyright (C) 2026 Hunter Picard
#
# mctoolkit is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# mctoolkit is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with mctoolkit. If not, see <https://www.gnu.org/licenses/>.

"""Floating Plotter must be an owned top-level window, not a child covering the table."""

from __future__ import annotations

from PySide6.QtCore import Qt

from mctoolkit.ui.main_window import ChemistryWorkspaceWindow
from mctoolkit.ui.plot_dialog import PlotDialog


def test_plot_dialog_is_owned_top_level_window(qapp):  # noqa: ARG001
    host = ChemistryWorkspaceWindow()
    dlg = PlotDialog(host)
    try:
        assert dlg.parentWidget() is host
        assert dlg.windowFlags() & Qt.Window
        assert dlg.isWindow()
        assert dlg._plot_widget.parentWidget() is dlg
        assert not (dlg.windowFlags() & Qt.WindowStaysOnTopHint)
    finally:
        dlg.close()
        dlg.deleteLater()
        host.close()
        host.deleteLater()
