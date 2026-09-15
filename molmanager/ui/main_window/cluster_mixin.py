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

"""Cluster dialog and cluster worker signal handlers (kept out of :class:`ChemistryMixin`)."""

from __future__ import annotations

from PyQt5.QtCore import Qt

from ..analysis_job_support import ensure_table_ready_for_tool, report_cancellable_job_failure


class ClusterMixin:
    def open_cluster_dialog(self) -> None:
        if not ensure_table_ready_for_tool(self, "Cluster"):
            return
        from ..dialogs import ClusterDialog

        dlg = getattr(self, "_cluster_dialog", None)
        if dlg is not None:
            try:
                dlg._refresh_structure_sources()
                self._sync_dialog_only_selected_scope(dlg)
                dlg.show()
                dlg.raise_()
                dlg.activateWindow()
                return
            except RuntimeError:
                self._cluster_dialog = None
        d = ClusterDialog(self)
        self._cluster_dialog = d
        self._prepare_tool_dialog(d)
        d.setAttribute(Qt.WA_DeleteOnClose, True)
        d.destroyed.connect(self._on_cluster_dialog_destroyed)
        d.show()
        d.raise_()
        d.activateWindow()

    def _on_cluster_dialog_destroyed(self) -> None:
        self._cluster_dialog = None

    def on_cluster_failed(self, message: str) -> None:
        def _reenable_run() -> None:
            dlg = getattr(self, "_cluster_dialog", None)
            if dlg is not None:
                try:
                    dlg.enable_run_after_job()
                except RuntimeError:
                    pass

        report_cancellable_job_failure(
            self,
            "Cluster",
            message,
            progress_label="Clustering",
            failure_fallback="Clustering failed.",
            after_finish=_reenable_run,
        )

    def on_cluster_explore_finished(self, results: list) -> None:
        self._finish_tool_progress("Exploring clusters")
        self.status_label.setText("Ready.")
        dlg = getattr(self, "_cluster_dialog", None)
        if dlg is not None:
            try:
                dlg.fill_explore_results(results)
            except RuntimeError:
                pass
