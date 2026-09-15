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

"""Dimred Plot Options open before the empty plot window."""

from molmanager.ui.dialogs.dimensionality_reduction import PCADialog


def test_present_initial_ui_opens_options_not_plot(qapp):
    dlg = PCADialog(None)
    try:
        panel = dlg._panel
        panel.present_initial_ui()
        qapp.processEvents()
        assert not dlg.isVisible()
        assert panel._opts_dialog.isVisible()
        assert panel._opts_dialog.windowTitle() == "Principal Component Analysis — Plot Options"
    finally:
        panel._opts_dialog.hide()
        dlg.close()
        dlg.deleteLater()
        qapp.processEvents()


def test_present_initial_ui_shows_plot_when_result_exists(qapp):
    dlg = PCADialog(None)
    try:
        panel = dlg._panel
        panel._last_result = object()
        panel.present_initial_ui()
        qapp.processEvents()
        assert dlg.isVisible()
        assert not panel._opts_dialog.isVisible()
    finally:
        dlg.close()
        dlg.deleteLater()
        qapp.processEvents()


def test_reveal_plot_window_hides_options(qapp):
    dlg = PCADialog(None)
    try:
        panel = dlg._panel
        panel.present_initial_ui()
        qapp.processEvents()
        panel._last_result = object()
        panel.reveal_plot_window()
        qapp.processEvents()
        assert dlg.isVisible()
        assert not panel._opts_dialog.isVisible()
    finally:
        dlg.close()
        dlg.deleteLater()
        qapp.processEvents()
