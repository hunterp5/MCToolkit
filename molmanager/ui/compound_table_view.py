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

"""QTableView stack for CompoundTableModel (delegate, header, view)."""

from __future__ import annotations

from PyQt5.QtCore import QRect, QSize, Qt
from PyQt5.QtGui import QColor, QPalette, QPixmap
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QHeaderView,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableView,
)

from ..display_constants import (
    structure_column_minimum_width,
    structure_depict_height,
    structure_depict_width,
    structure_row_default_height,
)

# Must match CompoundTableModel.STRUCTURE_COL
_STRUCTURE_COL = 1


class StructureDelegate(QStyledItemDelegate):
    """Paints cached structure pixmap or a neutral placeholder."""

    def __init__(self, parent=None, compound_model=None):
        super().__init__(parent)
        self._cell_background: QColor | None = QColor(255, 255, 255)
        self._compound_model = compound_model

    def set_compound_model(self, compound_model) -> None:
        self._compound_model = compound_model

    def set_cell_background(self, color: QColor | None) -> None:
        """Cell fill color; ``None`` falls back to white for legacy callers."""
        self._cell_background = color

    def _cell_has_structure_pixmap(self, index) -> bool:
        pix = index.data(Qt.DecorationRole)
        return isinstance(pix, QPixmap) and not pix.isNull()

    def _cell_is_selected(self, opt: QStyleOptionViewItem, index) -> bool:
        if opt.state & QStyle.State_Selected:
            return True
        from .table_selection_delegate import source_row_for_view_index

        if self._compound_model is None:
            return False
        row = source_row_for_view_index(index, self._compound_model)
        return row >= 0 and self._compound_model.is_row_highlighted(row)

    def _fill_cell_background(
        self,
        painter,
        opt: QStyleOptionViewItem,
        index,
        *,
        has_rendered_structure: bool = False,
    ) -> None:
        if self._cell_is_selected(opt, index):
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
            if self._cell_is_selected(opt, index):
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
            return QSize(max(sh.width(), pix.width()), max(sh.height(), pix.height()))
        return QSize(structure_depict_width(), max(sh.height(), structure_depict_height()))


def _header_grip_px(header: QHeaderView) -> int:
    """Pixel slop for a column resize grip, floored so the viewport edge stays hittable."""
    style = header.style()
    pm = 4
    if style is not None:
        raw = int(style.pixelMetric(QStyle.PM_HeaderGripMargin, None, header))
        if raw > 0:
            pm = raw
    return max(12, pm)


class CompoundTableHeaderView(QHeaderView):
    """Horizontal header that can still resize a column flush with the viewport edge.

    Qt's native grip sits on the section's true right border. When that border is at or
    past the visible edge, the handle is clipped and ScrollPerItem jumps the column away.
    Clicks on the last few pixels of the viewport resize the section under that edge.
    """

    def __init__(self, orientation=Qt.Horizontal, parent=None):
        super().__init__(orientation, parent)
        self.setSectionsMovable(True)
        self.setFirstSectionMovable(False)
        self.setSectionResizeMode(QHeaderView.Interactive)
        self.setStretchLastSection(False)
        self.setMouseTracking(True)
        self._edge_resize_logical = -1
        self._edge_resize_origin_x = 0
        self._edge_resize_origin_size = 0
        self.setStyleSheet("QHeaderView::section { padding-top: 1px; padding-bottom: 1px; }")
        vp = self.viewport()
        if vp is not None:
            vp.setMouseTracking(True)

    def section_for_viewport_right_grip(self, x: int) -> int:
        """Logical section resized by a click at ``x`` on the viewport's right edge, or -1."""
        vp = self.viewport()
        if vp is None:
            return -1
        vp_w = int(vp.width())
        grip = _header_grip_px(self)
        if vp_w <= 0 or int(x) < vp_w - grip:
            return -1
        logical = int(self.logicalIndexAt(max(0, vp_w - 1)))
        if logical < 0 or self.isSectionHidden(logical):
            return -1
        if self.sectionResizeMode(logical) != QHeaderView.Interactive:
            return -1
        right = int(self.sectionViewportPosition(logical)) + int(self.sectionSize(logical))
        if right < vp_w - grip:
            return -1
        return logical

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            logical = self.section_for_viewport_right_grip(event.pos().x())
            if logical >= 0:
                self._edge_resize_logical = logical
                self._edge_resize_origin_x = int(event.pos().x())
                self._edge_resize_origin_size = int(self.sectionSize(logical))
                self.setCursor(Qt.SplitHCursor)
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._edge_resize_logical >= 0:
            dx = int(event.pos().x()) - self._edge_resize_origin_x
            new_size = max(int(self.minimumSectionSize()), self._edge_resize_origin_size + dx)
            self.resizeSection(self._edge_resize_logical, new_size)
            self.setCursor(Qt.SplitHCursor)
            event.accept()
            return
        super().mouseMoveEvent(event)
        hovering_edge = (
            event.buttons() == Qt.NoButton
            and self.section_for_viewport_right_grip(event.pos().x()) >= 0
        )
        if hovering_edge:
            self.setCursor(Qt.SplitHCursor)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if self._edge_resize_logical >= 0:
            self._edge_resize_logical = -1
            self.unsetCursor()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        if self._edge_resize_logical < 0:
            self.unsetCursor()
        super().leaveEvent(event)


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
        self.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.verticalHeader().setDefaultSectionSize(structure_row_default_height())
        self.verticalHeader().setSectionsMovable(True)
        self.verticalHeader().setDefaultAlignment(Qt.AlignCenter)
        hh = CompoundTableHeaderView(Qt.Horizontal, self)
        self.setHorizontalHeader(hh)
        self.setSortingEnabled(False)
        self._compound_model = None
        self._structure_column_min_width = structure_column_minimum_width()
        hh.sectionResized.connect(self._on_horizontal_section_resized)

    def updateGeometries(self) -> None:  # noqa: N802
        super().updateGeometries()
        self._extend_horizontal_scroll_for_resize_grip()

    def _extend_horizontal_scroll_for_resize_grip(self) -> None:
        """Keep a few pixels of scroll past the last section so its right grip stays on-screen."""
        hh = self.horizontalHeader()
        bar = self.horizontalScrollBar()
        vp = self.viewport()
        if hh is None or bar is None or vp is None:
            return
        width = int(vp.width())
        length = int(hh.length())
        if width <= 0 or length <= 0:
            return
        grip = _header_grip_px(hh)
        needed_max = max(int(bar.maximum()), length - width + grip)
        if needed_max != int(bar.maximum()):
            bar.setRange(int(bar.minimum()), needed_max)

    def structure_column_minimum_width(self) -> int:
        return self._structure_column_min_width

    def _column_is_structure_sized(self, logical_index: int) -> bool:
        """True for Structure and 2D pixmap columns that share its depiction size."""
        if logical_index == _STRUCTURE_COL:
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

    def set_compound_model(self, model) -> None:
        self._compound_model = model
        self.setModel(model)
        self.setItemDelegateForColumn(_STRUCTURE_COL, StructureDelegate(self))
        if model.columnCount() > 0:
            self.setColumnHidden(0, True)

    def compound_model(self):
        return self._compound_model
