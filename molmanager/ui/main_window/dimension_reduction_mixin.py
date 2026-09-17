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

"""PCA, t-SNE, UMAP, and SOM dialogs (Tools → Dimensionality Reduction)."""

from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QMessageBox


class DimensionReductionMixin:
    def open_pca_dialog(self) -> None:
        self._open_dimension_reduction_dialog("pca")

    def open_tsne_dialog(self) -> None:
        self._open_dimension_reduction_dialog("tsne")

    def open_umap_dialog(self) -> None:
        self._open_dimension_reduction_dialog("umap")

    def open_som_dialog(self) -> None:
        self._open_dimension_reduction_dialog("som")

    def _open_dimension_reduction_dialog(self, kind: str) -> None:
        if not self.headers or self._table_model.rowCount() == 0:
            QMessageBox.information(
                self,
                "Dimensionality Reduction",
                "Open a file or add rows so the table has numeric data to analyze.",
            )
            return
        if kind == "pca":
            from ..dialogs.dimensionality_reduction import PCADialog

            attr = "_pca_dialog"
            factory = lambda: PCADialog(self)
            destroyed = self._on_pca_dialog_destroyed
        elif kind == "tsne":
            from ..dialogs.dimensionality_reduction import TSNEVisualizationDialog

            attr = "_tsne_dialog"
            factory = lambda: TSNEVisualizationDialog(self)
            destroyed = self._on_tsne_dialog_destroyed
        elif kind == "umap":
            from ..dialogs.dimensionality_reduction import UMAPVisualizationDialog

            attr = "_umap_dialog"
            factory = lambda: UMAPVisualizationDialog(self)
            destroyed = self._on_umap_dialog_destroyed
        elif kind == "som":
            from ..dialogs.dimensionality_reduction import SOMVisualizationDialog

            attr = "_som_dialog"
            factory = lambda: SOMVisualizationDialog(self)
            destroyed = self._on_som_dialog_destroyed
        else:
            QMessageBox.warning(
                self, "Dimensionality Reduction", f"Unknown embedding method: {kind!r}"
            )
            return

        dlg = getattr(self, attr, None)
        if dlg is not None:
            try:
                getattr(dlg, "_panel", dlg)._reload_columns()
                self._sync_dialog_only_selected_scope(dlg)
                self._present_dimension_reduction_dialog(dlg)
                return
            except (RuntimeError, AttributeError):
                setattr(self, attr, None)
        d = factory()
        setattr(self, attr, d)
        self._prepare_tool_dialog(d)
        d.setAttribute(Qt.WA_DeleteOnClose, True)
        d.destroyed.connect(destroyed)
        self._present_dimension_reduction_dialog(d)

    def _present_dimension_reduction_dialog(self, dlg) -> None:
        """Show Plot Options until a figure exists; then raise the plot window."""
        panel = getattr(dlg, "_panel", None)
        present = getattr(panel, "present_initial_ui", None)
        if callable(present):
            present()
            return
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()

    def _on_pca_dialog_destroyed(self) -> None:
        self._pca_dialog = None

    def _on_tsne_dialog_destroyed(self) -> None:
        self._tsne_dialog = None

    def _on_umap_dialog_destroyed(self) -> None:
        self._umap_dialog = None

    def _on_som_dialog_destroyed(self) -> None:
        self._som_dialog = None
