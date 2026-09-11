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

"""Pytest fixtures for molmanager (Qt offscreen for headless CI)."""

from __future__ import annotations

import os

import pytest


@pytest.fixture(autouse=True)
def _reset_worker_global_state() -> None:
    """Avoid cross-test pollution of process-pool shutdown (pKa / Uni-pKa workers)."""
    from molmanager.workers import process_pool_utils as ppu

    ppu._SHUTDOWN.clear()
    yield
    ppu._SHUTDOWN.clear()


@pytest.fixture(scope="session")
def qapp():
    """Single QApplication for the test session."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt5.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app
