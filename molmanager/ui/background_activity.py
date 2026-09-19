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

"""Unified signals and helpers for background work (process queue, Render 2D, Gnina, …)."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QObject, Signal

from ..platform_support.tool_progress import format_tool_progress_text


class BackgroundActivityHub(QObject):
    """
    Single ``changed`` signal for anything that should refresh the Processes dialog
    or other observers. Relays ``ProcessQueueManager.snapshot_changed`` and accepts
    explicit ``notify_changed()`` for activity outside the queue (e.g. Render 2D, Gnina).
    """

    changed = Signal()

    def __init__(self, app: Any, parent: QObject | None = None):
        super().__init__(parent or app)
        self._app = app

    def attach(self) -> None:
        pq = getattr(self._app, "process_queue", None)
        if pq is not None:
            pq.snapshot_changed.connect(self.changed.emit)

    def notify_changed(self) -> None:
        self.changed.emit()

    def render2d_batch_active(self) -> bool:
        fn = getattr(self._app, "render2d_batch_active", None)
        return bool(fn()) if callable(fn) else False

    def gnina_dock_active(self) -> bool:
        fn = getattr(self._app, "gnina_dock_active", None) or getattr(
            self._app, "smina_dock_active", None
        )
        return bool(fn()) if callable(fn) else False

    smina_dock_active = gnina_dock_active

    def _render2d_on_process_queue(self, snap: dict[str, Any] | None = None) -> bool:
        """True when Render 2D is the currently running serial queue job."""
        if not self.render2d_batch_active():
            return False
        if snap is None:
            pq = getattr(self._app, "process_queue", None)
            if pq is None:
                return False
            snap = pq.snapshot()
        title = str((snap.get("running") or {}).get("title") or "")
        return "render 2d" in title.lower()

    def current_tool_progress_text(self) -> str:
        """Formatted tool progress, independent of the status-bar label."""
        state = getattr(self._app, "_tool_progress_state", None)
        if state is not None:
            snapshot = getattr(state, "snapshot", None)
            if callable(snapshot):
                message, done, total, active = snapshot()
                if active:
                    return format_tool_progress_text(message, done, total)
        progress = getattr(self._app, "progress", None)
        return str(progress.current_status_text() if progress is not None else "")

    def processes_view_rows(
        self,
    ) -> tuple[list[tuple[str, str, str]], list[dict[str, Any]]]:
        """Table rows for Processes: ``(status, job_id, title)`` and matching row metadata dicts."""
        pq = getattr(self._app, "process_queue", None)
        if pq is None:
            return [], []
        snap = pq.snapshot()
        rows: list[tuple[str, str, str]] = []
        metas: list[dict[str, Any]] = []
        r: dict | None = snap.get("running")
        if r:
            rows.append((r.get("status", ""), r.get("job_id", ""), r.get("title", "")))
            metas.append(
                {
                    "kind": "pq_running",
                    "job_id": r.get("job_id", ""),
                    "cancellable": bool(r.get("cancellable")),
                    "started_at": r.get("started_at"),
                }
            )
        for q in snap.get("queued") or []:
            rows.append((q.get("status", "Queued"), q.get("job_id", ""), q.get("title", "")))
            metas.append(
                {
                    "kind": "pq_queued",
                    "job_id": q.get("job_id", ""),
                    "enqueued_at": q.get("enqueued_at"),
                }
            )
        for fr in snap.get("fast_running") or []:
            rows.append(
                (
                    fr.get("status", "Running"),
                    fr.get("job_id", ""),
                    fr.get("title", "Interactive job"),
                )
            )
            metas.append(
                {
                    "kind": "pq_fast_running",
                    "job_id": fr.get("job_id", ""),
                    "cancellable": bool(fr.get("cancellable", True)),
                    "started_at": fr.get("started_at"),
                }
            )

        if self.render2d_batch_active() and not self._render2d_on_process_queue(snap):
            rows.insert(0, ("Running", "(render-2d)", "Render 2D — drawing structures…"))
            metas.insert(0, {"kind": "render2d"})

        if self.gnina_dock_active():
            rows.insert(0, ("Running", "(gnina)", "Dock — Gnina"))
            metas.insert(0, {"kind": "gnina"})

        for job_id, title in sorted((getattr(self._app, "_background_jobs", None) or {}).items()):
            from .background_jobs import background_job_is_cancellable

            rows.append(("Running", job_id, title))
            metas.append(
                {
                    "kind": "background",
                    "job_id": job_id,
                    "cancellable": background_job_is_cancellable(self._app, job_id),
                }
            )

        progress = self.current_tool_progress_text()
        if progress:
            prefer = next(
                (i for i, meta in enumerate(metas) if meta.get("kind") == "pq_running"),
                None,
            )
            assigned = False
            for i, meta in enumerate(metas):
                kind = meta.get("kind")
                if kind == "pq_queued":
                    meta["progress"] = ""
                    continue
                if prefer is not None:
                    meta["progress"] = progress if i == prefer else ""
                    continue
                if not assigned:
                    meta["progress"] = progress
                    assigned = True
                else:
                    meta["progress"] = ""
        else:
            for meta in metas:
                meta["progress"] = ""

        return rows, metas

    def try_cancel_row(self, meta: dict | None) -> tuple[tuple[str, str] | None, str | None]:
        """
        Attempt cancel/remove for a Processes table row.

        Returns ``(dialog_info, status_text)`` where ``dialog_info`` is ``(title, text)``
        for ``QMessageBox.information`` when the action could not proceed or needs a notice;
        ``status_text`` is set on success for the status bar.
        """
        app = self._app
        pq = getattr(app, "process_queue", None)
        if not meta:
            return (("Cancel", "Select a process in the table first."), None)

        kind = meta.get("kind")
        if kind == "render2d":
            cancel = getattr(app, "cancel_render_2d_batch", None)
            if callable(cancel) and cancel():
                return (None, "Render 2D cancelled.")
            return (("Cancel", "Render 2D is not active."), None)

        if kind in {"gnina", "smina"}:
            cancel = getattr(app, "cancel_gnina_dock", None) or getattr(
                app, "cancel_smina_dock", None
            )
            if callable(cancel) and cancel():
                return (None, "Gnina stopped.")
            return (("Cancel", "Gnina is not running."), None)

        if kind == "pq_running":
            if self.render2d_batch_active() and self._render2d_on_process_queue():
                cancel = getattr(app, "cancel_render_2d_batch", None)
                if callable(cancel) and cancel():
                    return (None, "Render 2D cancelled.")
                return (("Cancel", "Render 2D is not active."), None)
            run = pq.snapshot().get("running") if pq else None
            if not run or run.get("job_id") != meta.get("job_id"):
                return (("Cancel", "That job is no longer running."), None)
            if pq and pq.cancel_running():
                return (None, "Cancelling…")
            return (
                (
                    "Cancel",
                    "This job cannot be cancelled cooperatively, or a cancel was already requested.",
                ),
                None,
            )

        if kind == "pq_queued":
            jid = meta.get("job_id") or ""
            if pq and pq.remove_queued_job(jid):
                return (None, f"Removed queued job ({jid}).")
            return (("Cancel", "That job is no longer in the queue."), None)

        if kind == "pq_fast_running":
            jid = meta.get("job_id") or ""
            if pq and pq.cancel_fast_job(jid):
                return (None, "Cancelling interactive job…")
            return (("Cancel", "That interactive job is no longer running."), None)

        if kind == "background":
            from .background_jobs import background_job_is_cancellable, cancel_background_job

            jid = str(meta.get("job_id") or "")
            if not jid:
                return (("Cancel", "Select a process in the table first."), None)
            if not background_job_is_cancellable(app, jid):
                return (("Cancel", "This background job cannot be cancelled."), None)
            if cancel_background_job(app, jid):
                return (None, "Cancelling…")
            return (("Cancel", "This background job cannot be cancelled."), None)

        return (("Cancel", "Unknown row type."), None)

    def clear_queued_jobs(self) -> int:
        pq = getattr(self._app, "process_queue", None)
        return pq.clear_queued() if pq is not None else 0

    def prepare_for_quit(self) -> None:
        """Cooperatively stop background jobs before draining thread pools (window close)."""
        app = self._app
        if hasattr(app, "_invalidate_substructure_async_jobs"):
            app._invalidate_substructure_async_jobs()
        if hasattr(app, "cancel_render_2d_batch"):
            app.cancel_render_2d_batch()
        if hasattr(app, "cancel_gnina_dock"):
            app.cancel_gnina_dock()
        elif hasattr(app, "cancel_smina_dock"):
            app.cancel_smina_dock()
        from .background_jobs import cancel_background_job

        for job_id in list((getattr(app, "_background_job_cancels", None) or {}).keys()):
            cancel_background_job(app, job_id)
        pq = getattr(app, "process_queue", None)
        if pq is not None:
            shutdown = getattr(pq, "shutdown_for_exit", None)
            if callable(shutdown):
                shutdown()
            else:
                pq.clear_queued()
                pq.cancel_running()
