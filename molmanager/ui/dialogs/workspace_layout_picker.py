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

"""Graphic picker for main-window table/plot layout presets."""

from __future__ import annotations

from PyQt5.QtCore import QRectF, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QPainter, QPen
from PyQt5.QtWidgets import (
    QDialog,
    QGridLayout,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..qt_widget_utils import make_window_minimizable

_TILE_W = 200
_TILE_H = 150


class LayoutPreviewTile(QWidget):
    """Clickable schematic for one workspace layout preset."""

    chosen = pyqtSignal(str)

    def __init__(
        self,
        layout_id: str,
        label: str,
        *,
        selected: bool = False,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.layout_id = layout_id
        self._label = label
        self._selected = selected
        self._hovered = False
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMinimumSize(_TILE_W, _TILE_H + 28)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.setToolTip(f"Apply layout: {label}")

    def set_selected(self, selected: bool) -> None:
        self._selected = selected
        self.update()

    def enterEvent(self, event) -> None:  # noqa: N802 — Qt API
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802 — Qt API
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802 — Qt API
        if event.button() == Qt.LeftButton:
            self.chosen.emit(self.layout_id)
            event.accept()
            return
        super().mousePressEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802 — Qt API
        if event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            self.chosen.emit(self.layout_id)
            event.accept()
            return
        super().keyPressEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802 — Qt API
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        pal = self.palette()
        border = (
            pal.color(pal.Highlight) if (self._selected or self._hovered) else pal.color(pal.Mid)
        )
        width = 2.5 if (self._selected or self._hovered) else 1.0
        frame = QRectF(1.5, 1.5, self.width() - 3.0, self.height() - 3.0)
        painter.setPen(QPen(border, width))
        bg = pal.color(pal.Base)
        if self._hovered:
            bg = QColor(pal.color(pal.AlternateBase))
        painter.setBrush(bg)
        painter.drawRoundedRect(frame, 6, 6)

        diagram = QRectF(14, 12, self.width() - 28, self.height() - 44)
        self._paint_diagram(painter, diagram)

        painter.setPen(pal.color(pal.Text))
        font = QFont(self.font())
        font.setPointSize(max(9, font.pointSize()))
        painter.setFont(font)
        label_rect = QRectF(8, self.height() - 30, self.width() - 16, 24)
        painter.drawText(label_rect, Qt.AlignHCenter | Qt.AlignVCenter, self._label)

    def _paint_diagram(self, painter: QPainter, rect: QRectF) -> None:
        pal = self.palette()
        table = QColor(pal.color(pal.Button))
        plot = QColor(pal.color(pal.Highlight))
        plot.setAlpha(110)
        gap = 4.0
        painter.setPen(QPen(pal.color(pal.Mid), 1.0))

        def fill_rect(r: QRectF, color: QColor, text: str) -> None:
            painter.setBrush(color)
            painter.drawRoundedRect(r, 3, 3)
            painter.setPen(pal.color(pal.Text))
            f = QFont(self.font())
            f.setBold(True)
            f.setPointSize(max(8, f.pointSize() - 1))
            painter.setFont(f)
            painter.drawText(r, Qt.AlignCenter, text)
            painter.setPen(QPen(pal.color(pal.Mid), 1.0))

        lid = self.layout_id
        if lid == "table_only":
            fill_rect(rect, table, "Table")
            return
        if lid == "table_single":
            tw = rect.width() * 0.55
            fill_rect(QRectF(rect.left(), rect.top(), tw - gap / 2, rect.height()), table, "T")
            fill_rect(
                QRectF(
                    rect.left() + tw + gap / 2,
                    rect.top(),
                    rect.width() - tw - gap / 2,
                    rect.height(),
                ),
                plot,
                "Plot",
            )
            return
        if lid == "table_stack":
            tw = rect.width() * 0.5
            fill_rect(QRectF(rect.left(), rect.top(), tw - gap / 2, rect.height()), table, "T")
            pr = QRectF(
                rect.left() + tw + gap / 2, rect.top(), rect.width() - tw - gap / 2, rect.height()
            )
            hh = (pr.height() - gap) / 2
            fill_rect(QRectF(pr.left(), pr.top(), pr.width(), hh), plot, "P")
            fill_rect(QRectF(pr.left(), pr.top() + hh + gap, pr.width(), hh), plot, "P")
            return
        if lid == "table_side":
            tw = rect.width() * 0.4
            fill_rect(QRectF(rect.left(), rect.top(), tw - gap / 2, rect.height()), table, "T")
            pr = QRectF(
                rect.left() + tw + gap / 2, rect.top(), rect.width() - tw - gap / 2, rect.height()
            )
            ww = (pr.width() - gap) / 2
            fill_rect(QRectF(pr.left(), pr.top(), ww, pr.height()), plot, "P")
            fill_rect(QRectF(pr.left() + ww + gap, pr.top(), ww, pr.height()), plot, "P")
            return
        if lid == "quadrants":
            ww = (rect.width() - gap) / 2
            hh = (rect.height() - gap) / 2
            fill_rect(QRectF(rect.left(), rect.top(), ww, hh), table, "T")
            fill_rect(QRectF(rect.left() + ww + gap, rect.top(), ww, hh), plot, "P")
            fill_rect(QRectF(rect.left(), rect.top() + hh + gap, ww, hh), plot, "P")
            fill_rect(QRectF(rect.left() + ww + gap, rect.top() + hh + gap, ww, hh), plot, "P")
            return
        if lid == "table_grid":
            ww = (rect.width() - 2 * gap) / 3
            hh = (rect.height() - gap) / 2
            fill_rect(QRectF(rect.left(), rect.top(), ww, hh), table, "T")
            fill_rect(QRectF(rect.left() + ww + gap, rect.top(), ww, hh), plot, "P")
            fill_rect(QRectF(rect.left() + 2 * (ww + gap), rect.top(), ww, hh), plot, "P")
            y1 = rect.top() + hh + gap
            for col in range(3):
                fill_rect(
                    QRectF(rect.left() + col * (ww + gap), y1, ww, hh),
                    plot,
                    "P",
                )
            return
        fill_rect(rect, table, "?")


class WorkspaceLayoutPickerDialog(QDialog):
    """Window of clickable layout schematics; choosing one closes the dialog."""

    layout_chosen = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None, *, current_layout_id: str | None = None):
        super().__init__(parent)
        from ..main_window.workspace_layout import LAYOUT_PRESETS

        self.setWindowTitle("Workspace Layout")
        self.setModal(True)
        self.setWindowModality(Qt.WindowModal)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.resize(680, 420)
        make_window_minimizable(self)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        grid = QGridLayout()
        grid.setSpacing(12)
        self._tiles: list[LayoutPreviewTile] = []
        for i, (layout_id, label) in enumerate(LAYOUT_PRESETS):
            tile = LayoutPreviewTile(
                layout_id,
                label,
                selected=layout_id == current_layout_id,
                parent=self,
            )
            tile.chosen.connect(self._on_tile_chosen)
            self._tiles.append(tile)
            grid.addWidget(tile, i // 3, i % 3)
        root.addLayout(grid)
        root.addStretch(1)

    def _on_tile_chosen(self, layout_id: str) -> None:
        self.layout_chosen.emit(layout_id)
        self.accept()
