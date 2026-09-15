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

"""Rasterized footer glyphs and compact button styling."""

from __future__ import annotations

from PyQt5.QtCore import QPointF, QRectF, QSize, Qt
from PyQt5.QtGui import QIcon, QPainter, QPainterPath, QPalette, QPen, QPixmap
from PyQt5.QtWidgets import QLineEdit, QPushButton, QSizePolicy

from .dockable_plot_constants import (
    _FOOTER_TEXT_FONT_PX,
    _FOOTER_TEXT_PAD_H,
    _GLYPH_BTN_SIZE,
    _GLYPH_ICON_SIZE,
    _GLYPH_INK,
)


def _glyph_pen(width: float) -> QPen:
    pen = QPen(_GLYPH_INK, width)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    return pen


def _paint_glyph_icon(paint_fn, size: int = _GLYPH_ICON_SIZE) -> QIcon:
    """Rasterize a glyph with stroke inset so ink stays centered and unclipped."""
    dpr = 2.0
    pm = QPixmap(int(size * dpr), int(size * dpr))
    pm.fill(Qt.transparent)
    pm.setDevicePixelRatio(dpr)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.Antialiasing, True)
    # Inset by ~½ stroke so edge strokes are not clipped asymmetrically.
    pad = 1.0
    painter.translate(pad, pad)
    paint_fn(painter, float(size) - 2.0 * pad)
    painter.end()
    return QIcon(pm)


def plot_options_glyph_icon(size: int = _GLYPH_ICON_SIZE) -> QIcon:
    """Compact gear icon for Plot Options."""

    def paint(p: QPainter, s: float) -> None:
        p.setPen(_glyph_pen(max(1.5, s * 0.12)))
        p.setBrush(Qt.NoBrush)
        cx = cy = s * 0.5
        r = s * 0.24
        R = s * 0.42
        p.drawEllipse(QPointF(cx, cy), r, r)
        for i in range(8):
            ang = i * 45.0
            from math import cos, radians, sin

            a = radians(ang)
            x0 = cx + r * 1.3 * cos(a)
            y0 = cy + r * 1.3 * sin(a)
            x1 = cx + R * cos(a)
            y1 = cy + R * sin(a)
            p.drawLine(QPointF(x0, y0), QPointF(x1, y1))

    return _paint_glyph_icon(paint, size)


def send_to_window_glyph_icon(size: int = _GLYPH_ICON_SIZE) -> QIcon:
    """Single window with a pop-out arrow for Send to New Window."""

    def paint(p: QPainter, s: float) -> None:
        p.setPen(_glyph_pen(max(1.6, s * 0.13)))
        p.setBrush(Qt.NoBrush)
        box = QRectF(s * 0.06, s * 0.34, s * 0.52, s * 0.56)
        p.drawRect(box)
        title_y = box.top() + s * 0.15
        p.drawLine(QPointF(box.left(), title_y), QPointF(box.right(), title_y))
        tip = QPointF(s * 0.92, s * 0.08)
        p.drawLine(QPointF(s * 0.50, s * 0.50), tip)
        head = QPainterPath()
        head.moveTo(tip)
        head.lineTo(QPointF(s * 0.64, s * 0.08))
        head.lineTo(QPointF(s * 0.92, s * 0.36))
        head.closeSubpath()
        p.setPen(Qt.NoPen)
        p.setBrush(_GLYPH_INK)
        p.drawPath(head)

    return _paint_glyph_icon(paint, size)


def add_to_main_glyph_icon(size: int = _GLYPH_ICON_SIZE) -> QIcon:
    """Dock-into-main icon for Add to Main Window (inverse of send)."""

    def paint(p: QPainter, s: float) -> None:
        p.setPen(_glyph_pen(max(1.5, s * 0.12)))
        p.setBrush(Qt.NoBrush)
        # Main window / dock target on the left
        p.drawRect(QRectF(s * 0.10, s * 0.14, s * 0.44, s * 0.72))
        p.drawLine(QPointF(s * 0.10, s * 0.30), QPointF(s * 0.54, s * 0.30))
        # Arrow pointing into the window
        path = QPainterPath()
        path.moveTo(s * 0.90, s * 0.5)
        path.lineTo(s * 0.60, s * 0.5)
        path.moveTo(s * 0.72, s * 0.34)
        path.lineTo(s * 0.56, s * 0.5)
        path.lineTo(s * 0.72, s * 0.66)
        p.drawPath(path)

    return _paint_glyph_icon(paint, size)


def clear_selection_glyph_icon(size: int = _GLYPH_ICON_SIZE) -> QIcon:
    """Selection marquee corners with a centered X for Clear Selection."""

    def paint(p: QPainter, s: float) -> None:
        p.setPen(_glyph_pen(max(1.6, s * 0.13)))
        p.setBrush(Qt.NoBrush)
        x0, y0 = s * 0.08, s * 0.08
        x1, y1 = s * 0.92, s * 0.92
        arm = s * 0.20
        p.drawLine(QPointF(x0, y0), QPointF(x0 + arm, y0))
        p.drawLine(QPointF(x0, y0), QPointF(x0, y0 + arm))
        p.drawLine(QPointF(x1, y0), QPointF(x1 - arm, y0))
        p.drawLine(QPointF(x1, y0), QPointF(x1, y0 + arm))
        p.drawLine(QPointF(x0, y1), QPointF(x0 + arm, y1))
        p.drawLine(QPointF(x0, y1), QPointF(x0, y1 - arm))
        p.drawLine(QPointF(x1, y1), QPointF(x1 - arm, y1))
        p.drawLine(QPointF(x1, y1), QPointF(x1, y1 - arm))
        m = s * 0.34
        p.drawLine(QPointF(m, m), QPointF(s - m, s - m))
        p.drawLine(QPointF(s - m, m), QPointF(m, s - m))

    return _paint_glyph_icon(paint, size)


def pane_nav_arrow_glyph_icon(direction: str, size: int = _GLYPH_ICON_SIZE) -> QIcon:
    """Filled triangle for plot-pane previous / next / reorder arrows."""
    d = str(direction or "").strip().lower()

    def paint(p: QPainter, s: float) -> None:
        tip = s * 0.16
        back = s * 0.84
        mid = s * 0.50
        spread = s * 0.32
        if d == "left":
            pts = (QPointF(tip, mid), QPointF(back, mid - spread), QPointF(back, mid + spread))
        elif d == "right":
            pts = (QPointF(back, mid), QPointF(tip, mid - spread), QPointF(tip, mid + spread))
        elif d == "up":
            pts = (QPointF(mid, tip), QPointF(mid - spread, back), QPointF(mid + spread, back))
        else:
            pts = (QPointF(mid, back), QPointF(mid - spread, tip), QPointF(mid + spread, tip))
        path = QPainterPath()
        path.moveTo(pts[0])
        path.lineTo(pts[1])
        path.lineTo(pts[2])
        path.closeSubpath()
        p.setPen(Qt.NoPen)
        p.setBrush(_GLYPH_INK)
        p.drawPath(path)

    return _paint_glyph_icon(paint, size)


def style_plot_pane_nav_arrow(btn: QPushButton, direction: str, tooltip: str = "") -> None:
    """Square antialiased triangle control for plot-pane pager / reorder."""
    style_plot_chrome_glyph_button(
        btn, pane_nav_arrow_glyph_icon(direction), tooltip or btn.toolTip()
    )


def style_plot_chrome_glyph_button(btn: QPushButton, icon: QIcon, tooltip: str) -> None:
    """Turn a footer chrome button into a compact square glyph control."""
    btn.setText("")
    btn.setIcon(icon)
    btn.setIconSize(QSize(_GLYPH_ICON_SIZE, _GLYPH_ICON_SIZE))
    btn.setFixedSize(_GLYPH_BTN_SIZE, _GLYPH_BTN_SIZE)
    btn.setToolTip(tooltip)
    btn.setAutoDefault(False)
    btn.setDefault(False)
    btn.setFocusPolicy(Qt.NoFocus)
    btn.setFlat(False)
    # Zero padding so the icon is optically centered in the square button.
    btn.setStyleSheet("QPushButton { padding: 0px; margin: 0px; }")


def style_plot_footer_text_button(btn: QPushButton) -> None:
    """Compact height/padding for text chrome (Close Plot, region select, …)."""
    btn.setAutoDefault(False)
    btn.setDefault(False)
    btn.setFocusPolicy(Qt.NoFocus)
    btn.setFixedHeight(_GLYPH_BTN_SIZE)
    btn.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
    btn.setStyleSheet(
        "QPushButton {"
        f" padding: 0px {_FOOTER_TEXT_PAD_H}px;"
        f" font-size: {_FOOTER_TEXT_FONT_PX}px;"
        " min-height: 0px;"
        " }"
    )


def style_plot_pane_title_edit(edit: QLineEdit) -> None:
    """Compact transparent title field between pager arrows."""
    edit.setFixedHeight(_GLYPH_BTN_SIZE)
    edit.setFixedWidth(130)
    edit.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
    edit.setAlignment(Qt.AlignCenter)
    edit.setFrame(False)
    edit.setAutoFillBackground(False)
    pal = edit.palette()
    pal.setColor(QPalette.Base, Qt.transparent)
    pal.setColor(QPalette.Window, Qt.transparent)
    edit.setPalette(pal)
    edit.setStyleSheet(
        "QLineEdit {"
        f" padding: 0px {_FOOTER_TEXT_PAD_H}px;"
        f" font-size: {_FOOTER_TEXT_FONT_PX}px;"
        " border: none;"
        " background: transparent;"
        " background-color: transparent;"
        " min-height: 0px;"
        " }"
        "QLineEdit:focus {"
        " border: 1px solid palette(highlight);"
        " background: transparent;"
        " background-color: transparent;"
        " }"
        "QLineEdit:read-only {"
        " selection-background-color: transparent;"
        " }"
    )


def style_floating_plot_title_edit(edit: QLineEdit) -> None:
    """Window-centered floating title: no chrome background, text only."""
    edit.setFixedHeight(_GLYPH_BTN_SIZE)
    edit.setMinimumWidth(80)
    edit.setMaximumWidth(360)
    edit.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
    edit.setAlignment(Qt.AlignCenter)
    edit.setFrame(False)
    edit.setAutoFillBackground(False)
    edit.setAttribute(Qt.WA_TranslucentBackground, True)
    pal = edit.palette()
    pal.setColor(QPalette.Base, Qt.transparent)
    pal.setColor(QPalette.Window, Qt.transparent)
    edit.setPalette(pal)
    edit.setStyleSheet(
        "QLineEdit {"
        f" padding: 0px {_FOOTER_TEXT_PAD_H}px;"
        f" font-size: {_FOOTER_TEXT_FONT_PX}px;"
        " border: none;"
        " background: transparent;"
        " background-color: transparent;"
        " min-height: 0px;"
        " }"
        "QLineEdit:focus {"
        " border: none;"
        " background: transparent;"
        " background-color: transparent;"
        " }"
        "QLineEdit:read-only {"
        " border: none;"
        " selection-background-color: transparent;"
        " }"
    )
