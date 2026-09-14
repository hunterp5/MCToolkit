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

"""
QAbstractTableModel + QTableView stack for compound tables.

The model owns row text, optional structure pixmaps, and stable molecule ids; a delegate
paints the Structure column.

Run the standalone demo::

    python -m molmanager.table_model_demo
    python -m molmanager.ui.compound_table_model
"""

from __future__ import annotations

import zlib
from dataclasses import dataclass, field

from PyQt5.QtCore import QAbstractItemModel, QAbstractTableModel, QModelIndex, QRect, QSize, Qt
from PyQt5.QtGui import QColor, QPalette, QPixmap
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QHeaderView,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableView,
)

from ..column_score_color import (
    COLOR_ALPHA,
    COLOR_FAVORABLE_RGB,
    COLOR_MID_RGB,
    COLOR_UNFAVORABLE_RGB,
    favorable_score_color_spec,
)
from ..display_constants import (
    STRUCTURE_COLUMN_HORIZONTAL_PADDING,
    STRUCTURE_DEPICT_HEIGHT,
    STRUCTURE_DEPICT_WIDTH,
    STRUCTURE_ROW_DEFAULT_HEIGHT,
    structure_column_minimum_width,
    structure_depiict_height,
    structure_depiict_width,
    structure_row_default_height,
)
from ..structure_render_store import StructureRenderStore
from ..utils import safe_float
from .strings import STRUCTURE_PENDING_HINT

# Backward-compatible names (also re-export layout constants for ``from .compound_table_model import …``).
STRUCTURE_COLUMN_PENDING_HINT = STRUCTURE_PENDING_HINT

__all__ = [
    "CompoundTableModel",
    "CompoundTableView",
    "StructureDelegate",
    "STRUCTURE_COLUMN_HORIZONTAL_PADDING",
    "STRUCTURE_COLUMN_PENDING_HINT",
    "STRUCTURE_DEPICT_HEIGHT",
    "STRUCTURE_DEPICT_WIDTH",
    "STRUCTURE_ROW_DEFAULT_HEIGHT",
    "structure_column_minimum_width",
    "structure_depiict_height",
    "structure_depiict_width",
    "structure_row_default_height",
]

# Packed multi-conformer / alignment payloads — not numeric filter columns (avoids scanning huge cells).
_NON_NUMERIC_BLOB_COLUMNS = frozenset({"confs", "superpose"})


@dataclass
class _Row:
    oid: int
    values: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class _ColumnColorRule:
    mode: str
    min_value: float = 0.0
    mid_value: float = 0.5
    max_value: float = 1.0
    low_rgb: int = 0
    mid_rgb: int = 0
    high_rgb: int = 0
    alpha: int = 96


class CompoundTableModel(QAbstractTableModel):
    """
    Column 0: hidden id (string of oid).
    Column 1: Structure (pixmap via DecorationRole, or placeholder).
    Column 2..n: text from ``values`` keyed by header name.
    """

    STRUCTURE_COL = 1
    STRUCTURE_PAINT_ROLES = frozenset(
        {
            Qt.DecorationRole,
            Qt.SizeHintRole,
            Qt.DisplayRole,
            Qt.ToolTipRole,
        }
    )

    @classmethod
    def is_structure_paint_data_change(cls, top_left, bottom_right, roles=()) -> bool:
        """True when ``dataChanged`` is a Structure pixmap paint (lazy-scroll flush)."""
        if top_left is None or bottom_right is None:
            return False
        try:
            if not top_left.isValid() or not bottom_right.isValid():
                return False
            if top_left.column() != cls.STRUCTURE_COL or bottom_right.column() != cls.STRUCTURE_COL:
                return False
        except Exception:
            return False
        if not roles:
            return True
        try:
            return set(roles) <= cls.STRUCTURE_PAINT_ROLES
        except TypeError:
            return True

    def __init__(self, headers: list[str], parent=None):
        super().__init__(parent)
        self._headers = list(headers)
        self._rows: list[_Row] = []
        self._pixmaps: dict[int, QPixmap] = {}
        self._structure_png_store: StructureRenderStore | None = None
        self._oid_to_row: dict[int, int] = {}
        # Optional extra columns that show a 2D pixmap (e.g. disconnected fragment) keyed by (oid, header).
        self._pixmap_columns: set[str] = set()
        self._extra_pixmaps: dict[tuple[int, str], QPixmap] = {}
        # Incremental numeric min/max cache for filter sliders (see numeric_bounds_by_column).
        self._numeric_bounds_cache: dict[str, dict] | None = None
        self._numeric_bounds_key: tuple[str, ...] | None = (
            None  # sorted data header names used for last full build
        )
        self._numeric_bounds_dirty_cols: set[str] | None = None  # None = need full rebuild
        # Optional per-column background coloring with O(1) lookups in data().
        self._column_color_rules: dict[str, _ColumnColorRule] = {}
        self._column_color_cache: dict[str, dict[int, int]] = {}
        self._rgb_qcolor_cache: dict[int, QColor] = {}
        # Logical row selection (OID set) for large selections — painted by delegates, not QItemSelection.
        self._highlighted_oids: frozenset[int] | None = None
        self._silent_append_depth = 0
        self._silent_append_start_row = 0

    def begin_silent_appends(self) -> None:
        """Defer ``beginInsertRows`` until :meth:`end_silent_appends` (bulk file ingest)."""
        if self._silent_append_depth == 0:
            self._silent_append_start_row = len(self._rows)
        self._silent_append_depth += 1

    def end_silent_appends(self) -> None:
        """Emit one insert notification for rows appended since :meth:`begin_silent_appends`."""
        if self._silent_append_depth <= 0:
            return
        self._silent_append_depth -= 1
        if self._silent_append_depth != 0:
            return
        start = int(self._silent_append_start_row)
        end = len(self._rows) - 1
        if end >= start:
            self.beginInsertRows(QModelIndex(), start, end)
            self.endInsertRows()

    @property
    def silent_appending(self) -> bool:
        return self._silent_append_depth > 0

    def set_headers(self, headers: list[str]) -> None:
        self.beginResetModel()
        self._headers = list(headers)
        self._pixmap_columns &= set(self._headers)
        self._extra_pixmaps = {
            k: v for k, v in self._extra_pixmaps.items() if k[1] in self._headers
        }
        keep = set(self._headers)
        self._column_color_rules = {h: r for h, r in self._column_color_rules.items() if h in keep}
        self._column_color_cache = {h: c for h, c in self._column_color_cache.items() if h in keep}
        self._invalidate_numeric_bounds_all()
        self.endResetModel()

    def clear_rows(self) -> None:
        """Drop all rows and cached structure pixmaps; keep column headers."""
        self._silent_append_depth = 0
        self._silent_append_start_row = 0
        self.beginResetModel()
        self._rows.clear()
        self._pixmaps.clear()
        self._structure_png_store = None
        self._oid_to_row.clear()
        self._extra_pixmaps.clear()
        self._highlighted_oids = None
        for cache in self._column_color_cache.values():
            cache.clear()
        self._invalidate_numeric_bounds_all()
        self.endResetModel()

    def set_highlighted_oids(self, oids: frozenset[int] | set[int] | None) -> None:
        """Rows whose OID is in *oids* are painted as selected (for large logical selections)."""
        new = None if oids is None else frozenset(int(x) for x in oids)
        if new == self._highlighted_oids:
            return
        self._highlighted_oids = new

    def highlighted_oids(self) -> frozenset[int] | None:
        return self._highlighted_oids

    def is_row_highlighted(self, row: int) -> bool:
        if self._highlighted_oids is None:
            return False
        if row < 0 or row >= len(self._rows):
            return False
        return int(self._rows[row].oid) in self._highlighted_oids

    def clear(self) -> None:
        """Remove rows and clear the header list (empty table)."""
        self._silent_append_depth = 0
        self._silent_append_start_row = 0
        self.beginResetModel()
        self._rows.clear()
        self._pixmaps.clear()
        self._structure_png_store = None
        self._headers.clear()
        self._oid_to_row.clear()
        self._pixmap_columns.clear()
        self._extra_pixmaps.clear()
        self._column_color_rules.clear()
        self._column_color_cache.clear()
        self._invalidate_numeric_bounds_all()
        self.endResetModel()

    def append_row(self, oid: int, cells: dict[str, str]) -> None:
        r = len(self._rows)
        self.beginInsertRows(QModelIndex(), r, r)
        row_obj = _Row(oid=oid, values=dict(cells))
        self._rows.append(row_obj)
        self.endInsertRows()
        self._oid_to_row[oid] = len(self._rows) - 1
        if self._column_color_rules:
            self._refresh_color_cache_for_row(row_obj, cells)
        bh = self._bounds_data_headers()
        for k in cells:
            if k in bh:
                self._mark_numeric_bounds_dirty({k})

    def append_rows_batch(
        self,
        entries: list[tuple[int, dict[str, str]]],
        *,
        defer_color_cache: bool = False,
        silent: bool | None = None,
    ) -> None:
        """Append many rows with a single insert-range notification."""
        if not entries:
            return
        use_silent = bool(silent) if silent is not None else self.silent_appending
        bh = self._bounds_data_headers()
        dirty_cols: set[str] = set()
        refresh_color = bool(self._column_color_rules) and not defer_color_cache
        start = len(self._rows)
        row_idx = start
        for oid, cells in entries:
            row_cells = dict(cells)
            row_obj = _Row(oid=int(oid), values=row_cells)
            self._rows.append(row_obj)
            self._oid_to_row[int(oid)] = row_idx
            row_idx += 1
            if refresh_color:
                self._refresh_color_cache_for_row(row_obj, row_cells)
            if bh:
                dirty_cols |= {k for k in row_cells if k in bh}
        if dirty_cols:
            self._mark_numeric_bounds_dirty(dirty_cols)
        if use_silent:
            return
        end = start + len(entries) - 1
        self.beginInsertRows(QModelIndex(), start, end)
        self.endInsertRows()

    def rebuild_column_color_caches_after_bulk_load(self) -> None:
        """Refresh conditional-format caches after a large append (skipped per row during ingest)."""
        if not self._column_color_rules:
            return
        for header_name in list(self._column_color_rules.keys()):
            self._rebuild_column_color_cache(header_name)

    def insert_row_at(self, logical_index: int, oid: int, cells: dict[str, str]) -> None:
        n = len(self._rows)
        logical_index = max(0, min(logical_index, n))
        self.beginInsertRows(QModelIndex(), logical_index, logical_index)
        self._rows.insert(logical_index, _Row(oid=oid, values=dict(cells)))
        self.endInsertRows()
        self._rebuild_oid_index()
        if self._column_color_rules:
            self._refresh_color_cache_for_row(self._rows[logical_index], cells)
        self._invalidate_numeric_bounds_all()

    def remove_row_at(self, logical_row: int) -> None:
        if logical_row < 0 or logical_row >= len(self._rows):
            return
        self.beginRemoveRows(QModelIndex(), logical_row, logical_row)
        oid = self._rows[logical_row].oid
        self._rows.pop(logical_row)
        self._drop_row_assets(oid)
        self.endRemoveRows()
        self._rebuild_oid_index()
        self._invalidate_numeric_bounds_all()

    def _drop_row_assets(self, oid: int) -> None:
        oid_i = int(oid)
        self._pixmaps.pop(oid_i, None)
        for k in [x for x in self._extra_pixmaps if x[0] == oid_i]:
            del self._extra_pixmaps[k]
        for cache in self._column_color_cache.values():
            cache.pop(oid_i, None)
        store = self._structure_png_store
        if store is not None:
            store.remove_oid(oid_i)

    def remove_rows_by_oids(self, oids: frozenset[int] | set[int]) -> int:
        """Remove every row whose OID is in *oids* with a single model reset (fast bulk delete)."""
        kill = {int(x) for x in oids}
        if not kill:
            return 0
        n_before = len(self._rows)
        self.beginResetModel()
        self._rows = [r for r in self._rows if int(r.oid) not in kill]
        for oid in kill:
            self._drop_row_assets(oid)
        if self._highlighted_oids is not None:
            remaining = frozenset(x for x in self._highlighted_oids if int(x) not in kill)
            self._highlighted_oids = remaining if remaining else None
        self._rebuild_oid_index()
        self._invalidate_numeric_bounds_all()
        self.endResetModel()
        return n_before - len(self._rows)

    def insert_rows_batch(self, rows: list[tuple[int, int, dict[str, str]]]) -> None:
        """Restore rows deleted in bulk (undo). Each item is ``(orig_logical_index, oid, cells)``."""
        if not rows:
            return
        ordered = sorted(rows, key=lambda item: item[0])
        self.beginResetModel()
        new_rows = list(self._rows)
        for k, (orig_row, oid, cells) in enumerate(ordered):
            insert_at = max(0, min(int(orig_row) + k, len(new_rows)))
            new_rows.insert(insert_at, _Row(oid=int(oid), values=dict(cells)))
        self._rows = new_rows
        self._rebuild_oid_index()
        if self._column_color_rules:
            for _orig_row, _oid, cells in ordered:
                row_obj = self._rows[self._oid_to_row[int(_oid)]]
                self._refresh_color_cache_for_row(row_obj, cells)
        self._invalidate_numeric_bounds_all()
        self.endResetModel()

    def row_oid(self, logical_row: int) -> int:
        return self._rows[logical_row].oid

    def _rebuild_oid_index(self) -> None:
        self._oid_to_row = {row.oid: i for i, row in enumerate(self._rows)}

    def logical_row_for_oid(self, oid: int) -> int:
        r = self._oid_to_row.get(oid, -1)
        if 0 <= r < len(self._rows) and self._rows[r].oid == oid:
            return r
        self._rebuild_oid_index()
        return self._oid_to_row.get(oid, -1)

    def export_rows_for_sqlite(self, data_headers: list[str]) -> list[tuple[int, dict[str, str]]]:
        """Bulk export text columns for the SQLite mirror (avoids per-cell lookup)."""
        return self.export_rows_for_sqlite_slice(data_headers, 0, len(self._rows))

    def export_rows_for_sqlite_slice(
        self,
        data_headers: list[str],
        start_row: int,
        end_row: int,
    ) -> list[tuple[int, dict[str, str]]]:
        """Export a row slice ``[start_row, end_row)`` for chunked SQLite indexing."""
        n = len(self._rows)
        lo = max(0, int(start_row))
        hi = min(n, int(end_row))
        out: list[tuple[int, dict[str, str]]] = []
        for r in range(lo, hi):
            row = self._rows[r]
            cells = {h: str(row.values.get(h, "") or "") for h in data_headers}
            out.append((int(row.oid), cells))
        return out

    def set_cell_text(self, oid: int, column_name: str, text: str) -> None:
        if column_name in ("ID_HIDDEN", "Structure") or column_name in self._pixmap_columns:
            return
        r = self.logical_row_for_oid(oid)
        if r < 0:
            return
        self._rows[r].values[column_name] = text
        self._refresh_color_cache_for_cell(self._rows[r], column_name, text)
        if column_name in self._bounds_data_headers():
            self._mark_numeric_bounds_dirty({column_name})
        try:
            c = self._headers.index(column_name)
        except ValueError:
            return
        idx = self.index(r, c)
        self.dataChanged.emit(idx, idx, [Qt.DisplayRole, Qt.EditRole, Qt.BackgroundRole])

    def set_backing_text(self, oid: int, column_name: str, text: str) -> None:
        """Set stored cell text, including pixmap-only structure columns (hidden SMILES)."""
        if column_name in ("ID_HIDDEN", "Structure"):
            return
        if column_name not in self._pixmap_columns:
            self.set_cell_text(oid, column_name, text)
            return
        r = self.logical_row_for_oid(oid)
        if r < 0:
            return
        self._rows[r].values[column_name] = text
        try:
            c = self._headers.index(column_name)
        except ValueError:
            return
        idx = self.index(r, c)
        self.dataChanged.emit(
            idx, idx, [Qt.DisplayRole, Qt.EditRole, Qt.DecorationRole, Qt.SizeHintRole]
        )

    def set_cell_text_batch(self, oid: int, values: dict[str, str]) -> None:
        """Set several text cells on one row; emit ``dataChanged`` once for the affected column span."""
        if not values:
            return
        r = self.logical_row_for_oid(oid)
        if r < 0:
            return
        changed_cols: list[int] = []
        for column_name, text in values.items():
            if column_name in ("ID_HIDDEN", "Structure") or column_name in self._pixmap_columns:
                continue
            try:
                c = self._headers.index(column_name)
            except ValueError:
                continue
            text_s = str(text)
            self._rows[r].values[column_name] = text_s
            self._refresh_color_cache_for_cell(self._rows[r], column_name, text_s)
            changed_cols.append(c)
        if not changed_cols:
            return
        dirty = {
            self._headers[c]
            for c in changed_cols
            if self._headers[c] in self._bounds_data_headers()
        }
        if dirty:
            self._mark_numeric_bounds_dirty(dirty)
        lo, hi = min(changed_cols), max(changed_cols)
        idx_tl = self.index(r, lo)
        idx_br = self.index(r, hi)
        self.dataChanged.emit(idx_tl, idx_br, [Qt.DisplayRole, Qt.EditRole, Qt.BackgroundRole])

    def structure_png_store_active(self) -> bool:
        store = self._structure_png_store
        return store is not None and len(store) > 0

    def set_structure_png_store(self, store: StructureRenderStore | None) -> None:
        self._structure_png_store = store

    def clear_structure_png_store(self) -> None:
        if self._structure_png_store is not None:
            self._structure_png_store.clear()
        self._structure_png_store = None

    def structure_pixmap_for_oid(self, oid: int) -> QPixmap | None:
        pix = self._pixmaps.get(int(oid))
        if pix is not None and not pix.isNull():
            return pix
        store = self._structure_png_store
        if store is not None and store.has_png(oid):
            return store.pixmap(oid)
        return None

    def notify_structure_column_changed(self, row_lo: int = 0, row_hi: int | None = None) -> None:
        if not self._rows:
            return
        hi = (
            len(self._rows) - 1 if row_hi is None else max(0, min(int(row_hi), len(self._rows) - 1))
        )
        lo = max(0, min(int(row_lo), hi))
        roles = list(self.STRUCTURE_PAINT_ROLES)
        self.dataChanged.emit(
            self.index(lo, self.STRUCTURE_COL), self.index(hi, self.STRUCTURE_COL), roles
        )

    def clear_structure_pixmaps_for_oids(self, oids: list[int], *, emit: bool = True) -> None:
        for oid in oids:
            self._pixmaps.pop(int(oid), None)
            store = self._structure_png_store
            if store is not None:
                store.remove_oid(oid)
        if emit and oids and self._rows:
            self.notify_structure_column_changed()

    def apply_structure_pixmaps_batch(
        self,
        items: list[tuple[int, QPixmap | None]],
        *,
        emit: bool = True,
    ) -> None:
        rows: list[int] = []
        for oid, pixmap in items:
            oid_i = int(oid)
            if pixmap is not None and not pixmap.isNull():
                self._pixmaps[oid_i] = pixmap
            else:
                self._pixmaps.pop(oid_i, None)
            r = self.logical_row_for_oid(oid_i)
            if r >= 0:
                rows.append(r)
        if emit and rows and self._rows:
            lo, hi = min(rows), max(rows)
            self.notify_structure_column_changed(lo, hi)

    def set_structure_pixmap(self, oid: int, pixmap: QPixmap | None) -> None:
        if pixmap is not None:
            self._pixmaps[oid] = pixmap
        else:
            self._pixmaps.pop(oid, None)
        r = self.logical_row_for_oid(oid)
        if r < 0:
            return
        idx = self.index(r, self.STRUCTURE_COL)
        self.dataChanged.emit(idx, idx, list(self.STRUCTURE_PAINT_ROLES))

    def register_pixmap_column(self, header_name: str) -> None:
        """Mark a data column as image-only (2D pixmap via ``set_column_pixmap``)."""
        if header_name in self._headers:
            self._pixmap_columns.add(header_name)

    def pixmap_data_column_headers(self) -> list[str]:
        """Data-column headers currently displayed as 2D images rather than text."""
        return [h for h in self._headers[2:] if h in self._pixmap_columns]

    def column_accepts_text_edit(self, logical_col: int) -> bool:
        """Plain string cells: not id, not structure, not pixmap-only columns."""
        if logical_col < 2 or logical_col >= len(self._headers):
            return False
        return self._headers[logical_col] not in self._pixmap_columns

    def set_column_pixmap(self, oid: int, header_name: str, pixmap: QPixmap | None) -> None:
        """Set pixmap for one row in a pixmap-only column (see ``register_pixmap_column``)."""
        if header_name not in self._pixmap_columns:
            return
        self._set_extra_pixmap(oid, header_name, pixmap)

    def set_cell_pixmap(self, oid: int, header_name: str, pixmap: QPixmap | None) -> None:
        """Set an optional 2D image for one cell; other rows in the column keep their text."""
        if header_name in self._pixmap_columns:
            self.set_column_pixmap(oid, header_name, pixmap)
            return
        self._set_extra_pixmap(oid, header_name, pixmap)

    def _set_extra_pixmap(self, oid: int, header_name: str, pixmap: QPixmap | None) -> None:
        if header_name not in self._headers or header_name in ("ID_HIDDEN", "Structure"):
            return
        key = (oid, header_name)
        if pixmap is not None and not pixmap.isNull():
            self._extra_pixmaps[key] = pixmap
        else:
            self._extra_pixmaps.pop(key, None)
        r = self.logical_row_for_oid(oid)
        if r < 0:
            return
        try:
            c = self._headers.index(header_name)
        except ValueError:
            return
        idx = self.index(r, c)
        self.dataChanged.emit(
            idx, idx, [Qt.DecorationRole, Qt.SizeHintRole, Qt.DisplayRole, Qt.ToolTipRole]
        )

    def cell_pixmap_copy(self, oid: int, header_name: str) -> QPixmap | None:
        return self.column_pixmap_copy(oid, header_name)

    def snapshot_structure_pixmaps(self, oids: list[int]) -> dict[int, QPixmap | None]:
        """Shallow copies of structure pixmaps for undo/cancel (caller owns QPixmap copies)."""
        out: dict[int, QPixmap | None] = {}
        for oid in oids:
            p = self._pixmaps.get(oid)
            if p is not None and not p.isNull():
                out[oid] = QPixmap(p)
            else:
                out[oid] = None
        return out

    def snapshot_column_pixmaps(
        self, header_name: str, oids: list[int]
    ) -> dict[int, QPixmap | None]:
        """Shallow copies of pixmap-column images for a header (e.g. Render 2D target column)."""
        out: dict[int, QPixmap | None] = {}
        if header_name not in self._headers:
            return out
        for oid in oids:
            key = (oid, header_name)
            p = self._extra_pixmaps.get(key)
            if p is not None and not p.isNull():
                out[oid] = QPixmap(p)
            else:
                out[oid] = None
        return out

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        if parent.isValid():
            return 0
        return len(self._rows)

    def columnCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        if parent.isValid():
            return 0
        return len(self._headers)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):  # noqa: N802
        if not index.isValid():
            return None
        row, col = index.row(), index.column()
        if row < 0 or row >= len(self._rows) or col < 0 or col >= len(self._headers):
            return None
        h = self._headers[col]
        oid = self._rows[row].oid

        if col == 0:
            if role in (Qt.DisplayRole, Qt.EditRole):
                return str(oid)
            if role == Qt.TextAlignmentRole:
                return int(Qt.AlignCenter)
            return None

        if col == self.STRUCTURE_COL:
            pix = self.structure_pixmap_for_oid(oid)
            has_pix = pix is not None and not pix.isNull()
            if role == Qt.DecorationRole:
                return pix if has_pix else None
            if role in (Qt.DisplayRole, Qt.EditRole):
                if has_pix:
                    return ""
                store = self._structure_png_store
                if store is not None and store.has_png(oid):
                    return ""
                return STRUCTURE_COLUMN_PENDING_HINT
            if role == Qt.TextAlignmentRole:
                if has_pix:
                    return int(Qt.AlignCenter)
                return int(Qt.AlignCenter | Qt.AlignVCenter)
            if role == Qt.SizeHintRole:
                if has_pix:
                    return QSize(pix.width(), pix.height())
                return QSize(structure_depiict_width(), structure_depiict_height())
            if role == Qt.ToolTipRole:
                if has_pix:
                    return None
                store = self._structure_png_store
                if store is not None and store.has_png(oid):
                    return None
                return STRUCTURE_COLUMN_PENDING_HINT
            return None

        if h in self._pixmap_columns:
            pix = self._extra_pixmaps.get((oid, h))
            has_pix = pix is not None and not pix.isNull()
            backing = self._rows[row].values.get(h, "") or ""
            if role == Qt.DecorationRole:
                return pix if has_pix else None
            if role == Qt.DisplayRole:
                return "" if has_pix else backing
            if role == Qt.ToolTipRole:
                return None if has_pix else (backing or None)
            if role == Qt.TextAlignmentRole:
                return int(Qt.AlignCenter) if has_pix else None
            if role == Qt.SizeHintRole:
                if has_pix:
                    return QSize(pix.width(), pix.height())
                return None
            return None

        cell_pix = self._extra_pixmaps.get((oid, h))
        if cell_pix is not None and not cell_pix.isNull():
            if role == Qt.DecorationRole:
                return cell_pix
            if role == Qt.SizeHintRole:
                return QSize(cell_pix.width() + 8, cell_pix.height() + 8)
            if role == Qt.TextAlignmentRole:
                return int(Qt.AlignCenter)

        if role == Qt.BackgroundRole:
            cmap = self._column_color_cache.get(h)
            if cmap:
                rgb = cmap.get(oid)
                if rgb is not None:
                    qc = self._rgb_qcolor_cache.get(rgb)
                    if qc is None:
                        qc = QColor.fromRgba(rgb)
                        self._rgb_qcolor_cache[rgb] = qc
                    return qc
            return None

        if role in (Qt.DisplayRole, Qt.EditRole):
            return self._rows[row].values.get(h, "")
        if role == Qt.TextAlignmentRole:
            v = self._rows[row].values.get(h, "")
            if safe_float(v) is not None:
                return int(Qt.AlignRight | Qt.AlignVCenter)
        return None

    def setData(self, index: QModelIndex, value, role: int = Qt.EditRole) -> bool:  # noqa: N802
        if not index.isValid() or role != Qt.EditRole:
            return False
        row, col = index.row(), index.column()
        if row < 0 or row >= len(self._rows) or col < 2:
            return False
        h = self._headers[col]
        text_s = str(value)
        self._rows[row].values[h] = text_s
        self._refresh_color_cache_for_cell(self._rows[row], h, text_s)
        self.dataChanged.emit(index, index, [Qt.DisplayRole, Qt.EditRole, Qt.BackgroundRole])
        return True

    def flags(self, index: QModelIndex) -> Qt.ItemFlags:  # noqa: N802
        if not index.isValid():
            return Qt.NoItemFlags
        return Qt.ItemIsEnabled | Qt.ItemIsSelectable

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole):  # noqa: N802
        if role == Qt.TextAlignmentRole:
            if orientation == Qt.Vertical:
                return int(Qt.AlignCenter)
            return None
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal and 0 <= section < len(self._headers):
            return self._headers[section]
        if orientation == Qt.Vertical:
            return str(section + 1)
        return None

    def sort(
        self, column: int, order: Qt.SortOrder = Qt.AscendingOrder, *, sort_kind: str = "auto"
    ) -> None:  # noqa: N802
        """Sort rows by *column*. *sort_kind*: ``auto`` (numbers then text), ``numeric``, or ``alphabetic``."""
        if column < 0 or column >= len(self._headers):
            return
        h = self._headers[column]
        rev = order == Qt.DescendingOrder

        def key_auto(row: _Row) -> tuple:
            if column == 0:
                return (0, row.oid)
            if column == 1:
                return (0, row.oid)
            raw = row.values.get(h, "") or ""
            f = safe_float(raw)
            if f is not None:
                return (0, float(f))
            return (1, raw.lower())

        def key_numeric(row: _Row) -> tuple:
            if column == 0:
                return (0, row.oid)
            if column == 1:
                return (0, row.oid)
            raw = (row.values.get(h, "") or "").strip()
            f = safe_float(raw)
            if f is not None:
                return (0, float(f))
            return (1, raw.lower())

        def key_alpha(row: _Row) -> tuple:
            if column == 0:
                return (0, str(row.oid))
            if column == 1:
                return (0, str(row.oid))
            raw = (row.values.get(h, "") or "").strip()
            return (1, raw.lower())

        if sort_kind == "numeric":
            key = key_numeric
        elif sort_kind == "alphabetic":
            key = key_alpha
        else:
            key = key_auto

        self.layoutAboutToBeChanged.emit([], QAbstractItemModel.VerticalSortHint)
        self._rows.sort(key=key, reverse=rev)
        self.layoutChanged.emit([], QAbstractItemModel.VerticalSortHint)
        self._rebuild_oid_index()

    def all_oids_in_order(self) -> list[int]:
        return [r.oid for r in self._rows]

    def cell_text(self, row: int, col: int) -> str:
        if row < 0 or row >= len(self._rows) or col < 0 or col >= len(self._headers):
            return ""
        if col == 0:
            return str(self._rows[row].oid)
        if col == self.STRUCTURE_COL:
            oid = self._rows[row].oid
            pix = self._pixmaps.get(oid)
            if pix is not None and not pix.isNull():
                return ""
            return STRUCTURE_COLUMN_PENDING_HINT
        h = self._headers[col]
        if h in self._pixmap_columns:
            return ""
        return self._rows[row].values.get(h, "") or ""

    def value_for_header(self, row: int, header_name: str) -> str:
        """Raw string cell for a data column (no QModelIndex); empty if unknown column."""
        if row < 0 or row >= len(self._rows):
            return ""
        if header_name in self._pixmap_columns:
            return ""
        return self._rows[row].values.get(header_name, "") or ""

    def backing_value_for_row_header(self, row: int, header_name: str) -> str:
        """Stored cell text even when ``header_name`` is a pixmap-only column (hidden from ``cell_text``)."""
        if row < 0 or row >= len(self._rows):
            return ""
        return (self._rows[row].values.get(header_name, "") or "").strip()

    def structure_pixmap_copy(self, oid: int) -> QPixmap | None:
        """Detached copy of the main structure pixmap for this molecule id, if any."""
        pm = self._pixmaps.get(oid)
        if pm is not None and not pm.isNull():
            return QPixmap(pm)
        return None

    def structure_png_bytes(self, oid: int) -> bytes | None:
        """Raw structure PNG bytes from the lazy store, if present."""
        store = self._structure_png_store
        if store is None:
            return None
        return store.png_bytes(oid)

    def set_structure_png_bytes(self, oid: int, png: bytes | None) -> None:
        """Restore structure PNG into the lazy store (decoded on demand)."""
        store = self._structure_png_store
        if png:
            if store is None:
                from ...structure_render_store import StructureRenderStore
                from ...config import load_config

                cfg = load_config()
                store = StructureRenderStore(
                    max_decoded_pixmaps=cfg.structure_render_pixmap_lru,
                    max_png_entries=cfg.structure_render_png_max_entries,
                )
                self._structure_png_store = store
            store.ingest_png(int(oid), png)
        elif store is not None:
            store.remove_oid(int(oid))
        r = self.logical_row_for_oid(int(oid))
        if r < 0:
            return
        idx = self.index(r, self.STRUCTURE_COL)
        self.dataChanged.emit(idx, idx, list(self.STRUCTURE_PAINT_ROLES))

    def extra_column_pixmaps_copy(self, oid: int) -> dict[str, QPixmap]:
        """Detached copies of extra pixmap-column images for this oid."""
        out: dict[str, QPixmap] = {}
        for (o, h), pm in list(self._extra_pixmaps.items()):
            if o == oid and pm is not None and not pm.isNull():
                out[h] = QPixmap(pm)
        return out

    def is_pixmap_data_column(self, header_name: str) -> bool:
        return header_name in self._pixmap_columns

    def column_pixmap_copy(self, oid: int, header_name: str) -> QPixmap | None:
        pm = self._extra_pixmaps.get((oid, header_name))
        if pm is not None and not pm.isNull():
            return QPixmap(pm)
        return None

    def column_pixmaps_by_oid(self, header_name: str) -> dict[int, QPixmap]:
        """Snapshot pixmap-column cells for undo (only rows that have an image)."""
        out: dict[int, QPixmap] = {}
        for (oid, h), pm in self._extra_pixmaps.items():
            if h == header_name and pm is not None and not pm.isNull():
                out[oid] = QPixmap(pm)
        return out

    def _bounds_data_headers(self) -> frozenset[str]:
        return frozenset(
            h
            for h in self._headers[2:]
            if h not in ("ID_HIDDEN", "Structure")
            and h not in self._pixmap_columns
            and h not in _NON_NUMERIC_BLOB_COLUMNS
        )

    def _invalidate_numeric_bounds_all(self) -> None:
        self._numeric_bounds_cache = None
        self._numeric_bounds_key = None
        self._numeric_bounds_dirty_cols = None

    def _mark_numeric_bounds_dirty(self, columns: set[str]) -> None:
        if not columns:
            return
        if self._numeric_bounds_cache is None:
            return
        if self._numeric_bounds_dirty_cols is None:
            return
        self._numeric_bounds_dirty_cols |= columns

    def _sorted_bounds_data_headers(self) -> list[str]:
        return sorted(
            h
            for h in self._headers[2:]
            if h not in ("ID_HIDDEN", "Structure")
            and h not in self._pixmap_columns
            and h not in _NON_NUMERIC_BLOB_COLUMNS
        )

    def _mark_headers_added_for_bounds(self, new_headers: list[str]) -> None:
        """Extend bounds cache metadata when columns are appended (avoid full-table rescan)."""
        bounds_headers = [h for h in new_headers if h in self._bounds_data_headers()]
        if not bounds_headers:
            return
        if self._numeric_bounds_cache is None:
            return
        self._numeric_bounds_key = tuple(self._sorted_bounds_data_headers())
        if self._numeric_bounds_dirty_cols is None:
            self._numeric_bounds_dirty_cols = set()
        self._numeric_bounds_dirty_cols.update(bounds_headers)

    def _mark_header_removed_for_bounds(self, removed: str) -> None:
        """Drop one column from the bounds cache without rescanning the full table."""
        if self._numeric_bounds_cache is None:
            return
        self._numeric_bounds_cache.pop(removed, None)
        self._numeric_bounds_key = tuple(self._sorted_bounds_data_headers())
        if self._numeric_bounds_dirty_cols is not None:
            self._numeric_bounds_dirty_cols.discard(removed)

    def numeric_bounds_for_header(self, header_name: str) -> dict | None:
        """Min/max metadata for a single data column (one pass over rows)."""
        if header_name not in self._bounds_data_headers():
            return None
        return self._scan_numeric_column(self._rows, header_name)

    def refresh_numeric_bounds_for_headers(self, headers: list[str]) -> None:
        """Update cached min/max for specific columns only (avoids rescanning the full table)."""
        if not headers:
            return
        targets = [h for h in headers if h in self._bounds_data_headers()]
        if not targets:
            return
        if self._numeric_bounds_cache is None:
            self._numeric_bounds_cache = {}
            self._numeric_bounds_dirty_cols = set()
        self._numeric_bounds_key = tuple(self._sorted_bounds_data_headers())
        for h in targets:
            meta = self._scan_numeric_column(self._rows, h)
            if meta is not None:
                self._numeric_bounds_cache[h] = meta
            else:
                self._numeric_bounds_cache.pop(h, None)
        if self._numeric_bounds_dirty_cols is not None:
            self._numeric_bounds_dirty_cols -= set(targets)

    @staticmethod
    def _scan_numeric_column(rows: list[_Row], h: str) -> dict | None:
        return CompoundTableModel.merge_numeric_bounds_rows(rows, h, 0, len(rows), None)

    @staticmethod
    def merge_numeric_bounds_rows(
        rows: list[_Row],
        h: str,
        start_row: int,
        end_row: int,
        acc: dict | None,
    ) -> dict | None:
        """Merge numeric min/max for ``rows[start_row:end_row]`` into *acc*."""
        lo = acc.get("min") if acc else None
        hi = acc.get("max") if acc else None
        int_ok = bool(acc.get("is_int", True)) if acc else True
        start = max(0, int(start_row))
        end = min(len(rows), int(end_row))
        for row in rows[start:end]:
            f = safe_float(row.values.get(h, ""))
            if f is None:
                continue
            fv = float(f)
            if lo is None:
                lo = hi = fv
                int_ok = f.is_integer()
            else:
                if fv < lo:
                    lo = fv
                if fv > hi:
                    hi = fv
                if not f.is_integer():
                    int_ok = False
        if lo is None:
            return None
        return {"min": lo, "max": hi, "is_int": int_ok}

    def list_bounds_data_headers(self) -> list[str]:
        return self._sorted_bounds_data_headers()

    def merge_numeric_bounds_chunk(
        self,
        header: str,
        start_row: int,
        end_row: int,
        acc: dict | None,
    ) -> dict | None:
        return self.merge_numeric_bounds_rows(self._rows, header, start_row, end_row, acc)

    def install_numeric_bounds_cache(self, cache: dict[str, dict]) -> None:
        self._numeric_bounds_cache = dict(cache)
        self._numeric_bounds_key = tuple(self._sorted_bounds_data_headers())
        self._numeric_bounds_dirty_cols = set()

    def pending_color_cache_headers(self) -> list[str]:
        if not self._column_color_rules:
            return []
        return [h for h in self._column_color_rules if h not in self._pixmap_columns]

    def _full_numeric_bounds_scan(self) -> dict[str, dict]:
        data_headers = sorted(
            h
            for h in self._headers[2:]
            if h not in ("ID_HIDDEN", "Structure")
            and h not in self._pixmap_columns
            and h not in _NON_NUMERIC_BLOB_COLUMNS
        )
        if not data_headers:
            return {}
        out: dict[str, dict] = {}
        for h in data_headers:
            meta = self._scan_numeric_column(self._rows, h)
            if meta is not None:
                out[h] = meta
        return out

    def numeric_bounds_by_column(self) -> dict[str, dict]:
        """Numeric min/max per data column for filter sliders.

        Maintains a cache and only rescans columns touched since the last call when possible.
        """
        data_headers = sorted(
            h
            for h in self._headers[2:]
            if h not in ("ID_HIDDEN", "Structure")
            and h not in self._pixmap_columns
            and h not in _NON_NUMERIC_BLOB_COLUMNS
        )
        key = tuple(data_headers)
        if not data_headers:
            self._invalidate_numeric_bounds_all()
            return {}

        if self._numeric_bounds_cache is None or self._numeric_bounds_key != key:
            self._numeric_bounds_cache = self._full_numeric_bounds_scan()
            self._numeric_bounds_key = key
            self._numeric_bounds_dirty_cols = set()
            return dict(self._numeric_bounds_cache)

        if not self._numeric_bounds_dirty_cols:
            return dict(self._numeric_bounds_cache)

        cache = self._numeric_bounds_cache
        for h in list(self._numeric_bounds_dirty_cols):
            if h not in key:
                continue
            meta = self._scan_numeric_column(self._rows, h)
            if meta is None:
                cache.pop(h, None)
            else:
                cache[h] = meta
        self._numeric_bounds_dirty_cols = set()
        return dict(cache)

    def set_cell_text_at(self, row: int, col: int, text: str) -> None:
        if row < 0 or row >= len(self._rows) or col < 2 or col >= len(self._headers):
            return
        h = self._headers[col]
        if h in self._pixmap_columns:
            return
        self._rows[row].values[h] = str(text)
        self._refresh_color_cache_for_cell(self._rows[row], h, str(text))
        if h in self._bounds_data_headers():
            self._mark_numeric_bounds_dirty({h})
        idx = self.index(row, col)
        self.dataChanged.emit(idx, idx, [Qt.DisplayRole, Qt.EditRole, Qt.BackgroundRole])

    def column_text_by_oid(self, header_name: str) -> dict[int, str]:
        """Snapshot one text column as ``{oid: value}`` (fast path for undo / bulk ops)."""
        if header_name in ("ID_HIDDEN", "Structure") or header_name in self._pixmap_columns:
            return {}
        out: dict[int, str] = {}
        for row in self._rows:
            out[row.oid] = str(row.values.get(header_name, ""))
        return out

    def duplicate_column_at(
        self,
        dest_col: int,
        header_name: str,
        src_logical: int,
        *,
        value_by_oid: dict[int, str] | None = None,
        pixmap_by_oid: dict[int, QPixmap] | None = None,
        as_pixmap: bool = False,
    ) -> None:
        """Insert a column and bulk-copy values from *src_logical* with one model notification.

        ``value_by_oid`` / ``pixmap_by_oid`` override the source cells (used when
        duplicating Structure, which does not store SMILES in ``row.values``).
        Pixmap source columns are copied as pixmap columns unless *as_pixmap* is
        forced on for Structure.
        """
        n = len(self._headers)
        if dest_col < 0 or dest_col > n or src_logical < 0 or src_logical >= n:
            return
        src_key = self._headers[src_logical]
        src_is_pixmap = src_key in self._pixmap_columns
        copy_as_pixmap = bool(as_pixmap) or src_is_pixmap
        self.beginInsertColumns(QModelIndex(), dest_col, dest_col)
        self._headers.insert(dest_col, header_name)
        for row in self._rows:
            if value_by_oid is not None:
                row.values[header_name] = str(value_by_oid.get(int(row.oid), "") or "")
            else:
                row.values[header_name] = str(row.values.get(src_key, "") or "")
        if src_key in self._column_color_rules:
            self._column_color_rules[header_name] = self._column_color_rules[src_key]
            self._rebuild_column_color_cache(header_name)
        if copy_as_pixmap:
            self._pixmap_columns.add(header_name)
            if pixmap_by_oid:
                for oid, pm in pixmap_by_oid.items():
                    if pm is not None and not pm.isNull():
                        self._extra_pixmaps[(int(oid), header_name)] = QPixmap(pm)
            elif src_is_pixmap:
                for (oid, h), pm in list(self._extra_pixmaps.items()):
                    if h == src_key and pm is not None and not pm.isNull():
                        self._extra_pixmaps[(oid, header_name)] = QPixmap(pm)
        self._mark_headers_added_for_bounds([header_name])
        self.endInsertColumns()
        if self._rows:
            roles = [Qt.DisplayRole, Qt.EditRole, Qt.BackgroundRole]
            if copy_as_pixmap:
                roles.extend([Qt.DecorationRole, Qt.SizeHintRole, Qt.ToolTipRole])
            self.dataChanged.emit(
                self.index(0, dest_col),
                self.index(len(self._rows) - 1, dest_col),
                roles,
            )

    def _emit_data_changed_row_spans(
        self,
        rows_changed: list[int],
        lo_col: int,
        hi_col: int,
        *,
        roles: list | None = None,
    ) -> None:
        """Notify the view only for changed rows (merged ranges), not the whole table."""
        if not rows_changed or not self._rows:
            return
        if roles is None:
            roles = [Qt.DisplayRole, Qt.EditRole, Qt.BackgroundRole]
        n = len(self._rows)
        unique = sorted({int(r) for r in rows_changed if 0 <= int(r) < n})
        if not unique:
            return
        if len(unique) >= max(1, int(n * 0.85)):
            self.dataChanged.emit(self.index(0, lo_col), self.index(n - 1, hi_col), roles)
            return
        i = 0
        while i < len(unique):
            lo_r = hi_r = unique[i]
            while i + 1 < len(unique) and unique[i + 1] == hi_r + 1:
                i += 1
                hi_r = unique[i]
            self.dataChanged.emit(self.index(lo_r, lo_col), self.index(hi_r, hi_col), roles)
            i += 1

    def set_column_text_by_oids(self, column_name: str, oid_values: list[tuple[int, str]]) -> None:
        """Set one text column for many molecule ids; batch ``dataChanged`` (contiguous row runs)."""
        if (
            not oid_values
            or column_name in ("ID_HIDDEN", "Structure")
            or column_name in self._pixmap_columns
        ):
            return
        try:
            col = self._headers.index(column_name)
        except ValueError:
            return
        rows_changed: list[int] = []
        for oid, text in oid_values:
            r = self.logical_row_for_oid(oid)
            if r < 0:
                continue
            text_s = str(text)
            self._rows[r].values[column_name] = text_s
            self._refresh_color_cache_for_cell(self._rows[r], column_name, text_s)
            rows_changed.append(r)
        if not rows_changed:
            return
        if column_name in self._bounds_data_headers():
            self._mark_numeric_bounds_dirty({column_name})
        self._emit_data_changed_row_spans(rows_changed, col, col)

    def apply_columns_values_bulk(
        self,
        column_names: list[str],
        oid_value_rows: list[tuple[int, dict[str, str]]],
        *,
        emit: bool = True,
    ) -> None:
        """Fill several columns for many rows; one ``dataChanged`` for the affected column block."""
        if not column_names or not oid_value_rows:
            return
        cols: list[int] = []
        col_set: set[str] = set()
        for header_name in column_names:
            if header_name in ("ID_HIDDEN", "Structure") or header_name in self._pixmap_columns:
                continue
            try:
                cols.append(self._headers.index(header_name))
                col_set.add(header_name)
            except ValueError:
                continue
        if not cols or not col_set:
            return
        colored_cols = [h for h in col_set if h in self._column_color_rules]
        from ..config import load_config

        defer_color = len(oid_value_rows) >= int(load_config().bulk_update_defer_color_cache_rows)
        rows_changed: list[int] = []
        for oid, row_d in oid_value_rows:
            r = self._oid_to_row.get(int(oid), -1)
            if r < 0 or r >= len(self._rows):
                continue
            row_obj = self._rows[r]
            for header_name in col_set:
                if header_name not in row_d:
                    continue
                row_obj.values[header_name] = str(row_d[header_name])
            rows_changed.append(r)
        if defer_color:
            for header_name in colored_cols:
                self._column_color_cache.pop(header_name, None)
        else:
            for header_name in colored_cols:
                self._rebuild_column_color_cache(header_name)
        dirty_bounds = {h for h in col_set if h in self._bounds_data_headers()}
        if dirty_bounds:
            self._mark_numeric_bounds_dirty(dirty_bounds)
        if emit and rows_changed and cols:
            roles = [Qt.DisplayRole, Qt.EditRole]
            if not defer_color:
                roles.append(Qt.BackgroundRole)
            self._emit_data_changed_row_spans(rows_changed, min(cols), max(cols), roles=roles)

    def fill_column_from_oid_map(
        self,
        column_name: str,
        oid_to_text: dict[int, str],
        *,
        default: str = "",
        emit: bool = True,
    ) -> None:
        """
        Set one column for every row in a single pass (for sparse maps + default fill).

        Used when most rows share a default (e.g. fingerprint similarity ``N/A``).
        """
        if column_name in ("ID_HIDDEN", "Structure") or column_name in self._pixmap_columns:
            return
        try:
            col = self._headers.index(column_name)
        except ValueError:
            return
        for row in self._rows:
            row.values[column_name] = oid_to_text.get(row.oid, default)
        if column_name in self._column_color_rules:
            self._rebuild_column_color_cache(column_name)
        if column_name in self._bounds_data_headers():
            self._mark_numeric_bounds_dirty({column_name})
        if emit and self._rows:
            self.dataChanged.emit(
                self.index(0, col),
                self.index(len(self._rows) - 1, col),
                [Qt.DisplayRole, Qt.EditRole, Qt.BackgroundRole],
            )

    def insert_columns_at(
        self, col: int, header_names: list[str], copy_from_logical: int | None = None
    ) -> None:
        """Insert multiple headers in one model notification (large tables)."""
        if not header_names:
            return
        n = len(self._headers)
        if col < 0 or col > n:
            return
        copy_key = None
        if copy_from_logical is not None and 0 <= copy_from_logical < n:
            copy_key = self._headers[copy_from_logical]
        last = col + len(header_names) - 1
        self.beginInsertColumns(QModelIndex(), col, last)
        for i, header_name in enumerate(header_names):
            self._headers.insert(col + i, header_name)
        if copy_key is not None:
            for header_name in header_names:
                for row in self._rows:
                    row.values[header_name] = row.values.get(copy_key, "")
                if copy_key in self._column_color_rules:
                    self._column_color_rules[header_name] = self._column_color_rules[copy_key]
                    self._rebuild_column_color_cache(header_name)
        self._mark_headers_added_for_bounds(header_names)
        self.endInsertColumns()

    def insert_column_at(
        self, col: int, header_name: str, copy_from_logical: int | None = None
    ) -> None:
        n = len(self._headers)
        if col < 0 or col > n:
            return
        copy_key = None
        if copy_from_logical is not None and 0 <= copy_from_logical < n:
            copy_key = self._headers[copy_from_logical]
        self.beginInsertColumns(QModelIndex(), col, col)
        self._headers.insert(col, header_name)
        if copy_key is not None:
            for row in self._rows:
                row.values[header_name] = row.values.get(copy_key, "")
            if copy_key in self._column_color_rules:
                self._column_color_rules[header_name] = self._column_color_rules[copy_key]
                self._rebuild_column_color_cache(header_name)
            self._invalidate_numeric_bounds_all()
        else:
            self._mark_headers_added_for_bounds([header_name])
        self.endInsertColumns()

    def remove_column_at(self, col: int) -> None:
        if col < 0 or col >= len(self._headers):
            return
        h = self._headers[col]
        if h in self._pixmap_columns:
            self._pixmap_columns.discard(h)
            for k in [x for x in self._extra_pixmaps if x[1] == h]:
                del self._extra_pixmaps[k]
        self._column_color_rules.pop(h, None)
        self._column_color_cache.pop(h, None)
        self.beginRemoveColumns(QModelIndex(), col, col)
        self._headers.pop(col)
        if col >= 2:
            for row in self._rows:
                row.values.pop(h, None)
        self._mark_header_removed_for_bounds(h)
        self.endRemoveColumns()

    def rename_header_at(self, col: int, new_name: str) -> None:
        if col < 0 or col >= len(self._headers) or self._headers[col] == new_name:
            return
        old = self._headers[col]
        self._headers[col] = new_name
        if old in self._column_color_rules:
            self._column_color_rules[new_name] = self._column_color_rules.pop(old)
        if old in self._column_color_cache:
            self._column_color_cache[new_name] = self._column_color_cache.pop(old)
        if col >= 2 and old in self._pixmap_columns:
            self._pixmap_columns.discard(old)
            self._pixmap_columns.add(new_name)
            for row in self._rows:
                oid = row.oid
                kk = (oid, old)
                if kk in self._extra_pixmaps:
                    self._extra_pixmaps[(oid, new_name)] = self._extra_pixmaps.pop(kk)
        if col >= 2:
            for row in self._rows:
                if old in row.values:
                    row.values[new_name] = row.values.pop(old)
        self.headerDataChanged.emit(Qt.Horizontal, col, col)
        c0 = self.index(0, col)
        c1 = self.index(max(len(self._rows) - 1, 0), col)
        self.dataChanged.emit(c0, c1, [Qt.DisplayRole, Qt.EditRole, Qt.BackgroundRole])
        self._invalidate_numeric_bounds_all()

    def clear_column_coloring(self, header_name: str) -> None:
        """Disable background coloring for one column."""
        self._column_color_rules.pop(header_name, None)
        self._column_color_cache.pop(header_name, None)
        self._emit_color_refresh_for_header(header_name)

    def set_column_color_numeric_gradient(
        self,
        header_name: str,
        *,
        min_value: float,
        max_value: float,
        low_color: QColor,
        high_color: QColor,
        alpha: int = 96,
    ) -> None:
        """Color a data column by numeric value mapped onto a two-color gradient."""
        if header_name not in self._headers or header_name in ("ID_HIDDEN", "Structure"):
            return
        if header_name in self._pixmap_columns:
            return
        lo = float(min(min_value, max_value))
        hi = float(max(min_value, max_value))
        a = max(20, min(int(alpha), 255))
        self._column_color_rules[header_name] = _ColumnColorRule(
            mode="numeric",
            min_value=lo,
            max_value=hi,
            low_rgb=QColor(low_color).rgb(),
            high_rgb=QColor(high_color).rgb(),
            alpha=a,
        )
        self._rebuild_column_color_cache(header_name)
        self._emit_color_refresh_for_header(header_name)

    def set_column_color_three_point_gradient(
        self,
        header_name: str,
        *,
        min_value: float,
        mid_value: float,
        max_value: float,
        low_color: QColor,
        mid_color: QColor,
        high_color: QColor,
        alpha: int = 96,
    ) -> None:
        """Color numeric values with low/mid/high anchors."""
        if header_name not in self._headers or header_name in ("ID_HIDDEN", "Structure"):
            return
        if header_name in self._pixmap_columns:
            return
        lo = float(min_value)
        mid = float(mid_value)
        hi = float(max_value)
        if hi < lo:
            lo, hi = hi, lo
        mid = max(lo, min(mid, hi))
        a = max(20, min(int(alpha), 255))
        self._column_color_rules[header_name] = _ColumnColorRule(
            mode="numeric3",
            min_value=lo,
            mid_value=mid,
            max_value=hi,
            low_rgb=QColor(low_color).rgb(),
            mid_rgb=QColor(mid_color).rgb(),
            high_rgb=QColor(high_color).rgb(),
            alpha=a,
        )
        self._rebuild_column_color_cache(header_name)
        self._emit_color_refresh_for_header(header_name)

    def apply_favorable_score_column_coloring(self, header_name: str) -> bool:
        """Color QED / AB-MPS / CNS MPO columns green (favorable) → yellow → red."""
        spec = favorable_score_color_spec(header_name)
        if spec is None:
            return False
        green = QColor(*COLOR_FAVORABLE_RGB)
        yellow = QColor(*COLOR_MID_RGB)
        red = QColor(*COLOR_UNFAVORABLE_RGB)
        if spec.higher_is_better:
            low_color, mid_color, high_color = red, yellow, green
        else:
            low_color, mid_color, high_color = green, yellow, red
        self.set_column_color_three_point_gradient(
            header_name,
            min_value=spec.min_value,
            mid_value=spec.mid_value,
            max_value=spec.max_value,
            low_color=low_color,
            mid_color=mid_color,
            high_color=high_color,
            alpha=COLOR_ALPHA,
        )
        return self.column_color_mode(header_name) == "numeric3"

    def set_column_color_categorical(self, header_name: str, *, alpha: int = 88) -> None:
        """Color non-empty distinct text values using a deterministic categorical palette."""
        if header_name not in self._headers or header_name in ("ID_HIDDEN", "Structure"):
            return
        if header_name in self._pixmap_columns:
            return
        a = max(20, min(int(alpha), 255))
        self._column_color_rules[header_name] = _ColumnColorRule(mode="categorical", alpha=a)
        self._rebuild_column_color_cache(header_name)
        self._emit_color_refresh_for_header(header_name)

    def column_color_mode(self, header_name: str) -> str:
        rule = self._column_color_rules.get(header_name)
        return "" if rule is None else rule.mode

    def column_color_rule_spec(self, header_name: str) -> dict | None:
        rule = self._column_color_rules.get(header_name)
        if rule is None:
            return None
        out = {
            "mode": rule.mode,
            "alpha": int(rule.alpha),
        }
        if rule.mode in {"numeric", "numeric3"}:
            out["min"] = float(rule.min_value)
            out["max"] = float(rule.max_value)
            out["low_rgb"] = int(rule.low_rgb)
            out["high_rgb"] = int(rule.high_rgb)
        if rule.mode == "numeric3":
            out["mid"] = float(rule.mid_value)
            out["mid_rgb"] = int(rule.mid_rgb)
        return out

    def export_column_color_rules(self) -> dict[str, dict]:
        out: dict[str, dict] = {}
        for header in sorted(self._column_color_rules.keys()):
            spec = self.column_color_rule_spec(header)
            if spec is not None:
                out[header] = spec
        return out

    def restore_column_color_rules(self, spec_by_header: dict) -> None:
        if not isinstance(spec_by_header, dict):
            return
        for header_name, spec in spec_by_header.items():
            if not isinstance(header_name, str) or not isinstance(spec, dict):
                continue
            mode = str(spec.get("mode") or "")
            if mode == "numeric":
                self.set_column_color_numeric_gradient(
                    header_name,
                    min_value=float(spec.get("min", 0.0)),
                    max_value=float(spec.get("max", 1.0)),
                    low_color=QColor.fromRgb(int(spec.get("low_rgb", QColor(48, 119, 242).rgb()))),
                    high_color=QColor.fromRgb(int(spec.get("high_rgb", QColor(236, 73, 73).rgb()))),
                    alpha=int(spec.get("alpha", 96)),
                )
            elif mode == "numeric3":
                self.set_column_color_three_point_gradient(
                    header_name,
                    min_value=float(spec.get("min", 0.0)),
                    mid_value=float(spec.get("mid", 0.5)),
                    max_value=float(spec.get("max", 1.0)),
                    low_color=QColor.fromRgb(int(spec.get("low_rgb", QColor(48, 119, 242).rgb()))),
                    mid_color=QColor.fromRgb(int(spec.get("mid_rgb", QColor(245, 209, 84).rgb()))),
                    high_color=QColor.fromRgb(int(spec.get("high_rgb", QColor(236, 73, 73).rgb()))),
                    alpha=int(spec.get("alpha", 96)),
                )
            elif mode == "categorical":
                self.set_column_color_categorical(header_name, alpha=int(spec.get("alpha", 88)))

    def _emit_color_refresh_for_header(self, header_name: str) -> None:
        if header_name not in self._headers:
            return
        n = len(self._rows)
        if n <= 0:
            return
        col = self._headers.index(header_name)
        self.dataChanged.emit(self.index(0, col), self.index(n - 1, col), [Qt.BackgroundRole])

    def _refresh_color_cache_for_cell(self, row_obj: _Row, header_name: str, value: str) -> None:
        rule = self._column_color_rules.get(header_name)
        if rule is None:
            return
        cmap = self._column_color_cache.setdefault(header_name, {})
        rgb = self._color_rgb_for_value(rule, value)
        if rgb is None:
            cmap.pop(row_obj.oid, None)
        else:
            cmap[row_obj.oid] = rgb

    def _refresh_color_cache_for_row(self, row_obj: _Row, row_cells: dict[str, str]) -> None:
        if not self._column_color_rules:
            return
        for header_name in self._column_color_rules:
            if header_name in self._pixmap_columns:
                continue
            val = row_cells.get(header_name, "")
            self._refresh_color_cache_for_cell(row_obj, header_name, val)

    def _rebuild_column_color_cache(self, header_name: str) -> None:
        rule = self._column_color_rules.get(header_name)
        if rule is None:
            self._column_color_cache.pop(header_name, None)
            return
        cmap: dict[int, int] = {}
        for row in self._rows:
            rgb = self._color_rgb_for_value(rule, row.values.get(header_name, ""))
            if rgb is not None:
                cmap[row.oid] = rgb
        self._column_color_cache[header_name] = cmap

    @staticmethod
    def _lerp_channel(c0: int, c1: int, t: float) -> int:
        return int(round(c0 + (c1 - c0) * t))

    def _color_rgb_for_value(self, rule: _ColumnColorRule, raw_value: str) -> int | None:
        txt = (raw_value or "").strip()
        if not txt:
            return None
        if rule.mode == "numeric":
            f = safe_float(txt)
            if f is None:
                return None
            lo = rule.min_value
            hi = rule.max_value
            if hi <= lo:
                t = 0.5
            else:
                t = (float(f) - lo) / (hi - lo)
            t = max(0.0, min(1.0, t))
            c0 = QColor.fromRgb(rule.low_rgb)
            c1 = QColor.fromRgb(rule.high_rgb)
            return QColor(
                self._lerp_channel(c0.red(), c1.red(), t),
                self._lerp_channel(c0.green(), c1.green(), t),
                self._lerp_channel(c0.blue(), c1.blue(), t),
                rule.alpha,
            ).rgba()
        if rule.mode == "numeric3":
            f = safe_float(txt)
            if f is None:
                return None
            lo = rule.min_value
            mid = max(lo, min(rule.mid_value, rule.max_value))
            hi = rule.max_value
            fv = float(f)
            if hi <= lo:
                c = QColor.fromRgb(rule.mid_rgb or rule.low_rgb)
                return QColor(c.red(), c.green(), c.blue(), rule.alpha).rgba()
            if fv <= mid:
                span = max(mid - lo, 1e-12)
                t = max(0.0, min(1.0, (fv - lo) / span))
                c0 = QColor.fromRgb(rule.low_rgb)
                c1 = QColor.fromRgb(rule.mid_rgb or rule.high_rgb)
            else:
                span = max(hi - mid, 1e-12)
                t = max(0.0, min(1.0, (fv - mid) / span))
                c0 = QColor.fromRgb(rule.mid_rgb or rule.low_rgb)
                c1 = QColor.fromRgb(rule.high_rgb)
            return QColor(
                self._lerp_channel(c0.red(), c1.red(), t),
                self._lerp_channel(c0.green(), c1.green(), t),
                self._lerp_channel(c0.blue(), c1.blue(), t),
                rule.alpha,
            ).rgba()
        if rule.mode == "categorical":
            hue = zlib.crc32(txt.encode("utf-8", errors="ignore")) % 360
            return QColor.fromHsl(int(hue), 140, 215, rule.alpha).rgba()
        return None

    def moveRow(
        self,
        sourceParent: QModelIndex,
        sourceRow: int,
        destinationParent: QModelIndex,
        destinationChild: int,
    ) -> bool:  # noqa: N802
        if sourceParent.isValid() or destinationParent.isValid():
            return False
        n = len(self._rows)
        if sourceRow < 0 or sourceRow >= n or destinationChild < 0 or destinationChild > n:
            return False
        if sourceRow == destinationChild:
            return True
        self.beginMoveRows(QModelIndex(), sourceRow, sourceRow, QModelIndex(), destinationChild)
        row = self._rows.pop(sourceRow)
        if destinationChild > sourceRow:
            self._rows.insert(destinationChild, row)
        else:
            self._rows.insert(destinationChild, row)
        self.endMoveRows()
        self._rebuild_oid_index()
        return True


class StructureDelegate(QStyledItemDelegate):
    """Paints cached structure pixmap or a neutral placeholder."""

    def __init__(self, parent=None, compound_model: CompoundTableModel | None = None):
        super().__init__(parent)
        self._cell_background: QColor | None = QColor(255, 255, 255)
        self._compound_model = compound_model

    def set_compound_model(self, compound_model: CompoundTableModel | None) -> None:
        self._compound_model = compound_model

    def set_cell_background(self, color: QColor | None) -> None:
        """Cell fill color; ``None`` falls back to white for legacy callers."""
        self._cell_background = color

    def _cell_has_structure_pixmap(self, index) -> bool:
        pix = index.data(Qt.DecorationRole)
        return isinstance(pix, QPixmap) and not pix.isNull()

    def _fill_cell_background(
        self,
        painter,
        opt: QStyleOptionViewItem,
        index,
        *,
        has_rendered_structure: bool = False,
    ) -> None:
        from .table_selection_delegate import source_row_for_view_index

        row = source_row_for_view_index(index, self._compound_model) if self._compound_model else -1
        if (
            self._compound_model is not None
            and row >= 0
            and self._compound_model.is_row_highlighted(row)
        ):
            pal = QApplication.palette() if QApplication.instance() else opt.palette
            painter.fillRect(opt.rect, pal.color(QPalette.Highlight))
            return
        if has_rendered_structure:
            painter.fillRect(opt.rect, QColor(255, 255, 255))
            return
        bg = self._cell_background if self._cell_background is not None else QColor(255, 255, 255)
        painter.fillRect(opt.rect, bg)

    def paint(self, painter, option, index):  # noqa: N802
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        has_pix = self._cell_has_structure_pixmap(index)
        self._fill_cell_background(painter, opt, index, has_rendered_structure=has_pix)
        pix = index.data(Qt.DecorationRole) if has_pix else None
        if has_pix:
            r = opt.rect
            x = r.x() + (r.width() - pix.width()) // 2
            y = r.y() + (r.height() - pix.height()) // 2
            painter.drawPixmap(x, y, pix)
        else:
            hint = index.data(Qt.DisplayRole)
            text = hint if isinstance(hint, str) and hint.strip() else "—"
            painter.save()
            painter.setFont(opt.font)
            from .table_selection_delegate import source_row_for_view_index

            row = (
                source_row_for_view_index(index, self._compound_model)
                if self._compound_model
                else -1
            )
            if (
                self._compound_model is not None
                and row >= 0
                and self._compound_model.is_row_highlighted(row)
            ):
                pal = QApplication.palette() if QApplication.instance() else opt.palette
                painter.setPen(pal.color(QPalette.HighlightedText))
            else:
                painter.setPen(opt.palette.text().color())
            margin = 6
            r = QRect(
                opt.rect.x() + margin,
                opt.rect.y() + margin,
                max(1, opt.rect.width() - 2 * margin),
                max(1, opt.rect.height() - 2 * margin),
            )
            painter.drawText(r, int(Qt.AlignCenter | Qt.TextWordWrap), text)
            painter.restore()

    def sizeHint(self, option, index):  # noqa: N802
        sh = super().sizeHint(option, index)
        pix = index.data(Qt.DecorationRole)
        if isinstance(pix, QPixmap) and not pix.isNull():
            return QSize(max(sh.width(), pix.width() + 8), max(sh.height(), pix.height() + 8))
        return QSize(structure_depiict_width(), max(sh.height(), structure_depiict_height()))


class CompoundTableView(QTableView):
    """
    QTableView pre-wired for ``CompoundTableModel`` + structure delegate.
    Call ``set_compound_model`` after construction.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlternatingRowColors(True)
        self.setSelectionBehavior(QTableView.SelectItems)
        self.setSelectionMode(QTableView.ExtendedSelection)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.verticalHeader().setDefaultSectionSize(structure_row_default_height())
        self.verticalHeader().setSectionsMovable(True)
        self.verticalHeader().setDefaultAlignment(Qt.AlignCenter)
        hh = self.horizontalHeader()
        hh.setSectionsMovable(True)
        hh.setFirstSectionMovable(False)
        hh.setSectionResizeMode(QHeaderView.Interactive)
        self.setSortingEnabled(False)
        self._compound_model: CompoundTableModel | None = None
        self._structure_column_min_width = structure_column_minimum_width()
        hh.sectionResized.connect(self._on_horizontal_section_resized)

    def structure_column_minimum_width(self) -> int:
        return self._structure_column_min_width

    def _column_is_structure_sized(self, logical_index: int) -> bool:
        """True for Structure and 2D pixmap columns that share its depiction size."""
        if logical_index == CompoundTableModel.STRUCTURE_COL:
            return True
        model = self._compound_model
        if model is None:
            return False
        headers = getattr(model, "_headers", ())
        if logical_index < 0 or logical_index >= len(headers):
            return False
        return bool(model.is_pixmap_data_column(headers[logical_index]))

    def set_structure_column_minimum_width(self, width: int) -> None:
        """Keep Structure and 2D pixmap columns at least wide enough for depictions."""
        w = max(1, int(width))
        if w == self._structure_column_min_width:
            return
        self._structure_column_min_width = w
        hh = self.horizontalHeader()
        hh.blockSignals(True)
        try:
            model = self._compound_model
            n = model.columnCount() if model is not None else 0
            if n <= 0:
                n = 2
            for col in range(n):
                if not self._column_is_structure_sized(col):
                    continue
                if self.columnWidth(col) < w:
                    self.setColumnWidth(col, w)
        finally:
            hh.blockSignals(False)

    def _on_horizontal_section_resized(
        self, logical_index: int, _old_size: int, new_size: int
    ) -> None:
        if not self._column_is_structure_sized(logical_index):
            return
        min_w = self._structure_column_min_width
        if new_size >= min_w:
            return
        hh = self.horizontalHeader()
        hh.blockSignals(True)
        try:
            self.setColumnWidth(logical_index, min_w)
        finally:
            hh.blockSignals(False)

    def set_compound_model(self, model: CompoundTableModel) -> None:
        self._compound_model = model
        self.setModel(model)
        self.setItemDelegateForColumn(CompoundTableModel.STRUCTURE_COL, StructureDelegate(self))
        if model.columnCount() > 0:
            self.setColumnHidden(0, True)

    def compound_model(self) -> CompoundTableModel | None:
        return self._compound_model


def run_table_model_demo() -> int:
    """Small window demonstrating the model + view + sort + pixmap update."""
    from PyQt5.QtWidgets import QApplication, QLabel, QMainWindow, QVBoxLayout, QWidget, QPushButton

    app = QApplication.instance() or QApplication([])

    headers = ["ID_HIDDEN", "Structure", "SMILES", "MW"]
    model = CompoundTableModel(headers)
    for i in range(8):
        smi = "C" * (i + 1)
        model.append_row(oid=100 + i, cells={"SMILES": smi, "MW": str(50 + i * 13)})

    w = QMainWindow()
    w.setWindowTitle("MolManager — QAbstractTableModel prototype")
    cw = QWidget()
    ly = QVBoxLayout(cw)
    view = CompoundTableView()
    view.set_compound_model(model)
    view.resizeColumnsToContents()
    ly.addWidget(
        QLabel(
            "Click a column header to select that column; Shift+click another header to select a range. "
            "Right-click the header for Sort (numeric or alphabetic). "
            "Structure column shows placeholders until you click the button."
        )
    )
    ly.addWidget(view)

    def fake_render():
        from PyQt5.QtGui import QColor, QPainter

        for oid in model.all_oids_in_order():
            pm = QPixmap(120, 90)
            pm.fill(QColor(240, 248, 255))
            p = QPainter(pm)
            p.setPen(Qt.darkGray)
            p.drawText(pm.rect(), Qt.AlignCenter, f"id {oid}")
            p.end()
            model.set_structure_pixmap(oid, pm)

    btn = QPushButton("Simulate 2D render (placeholder pixmap per row)")
    btn.clicked.connect(fake_render)
    ly.addWidget(btn)
    w.setCentralWidget(cw)
    w.resize(900, 520)
    w.show()
    return app.exec_()


if __name__ == "__main__":
    raise SystemExit(run_table_model_demo())
