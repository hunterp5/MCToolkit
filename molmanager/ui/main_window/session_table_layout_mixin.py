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

"""Table header/layout chrome for session save and restore."""

from __future__ import annotations

import logging

from PyQt5.QtCore import QByteArray, QTimer, Qt
from PyQt5.QtWidgets import QApplication

from ..qt_widget_utils import qobject_is_deleted

logger = logging.getLogger(__name__)


class SessionTableLayoutMixin:
    @staticmethod
    def _header_state_b64(header) -> str | None:
        if header is None:
            return None
        try:
            raw = header.saveState()
        except RuntimeError:
            return None
        if raw is None or raw.isEmpty():
            return None
        return bytes(raw.toBase64()).decode("ascii")

    @staticmethod
    def _restore_header_state_b64(header, payload: object) -> bool:
        if header is None or not isinstance(payload, str) or not payload:
            return False
        try:
            raw = QByteArray.fromBase64(payload.encode("ascii"))
            return bool(header.restoreState(raw))
        except (RuntimeError, ValueError):
            return False

    def _collect_table_layout(self) -> dict:
        """Column widths, hidden columns, row chrome, header state, and workspace layout."""
        widths: dict[str, int] = {}
        hidden: list[str] = []
        hh = None
        try:
            hh = self.table.horizontalHeader()
        except RuntimeError:
            hh = None
        updates = False
        try:
            updates = bool(self.table.updatesEnabled())
            self.table.setUpdatesEnabled(False)
        except RuntimeError:
            pass
        try:
            for i, h in enumerate(self.headers):
                if not h:
                    continue
                was_hidden = False
                try:
                    was_hidden = bool(self.table.isColumnHidden(i))
                    if was_hidden and i != 0 and hh is not None:
                        hh.showSection(i)
                    width = int(self.table.columnWidth(i))
                except RuntimeError:
                    width = 0
                if was_hidden:
                    try:
                        self.table.setColumnHidden(i, True)
                    except RuntimeError:
                        pass
                    if i != 0:
                        hidden.append(h)
                if width > 0 and h != "ID_HIDDEN":
                    widths[h] = width
        finally:
            if updates:
                try:
                    self.table.setUpdatesEnabled(True)
                except RuntimeError:
                    pass
        default_h = None
        vh = None
        try:
            vh = self.table.verticalHeader()
            if vh is not None:
                default_h = int(vh.defaultSectionSize())
        except RuntimeError:
            vh = None
        scroll_v = None
        scroll_h = None
        try:
            vbar = self.table.verticalScrollBar()
            hbar = self.table.horizontalScrollBar()
            if vbar is not None:
                scroll_v = int(vbar.value())
            if hbar is not None:
                scroll_h = int(hbar.value())
        except RuntimeError:
            pass
        payload = {
            "column_widths": widths,
            "hidden_columns": hidden,
            "pixmap_columns": self._table_model.pixmap_data_column_headers(),
            "default_row_height": default_h,
            "hheader_state": self._header_state_b64(hh),
            "vheader_state": self._header_state_b64(vh),
            "scroll_vertical": scroll_v,
            "scroll_horizontal": scroll_h,
        }
        mgr = getattr(self, "_workspace_layout", None)
        if mgr is not None:
            try:
                payload["workspace"] = mgr.collect_splitter_sizes()
            except RuntimeError:
                pass
        return payload

    def _restore_table_layout(self, payload: object) -> None:
        if not isinstance(payload, dict):
            return
        try:
            hh = self.table.horizontalHeader()
        except RuntimeError:
            hh = None
        self._restore_header_state_b64(hh, payload.get("hheader_state"))
        widths = payload.get("column_widths")
        if isinstance(widths, dict):
            for name, raw in widths.items():
                if not isinstance(name, str) or name not in self.headers:
                    continue
                try:
                    width = int(raw)
                except (TypeError, ValueError):
                    continue
                if width <= 0:
                    continue
                col = self.headers.index(name)
                try:
                    self.table.setColumnWidth(col, width)
                except RuntimeError:
                    pass
        hidden = payload.get("hidden_columns")
        if isinstance(hidden, list):
            for name in hidden:
                if not isinstance(name, str) or name not in self.headers or name == "ID_HIDDEN":
                    continue
                try:
                    self.table.setColumnHidden(self.headers.index(name), True)
                except RuntimeError:
                    pass
        pix_cols = payload.get("pixmap_columns")
        if isinstance(pix_cols, list):
            for name in pix_cols:
                if (
                    isinstance(name, str)
                    and name in self.headers
                    and name not in ("ID_HIDDEN", "Structure")
                ):
                    self._table_model.register_pixmap_column(name)
        try:
            vh = self.table.verticalHeader()
        except RuntimeError:
            vh = None
        self._restore_header_state_b64(vh, payload.get("vheader_state"))
        raw_h = payload.get("default_row_height")
        try:
            row_h = int(raw_h)
        except (TypeError, ValueError):
            row_h = 0
        if row_h > 0:
            try:
                if vh is not None:
                    vh.setDefaultSectionSize(row_h)
            except RuntimeError:
                pass
        try:
            self.table.setColumnHidden(0, True)
        except RuntimeError:
            pass
        try:
            vbar = self.table.verticalScrollBar()
            hbar = self.table.horizontalScrollBar()
            sv = payload.get("scroll_vertical")
            sh = payload.get("scroll_horizontal")
            if vbar is not None and isinstance(sv, (int, float)):
                vbar.setValue(int(sv))
            if hbar is not None and isinstance(sh, (int, float)):
                hbar.setValue(int(sh))
        except RuntimeError:
            pass

    def _restore_column_visual_order(self, logical_order: list[int]) -> None:
        h = self.table.horizontalHeader()
        n = self._table_model.columnCount()
        if not logical_order or len(logical_order) != n:
            return
        if any(not isinstance(x, int) or x < 0 or x >= n for x in logical_order):
            return
        for target_visual, want_logical in enumerate(logical_order):
            cur_v = h.visualIndex(want_logical)
            if cur_v != target_visual:
                h.moveSection(cur_v, target_visual)

    def _restore_pending_workspace_layout(self) -> None:
        """Re-apply saved splitter ratios after the workspace has a real size."""
        pending = getattr(self, "_pending_session_workspace_layout", None)
        if not isinstance(pending, dict):
            return
        mgr = getattr(self, "_workspace_layout", None)
        if mgr is None:
            return
        lid = pending.get("layout_id")
        if isinstance(lid, str) and lid and mgr.layout_id != lid:
            try:
                mgr.apply_layout(lid, preserve_plots=True)
            except RuntimeError:
                pass
        try:
            mgr.restore_splitter_sizes(pending)
        except RuntimeError:
            pass

    def _restore_session_table_chrome(self, payload: object | None = None) -> None:
        """Re-apply saved table layout and column order after other session side effects."""
        layout = (
            payload if payload is not None else getattr(self, "_pending_session_table_layout", None)
        )
        if layout is not None:
            self._restore_table_layout(layout)
        co = getattr(self, "_pending_session_column_order", None)
        if isinstance(co, list):
            try:
                self._restore_column_visual_order([int(x) for x in co])
            except (TypeError, ValueError):
                pass
        apply_font = getattr(self, "_apply_table_font", None)
        if callable(apply_font):
            apply_font()

    def _finish_deferred_session_workspace_restore(self) -> None:
        self._restore_pending_workspace_layout()
        self._restore_session_table_chrome()
        self._pending_session_table_layout = None
        self._pending_session_column_order = None
        self._pending_session_workspace_layout = None
