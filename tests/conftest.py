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

"""Pytest fixtures for MCToolkit (Qt offscreen for headless CI)."""

from __future__ import annotations

import os

import pytest


@pytest.fixture(autouse=True)
def _reset_worker_global_state() -> None:
    """Avoid cross-test pollution of process-pool shutdown (pKa / Uni-pKa workers)."""
    from mctoolkit.workers import process_pool_utils as ppu

    ppu._SHUTDOWN.clear()
    yield
    ppu._SHUTDOWN.clear()


@pytest.fixture(autouse=True)
def _destroy_leftover_widgets() -> None:
    """Destroy the widgets a test leaves behind, while no Qt code is on the stack.

    A window graph is cyclic — collaborators hold the window, signal connections hold bound
    methods — so closing a window frees nothing and the cycle collector ends up owning a live Qt
    tree. It then frees that tree at whatever allocation trips its threshold, which has meant
    inside another widget's constructor. Leaked windows are also not passive: ``setFont`` and
    friends walk every live widget, so one half-destroyed leftover corrupts an unrelated test.
    """
    yield
    import shiboken6
    from PySide6.QtCore import QEvent
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        return
    # Do not drain with processEvents first: PySide6 can native-crash in queued slots
    # that outlive a closing window. deleteLater + DeferredDelete is enough to drop
    # leftover top-levels before the next test constructs widgets.
    for widget in list(app.topLevelWidgets()):
        if not shiboken6.isValid(widget):
            continue
        for attr in (
            "_suppress_exit_session_prompt",
            "_dock_results_force_close",
            "_suppress_close_prompt",
        ):
            if hasattr(widget, attr):
                setattr(widget, attr, True)
        widget.deleteLater()
    QApplication.sendPostedEvents(None, QEvent.DeferredDelete)


@pytest.fixture(scope="session")
def qapp():
    """Single QApplication for the test session."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app
