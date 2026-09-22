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

"""Session log pane, status-label mirroring, and Log toolbar chrome."""

from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QMainWindow

from molmanager.platform_support.session_log import record_ui_log, session_log_buffer
from molmanager.ui.app_log_dialog import SessionLogPanel, StatusLogLabel
from molmanager.ui.main_window.app_menu_mixin import AppMenuMixin
from molmanager.ui.processes_dialog import ProcessesDialog


def test_session_log_panel_shows_ui_and_status_lines(qapp):  # noqa: ARG001
    session_log_buffer().clear()
    record_ui_log("Starting pdb2pqr", name="molmanager.ui.tools")
    label = StatusLogLabel("Ready")
    label.setText("Ready")
    label.setText("Descriptors: collecting… — 0/8 (0%)")
    label.setText("Descriptors: collecting… — 4/8 (50%)")
    label.setText("Descriptors: collecting… — 8/8 (100%)")
    label.setText("Ready")

    panel = SessionLogPanel()
    text = panel._view.toPlainText()
    assert "Starting pdb2pqr" in text
    assert "0/8 (0%)" in text
    assert "4/8 (50%)" in text
    assert "100%)" in text
    panel._search.setText("pdb2pqr")
    filtered = panel._view.toPlainText()
    assert "Starting pdb2pqr" in filtered
    assert "0/8" not in filtered
    panel.close()


def test_status_log_label_skips_ready(qapp):  # noqa: ARG001
    session_log_buffer().clear()
    label = StatusLogLabel("Ready")
    label.setText("Ready")
    entries, _seq, _gen = session_log_buffer().snapshot()
    assert entries == []
    label.setText("Layout: split horizontal.")
    entries, _seq, _gen = session_log_buffer().snapshot()
    assert [e.message for e in entries] == ["Layout: split horizontal."]
    assert entries[0].source == "status"


class _CornerHost(QMainWindow, AppMenuMixin):
    def open_workspace_layout_picker(self) -> None:
        return None

    def open_processes_dialog(self) -> None:
        return None


def test_corner_chrome_is_layout_and_log(qapp):  # noqa: ARG001
    w = _CornerHost()
    w._install_menubar_corner(w.menuBar())
    corner = w.menuBar().cornerWidget(Qt.TopRightCorner)
    ly = corner.layout()
    widgets = [ly.itemAt(i).widget() for i in range(ly.count())]
    assert widgets == [w._btn_workspace_layout, w._btn_processes]
    assert w._btn_processes.text() == "Log"
    assert getattr(w, "_btn_app_log", None) is None
    w.close()


def test_log_stays_enabled_during_ingest(qapp):  # noqa: ARG001
    w = _CornerHost()
    w._install_menubar_corner(w.menuBar())
    w._ingest_loading = True
    w._sync_main_toolbar_for_table_ready()
    assert not w._btn_workspace_layout.isEnabled()
    assert w._btn_processes.isEnabled()
    w._ingest_loading = False
    w._sync_main_toolbar_for_table_ready()
    assert w._btn_processes.isEnabled()
    w.close()


def test_processes_dialog_embeds_session_log(qapp):  # noqa: ARG001
    session_log_buffer().clear()
    record_ui_log("Starting pdb2pqr", name="molmanager.ui.tools")
    dlg = ProcessesDialog()
    assert dlg.windowTitle() == "Log"
    assert dlg._log is not None
    assert "Starting pdb2pqr" in dlg._log._view.toPlainText()
    splitter = dlg.layout().itemAt(0).widget()
    assert splitter.widget(0) is not dlg._log
    assert splitter.widget(1) is dlg._log
    footer = dlg.layout().itemAt(1).layout()
    footer_widgets = [
        footer.itemAt(i).widget()
        for i in range(footer.count())
        if footer.itemAt(i).widget() is not None
    ]
    assert footer_widgets == [dlg._btn_cancel, dlg._btn_clear, dlg._log.filter_bar()]
    assert dlg._btn_cancel.text() == "Cancel Job"
    assert dlg._btn_clear.text() == "Clear Queue"
    assert dlg._log.filter_bar().parent() is not dlg._log
    assert not hasattr(dlg, "_btn_refresh")
    assert not hasattr(dlg._log, "_btn_copy")
    dlg.close()
