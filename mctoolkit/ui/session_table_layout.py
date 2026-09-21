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

"""Table header/layout chrome for session save and restore."""

from __future__ import annotations

from contextlib import suppress

from PySide6.QtCore import QByteArray


class SessionTableLayout:
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
            hh = self._app.table.horizontalHeader()
        except RuntimeError:
            hh = None
        updates = False
        try:
            updates = bool(self._app.table.updatesEnabled())
            self._app.table.setUpdatesEnabled(False)
        except RuntimeError:
            pass
        try:
            for i, h in enumerate(self._app.headers):
                if not h:
                    continue
                was_hidden = False
                try:
                    was_hidden = bool(self._app.table.isColumnHidden(i))
                    if was_hidden and i != 0 and hh is not None:
                        hh.showSection(i)
                    width = int(self._app.table.columnWidth(i))
                except RuntimeError:
                    width = 0
                if was_hidden:
                    with suppress(RuntimeError):
                        self._app.table.setColumnHidden(i, True)
                    if i != 0:
                        hidden.append(h)
                if width > 0 and h != "ID_HIDDEN":
                    widths[h] = width
        finally:
            if updates:
                with suppress(RuntimeError):
                    self._app.table.setUpdatesEnabled(True)
        default_h = None
        vh = None
        try:
            vh = self._app.table.verticalHeader()
            if vh is not None:
                default_h = int(vh.defaultSectionSize())
        except RuntimeError:
            vh = None
        scroll_v = None
        scroll_h = None
        try:
            vbar = self._app.table.verticalScrollBar()
            hbar = self._app.table.horizontalScrollBar()
            if vbar is not None:
                scroll_v = int(vbar.value())
            if hbar is not None:
                scroll_h = int(hbar.value())
        except RuntimeError:
            pass
        payload = {
            "column_widths": widths,
            "hidden_columns": hidden,
            "pixmap_columns": self._app._table_model.pixmap_data_column_headers(),
            "default_row_height": default_h,
            "hheader_state": self._header_state_b64(hh),
            "vheader_state": self._header_state_b64(vh),
            "scroll_vertical": scroll_v,
            "scroll_horizontal": scroll_h,
        }
        mgr = getattr(self._app, "_workspace_layout", None)
        if mgr is not None:
            with suppress(RuntimeError):
                payload["workspace"] = mgr.collect_splitter_sizes()
        return payload

    def _restore_table_layout(self, payload: object) -> None:
        if not isinstance(payload, dict):
            return
        try:
            hh = self._app.table.horizontalHeader()
        except RuntimeError:
            hh = None
        self._restore_header_state_b64(hh, payload.get("hheader_state"))
        widths = payload.get("column_widths")
        if isinstance(widths, dict):
            for name, raw in widths.items():
                if not isinstance(name, str) or name not in self._app.headers:
                    continue
                try:
                    width = int(raw)
                except (TypeError, ValueError):
                    continue
                if width <= 0:
                    continue
                col = self._app.headers.index(name)
                with suppress(RuntimeError):
                    self._app.table.setColumnWidth(col, width)
        hidden = payload.get("hidden_columns")
        if isinstance(hidden, list):
            for name in hidden:
                if (
                    not isinstance(name, str)
                    or name not in self._app.headers
                    or name == "ID_HIDDEN"
                ):
                    continue
                with suppress(RuntimeError):
                    self._app.table.setColumnHidden(self._app.headers.index(name), True)
        pix_cols = payload.get("pixmap_columns")
        if isinstance(pix_cols, list):
            for name in pix_cols:
                if (
                    isinstance(name, str)
                    and name in self._app.headers
                    and name not in ("ID_HIDDEN", "Structure")
                ):
                    self._app._table_model.register_pixmap_column(name)
        try:
            vh = self._app.table.verticalHeader()
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
        with suppress(RuntimeError):
            self._app.table.setColumnHidden(0, True)
        try:
            vbar = self._app.table.verticalScrollBar()
            hbar = self._app.table.horizontalScrollBar()
            sv = payload.get("scroll_vertical")
            sh = payload.get("scroll_horizontal")
            if vbar is not None and isinstance(sv, (int, float)):
                vbar.setValue(int(sv))
            if hbar is not None and isinstance(sh, (int, float)):
                hbar.setValue(int(sh))
        except RuntimeError:
            pass

    def _restore_column_visual_order(self, logical_order: list[int]) -> None:
        h = self._app.table.horizontalHeader()
        n = self._app._table_model.columnCount()
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
        pending = getattr(self._app, "_pending_session_workspace_layout", None)
        if not isinstance(pending, dict):
            return
        mgr = getattr(self._app, "_workspace_layout", None)
        if mgr is None:
            return
        lid = pending.get("layout_id")
        if isinstance(lid, str) and lid and mgr.layout_id != lid:
            with suppress(RuntimeError):
                mgr.apply_layout(lid, preserve_plots=True)
        with suppress(RuntimeError):
            mgr.restore_splitter_sizes(pending)

    def _restore_session_table_chrome(self, payload: object | None = None) -> None:
        """Re-apply saved table layout and column order after other session side effects."""
        layout = (
            payload
            if payload is not None
            else getattr(self._app, "_pending_session_table_layout", None)
        )
        if layout is not None:
            self._restore_table_layout(layout)
        co = getattr(self._app, "_pending_session_column_order", None)
        if isinstance(co, list):
            with suppress(TypeError, ValueError):
                self._restore_column_visual_order([int(x) for x in co])
        apply_font = getattr(self._app, "_apply_table_font", None)
        if callable(apply_font):
            apply_font()

    def _finish_deferred_session_workspace_restore(self) -> None:
        self._restore_pending_workspace_layout()
        self._restore_session_table_chrome()
        self._app._pending_session_table_layout = None
        self._app._pending_session_column_order = None
        self._app._pending_session_workspace_layout = None
