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

"""Tool-progress owner for the main window.

The polled progress state machine lives here and owns its timer, depth counter, and the
last text it wrote. Status-bar chrome (stack overlay, memory label, visibility) lives on
the window via ``AppLifecycleMixin``.
"""

from __future__ import annotations

from contextlib import suppress
from typing import Any, Protocol

from PySide6.QtCore import QTimer

from ..platform_support.config import load_config
from ..platform_support.tool_progress import format_tool_progress_text
from .strings import STATUS_READY


class ProgressHost(Protocol):
    """What the progress state machine needs from the window's status chrome."""

    status_label: Any
    background_activity: Any
    _tool_progress_state: Any
    _loading_detail: Any
    _export_busy: bool

    def _workspace_loading_overlay_visible(self) -> bool: ...
    def _session_overlay_owns_loading_detail(self) -> bool: ...
    def _status_work_is_active(self) -> bool: ...


class ProgressController:
    """Owns the polled tool-progress state machine and the text it puts on the status line."""

    def __init__(self, app: ProgressHost) -> None:
        self._app = app
        self._active_label = ""
        self._last_status_text = ""
        self._background_job_ui_depth = 0
        self._partial_results_notice: str | None = None
        self._poll_interval_ms = int(load_config().tool_progress_poll_ms)
        self._poll_timer = QTimer(app)
        self._poll_timer.setInterval(self._poll_interval_ms)
        self._poll_timer.timeout.connect(self._poll_tool_progress_state)

    def current_status_text(self) -> str:
        """Last text written to the status line, for the background-activity hub."""
        return self._last_status_text

    def has_partial_results_notice(self) -> bool:
        return bool(self._partial_results_notice)

    def _begin_tool_progress(self, message: str, total: int) -> None:
        """Start polled status updates for a long-running queued tool."""
        total_i = max(1, int(total))
        self._active_label = str(message or "")
        self._app._tool_progress_state.begin(message, total_i)
        self._on_tool_progress(message, 0, total_i)
        if not self._poll_timer.isActive():
            self._poll_timer.start()

    def _poll_tool_progress_state(self) -> None:
        message, done, total, active = self._app._tool_progress_state.snapshot()
        if not active:
            self._poll_timer.stop()
            return
        self._on_tool_progress(message, done, total)

    def _background_job_ui_active(self) -> bool:
        return self._background_job_ui_depth > 0

    def _enter_background_job_ui(self) -> None:
        """Reduce main-thread churn while a queued tool holds the machine busy."""
        self._background_job_ui_depth += 1
        if self._background_job_ui_depth != 1:
            return
        self._poll_timer.setInterval(int(load_config().background_job_poll_ms))

    def _exit_background_job_ui(self) -> None:
        self._background_job_ui_depth = max(0, self._background_job_ui_depth - 1)
        if self._background_job_ui_depth != 0:
            return
        self._poll_timer.setInterval(self._poll_interval_ms)

    def _restore_idle_status(self) -> None:
        """Set the status line to Ready when nothing else is running."""
        if self._app._status_work_is_active():
            return
        label = self._app.status_label
        if label is None:
            return
        try:
            if label.text() != STATUS_READY:
                label.setText(STATUS_READY)
        except RuntimeError:
            pass

    def _finish_tool_progress(
        self,
        message: str | None = None,
        *,
        status_message: str | None = STATUS_READY,
    ) -> None:
        """Show 100% once, then stop polling and optionally reset the status line."""
        msg, done, total, active = self._app._tool_progress_state.snapshot()
        final_msg = message or msg or self._active_label
        if total > 0 and (active or done < total):
            self._on_tool_progress(final_msg, total, total)
        self._app._tool_progress_state.end()
        self._active_label = ""
        self._poll_timer.stop()
        if status_message is not None:
            self._app.status_label.setText(status_message)

    def _clear_tool_progress(self, *, status_message: str | None = STATUS_READY) -> None:
        """Stop polled tool progress; reset status line unless ``status_message`` is ``None``."""
        self._app._tool_progress_state.end()
        self._active_label = ""
        self._last_status_text = ""
        if self._poll_timer.isActive():
            self._poll_timer.stop()
        if status_message is not None:
            self._app.status_label.setText(status_message)
        self._notify_activity_hub()

    def _on_export_finished_message(self, message: str) -> None:
        self._app._export_busy = False
        self._clear_tool_progress(status_message=None)
        self._app.status_label.setText(message)

    def _on_tool_progress(self, message: str, done: int, total: int) -> None:
        state = self._app._tool_progress_state
        if message:
            if total < 0:
                state.update(message, 0, -1)
            else:
                state.update(message, done, total)
        text = format_tool_progress_text(message, done, total)
        if text and text == self._last_status_text:
            return
        self._last_status_text = text
        if text:
            self._app.status_label.setText(text)
        if (
            text
            and self._app._workspace_loading_overlay_visible()
            and not self._app._session_overlay_owns_loading_detail()
        ):
            detail = self._app._loading_detail
            if detail is not None:
                with suppress(RuntimeError):
                    detail.setText(text)
        self._notify_activity_hub()

    def _on_partial_results_notice(self, tool_label: str, done: int, total: int) -> None:
        d = max(0, int(done))
        t = max(1, int(total))
        self._partial_results_notice = (
            f"Cancelled — applied partial results for {tool_label} ({d}/{t})."
        )

    def _consume_partial_results_notice(self) -> str | None:
        note = self._partial_results_notice
        self._partial_results_notice = None
        return note

    def _notify_activity_hub(self) -> None:
        hub = self._app.background_activity
        if hub is not None:
            hub.notify_changed()
