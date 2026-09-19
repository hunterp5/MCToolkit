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

"""Cluster dialog and cluster worker signal handlers."""

from __future__ import annotations

from contextlib import suppress

from PySide6.QtCore import Qt

from .analysis_job_support import ensure_table_ready_for_tool, report_cancellable_job_failure
from .singleton_modeless_dialog import reuse_or_show_modeless_singleton


class ClusterTools:
    def __init__(self, app) -> None:
        self._app = app

    def open_cluster_dialog(self) -> None:
        if not ensure_table_ready_for_tool(self._app, "Cluster"):
            return
        from .dialogs import ClusterDialog

        def _factory():
            d = ClusterDialog(self._app)
            self._app._prepare_tool_dialog(d)
            d.setAttribute(Qt.WA_DeleteOnClose, True)
            return d

        def _on_reused(dlg) -> None:
            dlg._refresh_structure_sources()
            self._app._sync_dialog_only_selected_scope(dlg)

        reuse_or_show_modeless_singleton(
            self._app,
            "_cluster_dialog",
            _factory,
            on_reused_visible=_on_reused,
        )

    def on_cluster_failed(self, message: str) -> None:
        def _reenable_run() -> None:
            dlg = getattr(self._app, "_cluster_dialog", None)
            if dlg is not None:
                with suppress(RuntimeError):
                    dlg.enable_run_after_job()

        report_cancellable_job_failure(
            self._app,
            "Cluster",
            message,
            progress_label="Clustering",
            failure_fallback="Clustering failed.",
            after_finish=_reenable_run,
        )

    def on_cluster_explore_finished(self, results: list) -> None:
        self._app._finish_tool_progress("Exploring clusters")
        self._app.status_label.setText("Ready.")
        dlg = getattr(self._app, "_cluster_dialog", None)
        if dlg is not None:
            with suppress(RuntimeError):
                dlg.fill_explore_results(results)
