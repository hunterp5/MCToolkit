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

from __future__ import annotations

import threading

from molmanager.tool_progress import ToolProgressState, format_tool_progress_text


def test_format_tool_progress_text() -> None:
    assert format_tool_progress_text("Calculate descriptors", 120, 500) == (
        "Calculate descriptors — 120/500 (24%)"
    )
    assert format_tool_progress_text("", 1, 1) == "1/1 (100%)"
    assert format_tool_progress_text("Building table…", -1, -1) == "Building table…"


def test_tool_progress_state_threaded_updates():
    state = ToolProgressState()
    state.begin("Calculate descriptors", 100)
    errors: list[Exception] = []

    def worker() -> None:
        try:
            for i in range(1, 101):
                state.update("Calculate descriptors", i, 100)
        except Exception as exc:
            errors.append(exc)

    t = threading.Thread(target=worker)
    t.start()
    t.join()
    assert not errors
    msg, done, total, active = state.snapshot()
    assert active
    assert done == 100
    assert total == 100
    assert msg == "Calculate descriptors"
    state.end()
    assert state.snapshot()[3] is False
