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
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with MCToolkit. If not, see <https://www.gnu.org/licenses/>.

"""Structure column width, depict size, and zoom layout."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap

from ..table.structure_depiction_layout import (
    STRUCTURE_COLUMN_HORIZONTAL_PADDING,
    structure_column_minimum_width,
    structure_depict_height,
    structure_depict_width,
    structure_row_default_height,
)
from .compound_table_model import CompoundTableModel


class TableBuildLayout:
    def _view_row_to_source_row(self, view_row: int) -> int:
        """Map a table view row index to the source ``CompoundTableModel`` row."""
        proxy = getattr(self._app, "_filter_proxy_model", None)
        if proxy is not None:
            src = proxy.mapToSource(proxy.index(int(view_row), 0))
            if src.isValid():
                return int(src.row())
        return int(view_row)

    def apply_structure_table_layout(self) -> None:
        """Sync Structure column row/column chrome to the current depiction size."""
        if not hasattr(self._app, "table") or self._app.table is None:
            return
        row_h = structure_row_default_height()
        col = CompoundTableModel.STRUCTURE_COL
        vh = self._app.table.verticalHeader()
        if vh is not None:
            vh.setDefaultSectionSize(row_h)
        zoomed = bool(getattr(self._app, "zoomed_ids", None))
        min_col = structure_column_minimum_width(zoomed=zoomed)
        self._app.table.set_structure_column_minimum_width(min_col)
        if int(self._app.table.columnWidth(col)) < min_col:
            self._app.table.setColumnWidth(col, min_col)
        if hasattr(self._app, "_table_model") and self._app._table_model is not None:
            self._app._table_model.notify_structure_column_changed()
        self._app.table.viewport().update()

    def apply_structure_depict_size(self, width: int, height: int, *, persist: bool = True) -> None:
        """Apply depiction size from Settings and optionally re-render the Structure column."""
        from ..table.structure_depiction_layout import set_structure_depict_size

        set_structure_depict_size(width, height, persist=persist)
        self.apply_structure_table_layout()
        if persist:
            self.rerender_structure_column_for_new_size()

    def rerender_structure_column_for_new_size(self) -> None:
        """Re-draw Structure cells after depiction size changed in Settings."""
        if not hasattr(self._app, "_table_model") or self._app._table_model.rowCount() <= 0:
            if hasattr(self._app, "_table_model") and self._app._table_model is not None:
                self._app._table_model.notify_structure_column_changed()
            return
        if (
            getattr(self._app, "_render2d_batch_active", False)
            or self._app.process_queue.has_running_job()
        ):
            if hasattr(self._app, "status_label"):
                self._app.status_label.setText(
                    "2D render size saved. Re-draw structures when the current job finishes."
                )
            return
        self._app.zoomed_ids.clear()
        w, h = structure_depict_width(), structure_depict_height()
        renders, row_by_oid = self._build_render2d_tasks_in_table_order("Structure", w, h, None)
        self._app._table_model.clear_structure_png_store()
        if not renders:
            self._app._table_model.notify_structure_column_changed()
            return
        self._start_render_2d_batch(
            renders,
            row_by_oid,
            "Structure",
            column_pixmap_mode=False,
            queue_title_prefix="structure resize ",
        )

    def _sync_structure_column_width_for_zoom_state(self) -> None:
        """Set Structure column width from zoom state (O(1), no full-table scan)."""
        zoomed = bool(getattr(self._app, "zoomed_ids", None))
        need = structure_column_minimum_width(zoomed=zoomed)
        self._app.table.set_structure_column_minimum_width(need)
        col = CompoundTableModel.STRUCTURE_COL
        if int(self._app.table.columnWidth(col)) != need:
            self._app.table.setColumnWidth(col, need)

    def _normal_structure_pixmap_for_oid(self, oid: int) -> QPixmap | None:
        """Best-effort 1× depiction: PNG store, else scale down the in-memory pixmap."""
        store = self._app._table_model._structure_png_store
        if store is not None and store.has_png(oid):
            pm = store.pixmap(oid)
            if pm is not None and not pm.isNull():
                return pm
        current = self._app._table_model.structure_pixmap_for_oid(oid)
        if current is None or current.isNull():
            return None
        w, h = structure_depict_width(), structure_depict_height()
        if current.width() <= w and current.height() <= h:
            return current
        return current.scaled(w, h, Qt.KeepAspectRatio, Qt.SmoothTransformation)

    def _try_restore_structure_zoom_out(self, oid: int, view_row: int) -> bool:
        """Restore normal-size structure depiction without re-rendering when possible."""
        pm = self._normal_structure_pixmap_for_oid(oid)
        if pm is None or pm.isNull():
            return False
        self._app._table_model.set_structure_pixmap(oid, pm)
        self._app.table.setRowHeight(int(view_row), structure_depict_height())
        self._sync_structure_column_width_for_zoom_state()
        return True

    def _sync_structure_column_width_for_pixmap(self, pm: QPixmap | None, fallback_w: int) -> None:
        """Grow the Structure column to fit the pixmap + padding (never shrink — avoids fighting user resizes)."""
        col = CompoundTableModel.STRUCTURE_COL
        pad = STRUCTURE_COLUMN_HORIZONTAL_PADDING
        pix_w = int(pm.width()) if pm is not None and not pm.isNull() else int(fallback_w)
        need = max(1, pix_w + pad)
        cur = int(self._app.table.columnWidth(col))
        if need > cur:
            self._app.table.setColumnWidth(col, need)
        if need > self._app.table.structure_column_minimum_width():
            self._app.table.set_structure_column_minimum_width(need)

    def _sync_data_pixmap_column_width(
        self, header_name: str, pm: QPixmap | None, fallback_w: int
    ) -> None:
        try:
            col = self._app.headers.index(header_name)
        except ValueError:
            return
        pad = STRUCTURE_COLUMN_HORIZONTAL_PADDING
        pix_w = int(pm.width()) if pm is not None and not pm.isNull() else int(fallback_w)
        need = max(1, pix_w + pad)
        cur = int(self._app.table.columnWidth(col))
        if need > cur:
            self._app.table.setColumnWidth(col, need)
