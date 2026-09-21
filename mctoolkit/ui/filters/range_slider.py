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

"""Horizontal dual-handle range slider for numeric filter cards."""

from __future__ import annotations

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPaintEvent
from PySide6.QtWidgets import QSizePolicy, QWidget


class RangeSlider(QWidget):
    """Single groove with two knobs for inclusive min/max integer values."""

    lowerValueChanged = Signal(int)
    upperValueChanged = Signal(int)
    rangeChanged = Signal(int, int)
    sliderReleased = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._minimum = 0
        self._maximum = 100
        self._lower = 0
        self._upper = 100
        self._active: str | None = None  # "lower" | "upper"
        self._handle_r = 6
        self.setMinimumHeight(16)
        self.setFixedHeight(16)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setCursor(Qt.ArrowCursor)

    def minimum(self) -> int:
        return self._minimum

    def maximum(self) -> int:
        return self._maximum

    def lowerValue(self) -> int:
        return self._lower

    def upperValue(self) -> int:
        return self._upper

    def setRange(self, minimum: int, maximum: int) -> None:
        lo = int(minimum)
        hi = int(maximum)
        if hi < lo:
            lo, hi = hi, lo
        self._minimum = lo
        self._maximum = hi
        self._lower = max(lo, min(self._lower, hi))
        self._upper = max(self._lower, min(self._upper, hi))
        self.update()

    def setLowerValue(self, value: int) -> None:
        v = max(self._minimum, min(int(value), self._upper))
        if v == self._lower:
            return
        self._lower = v
        self.lowerValueChanged.emit(self._lower)
        self.rangeChanged.emit(self._lower, self._upper)
        self.update()

    def setUpperValue(self, value: int) -> None:
        v = min(self._maximum, max(int(value), self._lower))
        if v == self._upper:
            return
        self._upper = v
        self.upperValueChanged.emit(self._upper)
        self.rangeChanged.emit(self._lower, self._upper)
        self.update()

    def setValues(self, lower: int, upper: int) -> None:
        lo = max(self._minimum, min(int(lower), self._maximum))
        hi = max(self._minimum, min(int(upper), self._maximum))
        if lo > hi:
            lo, hi = hi, lo
        changed = lo != self._lower or hi != self._upper
        self._lower = lo
        self._upper = hi
        if changed:
            self.lowerValueChanged.emit(self._lower)
            self.upperValueChanged.emit(self._upper)
            self.rangeChanged.emit(self._lower, self._upper)
            self.update()

    def _span(self) -> int:
        return max(1, self._maximum - self._minimum)

    def _groove_rect(self):
        from PySide6.QtCore import QRect

        m = self._handle_r + 1
        y = self.height() // 2 - 1
        return QRect(m, y, max(1, self.width() - 2 * m), 3)

    def _x_for_value(self, value: int) -> int:
        groove = self._groove_rect()
        t = (value - self._minimum) / float(self._span())
        return int(round(groove.left() + t * groove.width()))

    def _value_for_x(self, x: int) -> int:
        groove = self._groove_rect()
        if groove.width() <= 0:
            return self._minimum
        t = (x - groove.left()) / float(groove.width())
        t = 0.0 if t < 0.0 else 1.0 if t > 1.0 else t
        return int(round(self._minimum + t * self._span()))

    def _handle_at(self, pos: QPoint) -> str | None:
        lx = self._x_for_value(self._lower)
        ux = self._x_for_value(self._upper)
        cy = self.height() // 2
        dl = (pos.x() - lx) ** 2 + (pos.y() - cy) ** 2
        du = (pos.x() - ux) ** 2 + (pos.y() - cy) ** 2
        hit_r2 = (self._handle_r + 4) ** 2
        if dl <= hit_r2 and du <= hit_r2:
            return "upper" if abs(pos.x() - ux) <= abs(pos.x() - lx) else "lower"
        if dl <= hit_r2:
            return "lower"
        if du <= hit_r2:
            return "upper"
        return None

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        del event
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        pal = self.palette()
        groove = self._groove_rect()

        p.setPen(Qt.NoPen)
        p.setBrush(pal.mid())
        p.drawRoundedRect(groove, 1, 1)

        x0 = self._x_for_value(self._lower)
        x1 = self._x_for_value(self._upper)
        if x1 > x0:
            from PySide6.QtCore import QRect

            sel = QRect(x0, groove.top(), max(1, x1 - x0), groove.height())
            p.setBrush(pal.highlight())
            p.drawRoundedRect(sel, 1, 1)

        for x in (x0, x1):
            p.setBrush(pal.highlight())
            p.setPen(pal.dark().color())
            p.drawEllipse(QPoint(x, self.height() // 2), self._handle_r, self._handle_r)
            # Soft rim so knobs stay visible on the selected track.
            rim = QColor(pal.highlightedText().color())
            rim.setAlpha(40)
            p.setPen(rim)
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(QPoint(x, self.height() // 2), self._handle_r, self._handle_r)
        p.end()

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() != Qt.LeftButton:
            return
        handle = self._handle_at(event.pos())
        if handle is None:
            # Click on groove: move nearest knob.
            v = self._value_for_x(event.pos().x())
            if abs(v - self._lower) <= abs(v - self._upper):
                handle = "lower"
                self.setLowerValue(v)
            else:
                handle = "upper"
                self.setUpperValue(v)
        self._active = handle
        self.setCursor(Qt.SizeHorCursor)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._active is None:
            if self._handle_at(event.pos()) is not None:
                self.setCursor(Qt.SizeHorCursor)
            else:
                self.setCursor(Qt.ArrowCursor)
            return
        v = self._value_for_x(event.pos().x())
        if self._active == "lower":
            self.setLowerValue(v)
        else:
            self.setUpperValue(v)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() != Qt.LeftButton:
            return
        if self._active is not None:
            self._active = None
            self.setCursor(Qt.ArrowCursor)
            self.sliderReleased.emit()
