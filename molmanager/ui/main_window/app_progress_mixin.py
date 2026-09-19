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

"""Status chrome and tool-progress UI for ChemistryWorkspaceWindow."""

from __future__ import annotations

import logging
from contextlib import suppress

from PyQt5.QtCore import QTimer

from ...platform_support.config import load_config
from ...platform_support.memory_usage import format_process_memory_status
from ...platform_support.tool_progress import format_tool_progress_text
from ..strings import STATUS_READY

logger = logging.getLogger(__name__)


class AppProgressMixin:
    def _workspace_loading_overlay_visible(self) -> bool:
        """True while file/session load is covering the workspace."""
        if bool(getattr(self, "_ingest_loading", False)):
            return True
        stack = getattr(self, "_table_stack", None)
        try:
            return stack is not None and int(stack.currentIndex()) == 0
        except RuntimeError:
            return False

    def _session_overlay_owns_loading_detail(self) -> bool:
        """True while session restore is writing the loading page (not tool progress)."""
        if getattr(self, "_session_waiting_for_render", False):
            return False
        if getattr(self, "_session_awaiting_ready", False):
            return True
        if getattr(self, "_session_finalize_ctx", None) is not None:
            return True
        if getattr(self, "_session_restore_ctx", None) is not None:
            return True
        if getattr(self, "_csv_session_ctx", None) is not None:
            return True
        return False

    def _sync_status_chrome_for_workspace(self) -> None:
        """Hide status/memory on the loading page; restore the user's status-bar setting after."""
        apply_bar = getattr(self, "_apply_status_bar_visible", None)
        if not callable(apply_bar):
            return
        act = getattr(self, "_act_status_bar", None)
        if act is not None:
            want = bool(act.isChecked())
        else:
            from ..theme import load_status_bar_visible

            want = bool(load_status_bar_visible())
        apply_bar(want, persist=False)

    def _set_workspace_stack_index(self, index: int) -> None:
        stack = getattr(self, "_table_stack", None)
        if stack is None:
            return
        stack.setCurrentIndex(int(index))
        self._sync_status_chrome_for_workspace()

    def _status_memory_should_poll(self) -> bool:
        """True unless the status-bar host was explicitly hidden.

        ``isVisible()`` is False until the top-level window is shown, so it
        cannot be used during ``__init__`` to decide whether polling starts.
        """
        if self._workspace_loading_overlay_visible():
            return False
        host = getattr(self, "_status_host", None)
        return host is None or not host.isHidden()

    def _init_status_memory_tracker(self, cfg) -> None:
        self._memory_status_timer = QTimer(self)
        self._memory_status_timer.timeout.connect(self._refresh_status_memory_label)
        label = getattr(self, "_memory_status_label", None)
        if cfg.status_memory_enabled:
            if label is not None:
                label.show()
            self._memory_status_timer.setInterval(int(cfg.status_memory_poll_ms))
            if self._status_memory_should_poll():
                self._memory_status_timer.start()
            self._refresh_status_memory_label()
        elif label is not None:
            label.hide()

    def _refresh_status_memory_label(self) -> None:
        label = getattr(self, "_memory_status_label", None)
        if label is None or label.isHidden():
            return
        text = format_process_memory_status()
        if text is None:
            label.setText("")
            label.setToolTip("Process memory unavailable on this platform.")
            return
        label.setText(text)

    def _begin_tool_progress(self, message: str, total: int) -> None:
        """Start polled status updates for a long-running queued tool."""
        total_i = max(1, int(total))
        self._tool_progress_active_label = str(message or "")
        self._tool_progress_state.begin(message, total_i)
        self._on_tool_progress(message, 0, total_i)
        if not self._tool_progress_poll_timer.isActive():
            self._tool_progress_poll_timer.start()

    def _poll_tool_progress_state(self) -> None:
        message, done, total, active = self._tool_progress_state.snapshot()
        if not active:
            self._tool_progress_poll_timer.stop()
            return
        self._on_tool_progress(message, done, total)

    def _background_job_ui_active(self) -> bool:
        return int(getattr(self, "_background_job_ui_depth", 0)) > 0

    def _status_work_is_active(self) -> bool:
        """True when the status line should keep showing in-progress work."""
        if bool(getattr(self, "_ingest_loading", False)):
            return True
        if bool(getattr(self, "_export_busy", False)):
            return True
        render2d_active = getattr(self, "render2d_batch_active", None)
        if callable(render2d_active) and render2d_active():
            return True
        if self._background_job_ui_active():
            return True
        state = getattr(self, "_tool_progress_state", None)
        if state is not None:
            _msg, _done, _total, active = state.snapshot()
            if active:
                return True
        jobs = getattr(self, "_background_jobs", None)
        return bool(jobs)

    def _restore_idle_status(self) -> None:
        """Set the status line to Ready when nothing else is running."""
        if self._status_work_is_active():
            return
        label = getattr(self, "status_label", None)
        if label is None:
            return
        try:
            if label.text() != STATUS_READY:
                label.setText(STATUS_READY)
        except RuntimeError:
            pass

    def _enter_background_job_ui(self) -> None:
        """Reduce main-thread churn while a queued tool holds the machine busy."""
        self._background_job_ui_depth = int(getattr(self, "_background_job_ui_depth", 0)) + 1
        if self._background_job_ui_depth != 1:
            return
        cfg = load_config()
        self._tool_progress_poll_timer.setInterval(int(cfg.background_job_poll_ms))

    def _exit_background_job_ui(self) -> None:
        self._background_job_ui_depth = max(
            0, int(getattr(self, "_background_job_ui_depth", 0)) - 1
        )
        if self._background_job_ui_depth != 0:
            return
        ms = int(getattr(self, "_tool_progress_poll_interval_ms", 200))
        self._tool_progress_poll_timer.setInterval(ms)

    def _finish_tool_progress(
        self,
        message: str | None = None,
        *,
        status_message: str | None = STATUS_READY,
    ) -> None:
        """Show 100% once, then stop polling and optionally reset the status line."""
        msg, done, total, active = self._tool_progress_state.snapshot()
        stored = getattr(self, "_tool_progress_active_label", "") or ""
        final_msg = message or msg or stored
        if total > 0 and (active or done < total):
            self._on_tool_progress(final_msg, total, total)
        self._tool_progress_state.end()
        self._tool_progress_active_label = ""
        self._tool_progress_poll_timer.stop()
        if status_message is not None:
            self.status_label.setText(status_message)

    def _on_export_finished_message(self, message: str) -> None:
        self._export_busy = False
        self._clear_tool_progress(status_message=None)
        self.status_label.setText(message)

    def _on_tool_progress(self, message: str, done: int, total: int) -> None:
        if message:
            if total < 0:
                self._tool_progress_state.update(message, 0, -1)
            else:
                self._tool_progress_state.update(message, done, total)
        text = format_tool_progress_text(message, done, total)
        if text and text == getattr(self, "_last_tool_progress_status", ""):
            return
        self._last_tool_progress_status = text
        if text:
            self.status_label.setText(text)
        if (
            text
            and self._workspace_loading_overlay_visible()
            and not self._session_overlay_owns_loading_detail()
        ):
            detail = getattr(self, "_loading_detail", None)
            if detail is not None:
                with suppress(RuntimeError):
                    detail.setText(text)
        hub = getattr(self, "background_activity", None)
        if hub is not None:
            hub.notify_changed()

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

    def _clear_tool_progress(self, *, status_message: str | None = STATUS_READY) -> None:
        """Stop polled tool progress; reset status line unless ``status_message`` is ``None``."""
        self._tool_progress_state.end()
        self._tool_progress_active_label = ""
        self._last_tool_progress_status = ""
        if self._tool_progress_poll_timer.isActive():
            self._tool_progress_poll_timer.stop()
        if status_message is not None:
            self.status_label.setText(status_message)
        hub = getattr(self, "background_activity", None)
        if hub is not None:
            hub.notify_changed()
