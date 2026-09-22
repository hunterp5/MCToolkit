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

from __future__ import annotations

from types import SimpleNamespace

from PySide6.QtCore import QObject

from mctoolkit.platform_support.tool_progress import ToolProgressState
from mctoolkit.ui.progress_controller import ProgressController


def test_resolve_progress_job_id_prefers_label_match(qapp) -> None:  # noqa: ARG001
    state = ToolProgressState()
    state.begin("Protonate", 10, job_id="prot")
    state.begin("Calculate descriptors", 50, job_id="desc")

    class Host(QObject):
        def __init__(self) -> None:
            super().__init__()
            self.status_label = SimpleNamespace(setText=lambda *_a, **_k: None)
            self.background_activity = None
            self._tool_progress_state = state
            self._loading_detail = None
            self._export_busy = False
            self.process_queue = SimpleNamespace(snapshot=lambda: {})

        def _workspace_loading_overlay_visible(self) -> bool:
            return False

        def _session_overlay_owns_loading_detail(self) -> bool:
            return False

        def _status_work_is_active(self) -> bool:
            return False

    ctrl = ProgressController(Host())
    assert ctrl._resolve_progress_job_id(None, message="Protonate") == "prot"
    assert ctrl._resolve_progress_job_id(None, message="Calculate descriptors") == "desc"
    # Label mismatch must not steal another active slot.
    assert ctrl._resolve_progress_job_id(None, message="Writing results") is None
