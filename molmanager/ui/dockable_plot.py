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

"""Shared helpers for plots docked beside the main compound table."""

from __future__ import annotations

from PyQt5.QtCore import QEvent, QObject, QPointF, QRectF, QSize, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PyQt5.QtWidgets import (
    QDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

# Floor when no docked content is present (empty host / buttons only).
PLOT_PANEL_BASE_MINIMUM_WIDTH = 420
# Comfortable default dock width for a plot figure (options live in a dialog).
PLOT_PANEL_DEFAULT_WIDTH = 640
# Plot region narrower than this is treated as collapsed (grow to the layout default).
PLOT_PANEL_COLLAPSED_WIDTH = 48

_PANE_EMBED_ATTR = "_molmanager_pane_embed_state"
_DOCK_HEADER_HOME_ATTR = "_molmanager_dock_header_homes"
_FLOAT_TITLE_EDIT_ATTR = "_float_title_edit"
_FLOAT_TITLE_FILTER_ATTR = "_float_title_filter"
_FLOAT_TITLE_BASE_ATTR = "_float_title_edit_base"
_DOCK_LEADING_OPTS_ATTRS = ("_opts_btn", "_clear_sel_btn")
_DOCK_HEADER_BUTTON_ATTRS = (
    "select_egg_btn",
    "select_yolk_btn",
    "select_region_btn",
    "_btn_browse",
    "_btn_select",
)
# Floating: Add to Main. Docked: Send to New Window. Same footer slot.
_DOCK_SEND_WINDOW_ATTRS = (
    "_add_to_main_btn",
    "_send_window_btn",
)
_DOCK_TRAILING_CLOSE_BUTTON_ATTRS = (
    "_close_plot_btn",
    "_close_viewer_btn",
    "_close_btn",
)
_DOCK_TEXT_CHROME_ATTRS = (
    "_close_plot_btn",
    "_close_viewer_btn",
    "_close_btn",
    "select_egg_btn",
    "select_yolk_btn",
    "select_region_btn",
    "_btn_browse",
    "_btn_select",
)
_GLYPH_BTN_SIZE = 20
_GLYPH_ICON_SIZE = 13
_FOOTER_TEXT_FONT_PX = 11
_FOOTER_TEXT_PAD_H = 5


def _paint_glyph_icon(paint_fn, size: int = _GLYPH_ICON_SIZE) -> QIcon:
    dpr = 2.0
    pm = QPixmap(int(size * dpr), int(size * dpr))
    pm.fill(Qt.transparent)
    pm.setDevicePixelRatio(dpr)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.Antialiasing, True)
    paint_fn(painter, float(size))
    painter.end()
    return QIcon(pm)


def plot_options_glyph_icon(size: int = _GLYPH_ICON_SIZE) -> QIcon:
    """Compact gear icon for Plot Options."""

    def paint(p: QPainter, s: float) -> None:
        pen = QPen(QColor(40, 40, 40), max(1.2, s * 0.1))
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        cx = cy = s * 0.5
        r = s * 0.22
        R = s * 0.38
        p.drawEllipse(QPointF(cx, cy), r, r)
        for i in range(8):
            ang = i * 45.0
            from math import cos, radians, sin

            a = radians(ang)
            x0 = cx + r * 1.35 * cos(a)
            y0 = cy + r * 1.35 * sin(a)
            x1 = cx + R * cos(a)
            y1 = cy + R * sin(a)
            p.drawLine(QPointF(x0, y0), QPointF(x1, y1))

    return _paint_glyph_icon(paint, size)


def send_to_window_glyph_icon(size: int = _GLYPH_ICON_SIZE) -> QIcon:
    """Window-with-arrow icon for Send to New Window."""

    def paint(p: QPainter, s: float) -> None:
        pen = QPen(QColor(40, 40, 40), max(1.2, s * 0.1))
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        # Back window
        p.drawRect(QRectF(s * 0.12, s * 0.28, s * 0.48, s * 0.48))
        # Front window offset
        p.drawRect(QRectF(s * 0.34, s * 0.14, s * 0.48, s * 0.48))
        # Arrow pointing out
        path = QPainterPath()
        path.moveTo(s * 0.58, s * 0.42)
        path.lineTo(s * 0.82, s * 0.18)
        path.moveTo(s * 0.66, s * 0.18)
        path.lineTo(s * 0.82, s * 0.18)
        path.lineTo(s * 0.82, s * 0.34)
        p.drawPath(path)

    return _paint_glyph_icon(paint, size)


def add_to_main_glyph_icon(size: int = _GLYPH_ICON_SIZE) -> QIcon:
    """Dock-into-main icon for Add to Main Window (inverse of send)."""

    def paint(p: QPainter, s: float) -> None:
        pen = QPen(QColor(40, 40, 40), max(1.2, s * 0.1))
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        # Main window / dock target on the left
        p.drawRect(QRectF(s * 0.12, s * 0.18, s * 0.42, s * 0.64))
        p.drawLine(QPointF(s * 0.12, s * 0.32), QPointF(s * 0.54, s * 0.32))
        # Arrow pointing into the window
        path = QPainterPath()
        path.moveTo(s * 0.88, s * 0.5)
        path.lineTo(s * 0.62, s * 0.5)
        path.moveTo(s * 0.70, s * 0.36)
        path.lineTo(s * 0.58, s * 0.5)
        path.lineTo(s * 0.70, s * 0.64)
        p.drawPath(path)

    return _paint_glyph_icon(paint, size)


def clear_selection_glyph_icon(size: int = _GLYPH_ICON_SIZE) -> QIcon:
    """Dashed selection box with a clear mark for Clear Selection."""

    def paint(p: QPainter, s: float) -> None:
        pen = QPen(QColor(40, 40, 40), max(1.2, s * 0.1))
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        pen.setStyle(Qt.DashLine)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        inset = s * 0.14
        p.drawRect(QRectF(inset, inset, s - 2 * inset, s - 2 * inset))
        pen.setStyle(Qt.SolidLine)
        pen.setWidthF(max(1.4, s * 0.12))
        p.setPen(pen)
        m = s * 0.32
        p.drawLine(QPointF(m, m), QPointF(s - m, s - m))
        p.drawLine(QPointF(s - m, m), QPointF(m, s - m))

    return _paint_glyph_icon(paint, size)


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
    edit.setStyleSheet(
        "QLineEdit {"
        f" padding: 0px {_FOOTER_TEXT_PAD_H}px;"
        f" font-size: {_FOOTER_TEXT_FONT_PX}px;"
        " border: none;"
        " background: transparent;"
        " min-height: 0px;"
        " }"
        "QLineEdit:focus {"
        " border: 1px solid palette(highlight);"
        " background: transparent;"
        " }"
        "QLineEdit:read-only {"
        " selection-background-color: transparent;"
        " }"
    )


def plot_widget_display_title(widget: QWidget | None) -> str:
    """User-facing plot name: custom pane title, else window/class defaults."""
    if widget is None:
        return "empty"
    custom = getattr(widget, "_pane_display_title", None)
    if isinstance(custom, str) and custom.strip():
        return custom.strip()
    title = getattr(widget, "_window_title", None)
    if isinstance(title, str) and title.strip():
        return title.strip()
    win_title = ""
    try:
        win_title = str(widget.windowTitle() or "").strip()
    except RuntimeError:
        win_title = ""
    if win_title:
        return win_title
    name = widget.__class__.__name__
    if name.endswith("PlotPanel"):
        return name[: -len("PlotPanel")] or name
    if name.endswith("Widget"):
        return name[: -len("Widget")] or name
    return name


def resolve_plot_title_text(override: str | None, default: str) -> str:
    """Use a non-empty override; otherwise keep ``default``."""
    text = (override or "").strip()
    return text if text else default


class _FloatingTitleEditFilter(QObject):
    """Double-click / Escape handling for the floating plot title field."""

    def __init__(self, host: QWidget, edit: QLineEdit):
        super().__init__(edit)
        self._host = host
        self._edit = edit

    def eventFilter(self, obj, event):  # noqa: N802 — Qt API name
        if obj is not self._edit:
            return super().eventFilter(obj, event)
        if event.type() == QEvent.MouseButtonDblClick:
            if event.button() == Qt.LeftButton:
                begin_floating_title_edit(self._host)
                return True
        if event.type() == QEvent.KeyPress and event.key() == Qt.Key_Escape:
            if not self._edit.isReadOnly():
                cancel_floating_title_edit(self._host)
                return True
        return super().eventFilter(obj, event)


def begin_floating_title_edit(widget: QWidget) -> None:
    edit = getattr(widget, _FLOAT_TITLE_EDIT_ATTR, None)
    if not isinstance(edit, QLineEdit):
        return
    base = plot_widget_display_title(widget)
    setattr(widget, _FLOAT_TITLE_BASE_ATTR, base)
    edit.blockSignals(True)
    edit.setText(base)
    edit.blockSignals(False)
    edit.setReadOnly(False)
    edit.setFocus(Qt.MouseFocusReason)
    edit.selectAll()


def cancel_floating_title_edit(widget: QWidget) -> None:
    edit = getattr(widget, _FLOAT_TITLE_EDIT_ATTR, None)
    if not isinstance(edit, QLineEdit):
        return
    base = str(getattr(widget, _FLOAT_TITLE_BASE_ATTR, "") or plot_widget_display_title(widget))
    edit.blockSignals(True)
    edit.setText(base)
    edit.blockSignals(False)
    edit.setReadOnly(True)
    edit.clearFocus()
    refresh_floating_title_edit(widget)


def commit_floating_title_edit(widget: QWidget) -> None:
    edit = getattr(widget, _FLOAT_TITLE_EDIT_ATTR, None)
    if not isinstance(edit, QLineEdit) or edit.isReadOnly():
        return
    text = edit.text().strip()
    edit.setReadOnly(True)
    if text:
        widget._pane_display_title = text
    elif hasattr(widget, "_pane_display_title"):
        try:
            delattr(widget, "_pane_display_title")
        except Exception:
            widget._pane_display_title = ""
    title = plot_widget_display_title(widget)
    try:
        host = widget.window()
        if host is not None and host is not widget:
            host.setWindowTitle(title)
    except RuntimeError:
        pass
    refresh_floating_title_edit(widget)
    app = getattr(widget, "parent_app", None)
    mark = getattr(app, "_mark_session_dirty", None) if app is not None else None
    if callable(mark):
        mark()


def refresh_floating_title_edit(widget: QWidget | None) -> None:
    if widget is None:
        return
    edit = getattr(widget, _FLOAT_TITLE_EDIT_ATTR, None)
    if not isinstance(edit, QLineEdit):
        return
    if not edit.isReadOnly() and edit.hasFocus():
        return
    title = plot_widget_display_title(widget)
    edit.blockSignals(True)
    edit.setText(title)
    edit.blockSignals(False)
    edit.setToolTip(f"{title}\nDouble-click to rename")


def ensure_floating_title_edit(widget: QWidget | None) -> QLineEdit | None:
    """Ensure a centered editable title sits in the floating footer chrome."""
    if widget is None:
        return None
    existing = getattr(widget, _FLOAT_TITLE_EDIT_ATTR, None)
    if isinstance(existing, QLineEdit):
        return existing
    bar = getattr(widget, "_footer_bar", None)
    foot = bar.layout() if bar is not None else None
    if not isinstance(foot, QHBoxLayout):
        return None
    edit = QLineEdit(bar)
    style_plot_pane_title_edit(edit)
    edit.setReadOnly(True)
    edit.setToolTip("Double-click to rename this plot")
    edit.editingFinished.connect(lambda w=widget: commit_floating_title_edit(w))
    filt = _FloatingTitleEditFilter(widget, edit)
    edit.installEventFilter(filt)
    setattr(widget, _FLOAT_TITLE_EDIT_ATTR, edit)
    setattr(widget, _FLOAT_TITLE_FILTER_ATTR, filt)

    stretch_idx = -1
    for i in range(foot.count()):
        item = foot.itemAt(i)
        if item is not None and item.spacerItem() is not None:
            stretch_idx = i
            break
    if stretch_idx < 0:
        foot.addStretch(1)
        stretch_idx = foot.count() - 1
    # opts … | stretch | title | stretch | add…
    foot.insertStretch(stretch_idx, 1)
    foot.insertWidget(stretch_idx + 1, edit)
    refresh_floating_title_edit(widget)
    return edit


def sync_floating_title_chrome(widget: QWidget | None, *, floating: bool) -> None:
    """Show the floating title editor only while the plot is undocked."""
    if widget is None:
        return
    edit = ensure_floating_title_edit(widget)
    if edit is None:
        return
    try:
        edit.setVisible(bool(floating))
    except RuntimeError:
        return
    if floating:
        refresh_floating_title_edit(widget)

class PlotTitlesControls(QGroupBox):
    """Titles section for Plot Options: figure title and axis names."""

    changed = pyqtSignal()

    def __init__(self, parent: QWidget | None = None, *, include_z: bool = False):
        super().__init__("Titles", parent)
        self._include_z = bool(include_z)
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(4)

        title_row = QHBoxLayout()
        title_row.setSpacing(6)
        title_row.addWidget(QLabel("Plot title:"))
        self.plot_title_edit = QLineEdit()
        self.plot_title_edit.setPlaceholderText("Default (leave empty)")
        self.plot_title_edit.setToolTip(
            "Title drawn inside the plot. Leave empty to keep the plot’s default title."
        )
        self.plot_title_edit.editingFinished.connect(self.changed.emit)
        title_row.addWidget(self.plot_title_edit, 1)
        root.addLayout(title_row)

        axis_row = QHBoxLayout()
        axis_row.setSpacing(6)
        axis_row.addWidget(QLabel("X title:"))
        self.xaxis_title_edit = QLineEdit()
        self.xaxis_title_edit.setPlaceholderText("Default (leave empty)")
        self.xaxis_title_edit.setToolTip("Override the X-axis title. Empty keeps the default.")
        self.xaxis_title_edit.editingFinished.connect(self.changed.emit)
        axis_row.addWidget(self.xaxis_title_edit, 1)
        axis_row.addWidget(QLabel("Y title:"))
        self.yaxis_title_edit = QLineEdit()
        self.yaxis_title_edit.setPlaceholderText("Default (leave empty)")
        self.yaxis_title_edit.setToolTip("Override the Y-axis title. Empty keeps the default.")
        self.yaxis_title_edit.editingFinished.connect(self.changed.emit)
        axis_row.addWidget(self.yaxis_title_edit, 1)
        self._z_title_label = QLabel("Z title:")
        self.zaxis_title_edit = QLineEdit()
        self.zaxis_title_edit.setPlaceholderText("Default (leave empty)")
        self.zaxis_title_edit.setToolTip("Override the Z-axis title. Empty keeps the default.")
        self.zaxis_title_edit.editingFinished.connect(self.changed.emit)
        axis_row.addWidget(self._z_title_label)
        axis_row.addWidget(self.zaxis_title_edit, 1)
        root.addLayout(axis_row)
        self.set_z_visible(self._include_z)

    def set_z_visible(self, visible: bool) -> None:
        self._include_z = bool(visible)
        self._z_title_label.setVisible(self._include_z)
        self.zaxis_title_edit.setVisible(self._include_z)

    def title_overrides(self) -> dict[str, str]:
        """Return non-normalized title field texts for figure builders."""
        out = {
            "plot_title": self.plot_title_edit.text(),
            "xaxis_title": self.xaxis_title_edit.text(),
            "yaxis_title": self.yaxis_title_edit.text(),
        }
        if self._include_z:
            out["zaxis_title"] = self.zaxis_title_edit.text()
        return out


def make_plot_options_button(
    parent: QWidget | None = None,
    *,
    tooltip: str = "Plot Options",
) -> QPushButton:
    btn = QPushButton(parent)
    style_plot_chrome_glyph_button(btn, plot_options_glyph_icon(), tooltip)
    return btn


def make_send_window_button(
    parent: QWidget | None = None,
    *,
    tooltip: str = "Send to New Window",
) -> QPushButton:
    btn = QPushButton(parent)
    style_plot_chrome_glyph_button(btn, send_to_window_glyph_icon(), tooltip)
    return btn


def make_add_to_main_button(
    parent: QWidget | None = None,
    *,
    tooltip: str = "Add to Main Window",
) -> QPushButton:
    btn = QPushButton(parent)
    style_plot_chrome_glyph_button(btn, add_to_main_glyph_icon(), tooltip)
    return btn


def make_close_plot_button(
    parent: QWidget | None = None,
    *,
    tooltip: str = "Close this plot.",
) -> QPushButton:
    btn = QPushButton("Close Plot", parent)
    btn.setToolTip(tooltip)
    style_plot_footer_text_button(btn)
    return btn


def make_clear_selection_button(
    parent: QWidget | None = None,
    *,
    tooltip: str = "Clear the current table and plot selection.",
) -> QPushButton:
    btn = QPushButton(parent)
    style_plot_chrome_glyph_button(btn, clear_selection_glyph_icon(), tooltip)
    return btn


def apply_plot_chrome_glyphs(widget: QWidget | None) -> None:
    """Ensure Plot Options / Clear / Add / Send glyphs and compact text chrome when present."""
    if widget is None:
        return
    opts = getattr(widget, "_opts_btn", None)
    if isinstance(opts, QPushButton):
        tip = opts.toolTip() or "Plot Options"
        style_plot_chrome_glyph_button(opts, plot_options_glyph_icon(), tip)
    clear = getattr(widget, "_clear_sel_btn", None)
    if isinstance(clear, QPushButton):
        tip = clear.toolTip() or "Clear the current table and plot selection."
        style_plot_chrome_glyph_button(clear, clear_selection_glyph_icon(), tip)
    add = getattr(widget, "_add_to_main_btn", None)
    if isinstance(add, QPushButton):
        tip = add.toolTip() or "Add to Main Window"
        style_plot_chrome_glyph_button(add, add_to_main_glyph_icon(), tip)
    send = getattr(widget, "_send_window_btn", None)
    if isinstance(send, QPushButton):
        tip = send.toolTip() or "Send to New Window"
        style_plot_chrome_glyph_button(send, send_to_window_glyph_icon(), tip)
    for name in _DOCK_TEXT_CHROME_ATTRS:
        btn = getattr(widget, name, None)
        if isinstance(btn, QPushButton) and (btn.text() or "").strip():
            style_plot_footer_text_button(btn)


def confirm_close_plot(
    parent: QWidget | None,
    *,
    title: str = "Close Plot",
    message: str = "Close this plot?",
) -> bool:
    """Deprecated no-op: plot close is no longer confirmed. Always returns True."""
    _ = parent, title, message
    return True


def _widget_is_docked_in_main(widget: QWidget) -> bool:
    app = getattr(widget, "parent_app", None)
    if app is None:
        return False
    check = getattr(app, "is_plot_docked", None)
    if callable(check):
        return bool(check(widget))
    return getattr(app, "_docked_plot_widget", None) is widget


def request_close_plot_widget(
    widget: QWidget,
    *,
    title: str = "Close Plot",
    message: str = "Close this plot?",
) -> None:
    """Close a docked plot or its floating host dialog without confirmation."""
    _ = title, message
    if _widget_is_docked_in_main(widget):
        app = getattr(widget, "parent_app", None)
        close = getattr(app, "close_docked_plot", None) if app is not None else None
        if callable(close):
            close(widget, confirm=False)
        return
    dlg = widget.window()
    if dlg is not None and dlg is not widget:
        dlg._force_close = True
        dlg.close()


def handle_floating_plot_close_event(
    dialog: QWidget,
    event,
    *,
    title: str = "Close Plot",
    message: str = "Close this plot?",
) -> None:
    """Shared closeEvent for floating plot / viewer / browser dialogs (no confirm)."""
    _ = title, message
    if getattr(dialog, "_force_close", False):
        dialog._force_close = False
    event.accept()


def discard_host_dialog_after_dock(dlg, host, attr_name: str) -> None:
    """Destroy the empty floating husk after its panel was reparented into the workspace."""
    if dlg is None:
        return
    if hasattr(dlg, "_panel"):
        dlg._panel = None
    dlg._force_close = True
    if host is not None and getattr(host, attr_name, None) is dlg:
        setattr(host, attr_name, None)
    try:
        dlg.close()
        dlg.deleteLater()
    except RuntimeError:
        pass


def make_plot_options_dialog(
    parent: QWidget,
    content: QWidget,
    *,
    title: str = "Plot Options",
    min_width: int = 520,
    min_height: int = 360,
) -> QDialog:
    """Build a modeless dialog that hosts a plot's options panel."""
    dlg = QDialog(parent)
    dlg.setWindowTitle(title)
    dlg.setModal(False)
    dlg.setWindowModality(Qt.NonModal)
    dlg.setAttribute(Qt.WA_DeleteOnClose, False)
    dlg.setMinimumWidth(min_width)
    dlg.setMinimumHeight(min_height)
    root = QVBoxLayout(dlg)
    root.setContentsMargins(8, 8, 8, 8)
    root.addWidget(content, 1)
    return dlg


def show_plot_options_dialog(dialog: QDialog | None) -> None:
    """Show and raise an existing plot-options dialog."""
    if dialog is None:
        return
    dialog.show()
    dialog.raise_()
    dialog.activateWindow()


def hide_plot_options_dialog(dialog: QDialog | None) -> None:
    """Hide a plot-options dialog if it is open."""
    if dialog is None:
        return
    try:
        dialog.hide()
    except RuntimeError:
        pass


def iter_plot_selection_views(root: QWidget | None) -> list:
    """Return widgets that implement ``sync_from_table_selection`` (plot ↔ table)."""
    if root is None:
        return []
    views: list = []
    seen: set[int] = set()

    def add(candidate) -> None:
        if candidate is None:
            return
        key = id(candidate)
        if key in seen:
            return
        if not callable(getattr(candidate, "sync_from_table_selection", None)):
            return
        seen.add(key)
        views.append(candidate)

    add(root)
    add(getattr(root, "_plot_view", None))
    add(getattr(root, "_plot_widget", None))
    return views


def is_dockable_plot_widget(widget) -> bool:
    """True when the widget can be placed in the main-window plot panel."""
    return getattr(widget, "only_selected_cb", None) is not None and bool(
        iter_plot_selection_views(widget)
    )


def is_dockable_workspace_widget(widget) -> bool:
    """True for plot panels or other workspace-dockable widgets (e.g. 2D/3D viewers)."""
    if is_dockable_plot_widget(widget):
        return True
    return bool(getattr(widget, "dockable_in_workspace", False))


def plot_embedded_minimum_width(widget: QWidget | None) -> int:
    """Minimum panel width so docked plot controls do not overlap or clip."""
    if widget is None:
        return PLOT_PANEL_BASE_MINIMUM_WIDTH
    custom = getattr(widget, "embedded_minimum_width", None)
    if callable(custom):
        try:
            return max(PLOT_PANEL_BASE_MINIMUM_WIDTH, int(custom()))
        except Exception:
            pass
    try:
        hint = int(widget.minimumSizeHint().width())
    except Exception:
        hint = 0
    return max(PLOT_PANEL_BASE_MINIMUM_WIDTH, hint)


def plot_embedded_preferred_width(widget: QWidget | None) -> int:
    """Preferred dock width (at least the minimum needed for controls)."""
    min_w = plot_embedded_minimum_width(widget)
    if widget is None:
        return max(min_w, PLOT_PANEL_DEFAULT_WIDTH)
    custom = getattr(widget, "embedded_preferred_width", None)
    if callable(custom):
        try:
            return max(min_w, int(custom()))
        except Exception:
            pass
    try:
        hint = int(widget.sizeHint().width())
    except Exception:
        hint = 0
    return max(min_w, hint, PLOT_PANEL_DEFAULT_WIDTH)


def _layout_containing(widget: QWidget) -> QLayout | None:
    parent = widget.parentWidget()
    if parent is None:
        return None
    ly = parent.layout()
    if ly is not None:
        try:
            if ly.indexOf(widget) >= 0:
                return ly
        except RuntimeError:
            pass
    try:
        for child_ly in parent.findChildren(QLayout):
            try:
                if child_ly.indexOf(widget) >= 0:
                    return child_ly
            except RuntimeError:
                continue
    except RuntimeError:
        pass
    return None


def iter_dock_header_buttons(widget: QWidget | None) -> list[QWidget]:
    """Mid-header chrome buttons (e.g. Egg / Yolk / Triangle) when docked."""
    return _iter_named_buttons(widget, _DOCK_HEADER_BUTTON_ATTRS)


def iter_dock_leading_opts_buttons(widget: QWidget | None) -> list[QWidget]:
    """Plot Options + Clear Selection glyphs on the far left of the pane header."""
    return _iter_named_buttons(widget, _DOCK_LEADING_OPTS_ATTRS)


def iter_dock_send_window_buttons(widget: QWidget | None) -> list[QWidget]:
    """Add-to-main / send-window glyph shown left of Close / pane ×."""
    return _iter_named_buttons(widget, _DOCK_SEND_WINDOW_ATTRS)


def iter_dock_trailing_close_buttons(widget: QWidget | None) -> list[QWidget]:
    """Close-this-plot/viewer buttons shown immediately left of the pane ×."""
    return _iter_named_buttons(widget, _DOCK_TRAILING_CLOSE_BUTTON_ATTRS)


def _iter_named_buttons(widget: QWidget | None, names: tuple[str, ...]) -> list[QWidget]:
    if widget is None:
        return []
    buttons: list[QWidget] = []
    seen: set[int] = set()
    for name in names:
        btn = getattr(widget, name, None)
        if btn is None:
            continue
        key = id(btn)
        if key in seen:
            continue
        seen.add(key)
        buttons.append(btn)
    return buttons


def restore_dock_header_buttons(widget: QWidget | None) -> None:
    """Put pane-adopted buttons back on the plot/viewer footer."""
    if widget is None:
        return
    homes = getattr(widget, _DOCK_HEADER_HOME_ATTR, None)
    if not homes:
        return
    try:
        delattr(widget, _DOCK_HEADER_HOME_ATTR)
    except Exception:
        setattr(widget, _DOCK_HEADER_HOME_ATTR, None)
    for btn, layout, index in sorted(homes, key=lambda item: int(item[2])):
        if btn is None or layout is None:
            continue
        try:
            idx = max(0, min(int(index), layout.count()))
            layout.insertWidget(idx, btn)
        except RuntimeError:
            continue
    sync_docked_footer_bar(widget, docked=False)


def _adopt_buttons_into_layout(
    host_layout: QHBoxLayout, widget: QWidget, buttons: list[QWidget]
) -> list[tuple[QWidget, QLayout | None, int]]:
    homes: list[tuple[QWidget, QLayout | None, int]] = []
    for btn in buttons:
        try:
            # ``isVisible()`` is false until the pane is shown; use ``isHidden()``
            # so intentionally suppressed chrome (e.g. Add to Main while docked) is skipped.
            if btn.isHidden():
                continue
        except RuntimeError:
            continue
        layout = _layout_containing(btn)
        index = -1
        if layout is not None:
            try:
                index = int(layout.indexOf(btn))
            except RuntimeError:
                index = -1
        homes.append((btn, layout, index))
        try:
            host_layout.addWidget(btn)
            btn.setAutoDefault(False)
            btn.setDefault(False)
            btn.setFocusPolicy(Qt.NoFocus)
        except RuntimeError:
            continue
    return homes


def adopt_dock_header_buttons(
    host_layout: QHBoxLayout,
    widget: QWidget | None,
    *,
    leading_opts_layout: QHBoxLayout | None = None,
    send_window_layout: QHBoxLayout | None = None,
    trailing_close_layout: QHBoxLayout | None = None,
) -> None:
    """Move dock chrome buttons into pane header strips."""
    if widget is None:
        return
    apply_plot_chrome_glyphs(widget)
    restore_dock_header_buttons(widget)
    homes: list[tuple[QWidget, QLayout | None, int]] = []
    if leading_opts_layout is not None:
        homes.extend(
            _adopt_buttons_into_layout(
                leading_opts_layout, widget, iter_dock_leading_opts_buttons(widget)
            )
        )
    else:
        homes.extend(
            _adopt_buttons_into_layout(
                host_layout, widget, iter_dock_leading_opts_buttons(widget)
            )
        )
    homes.extend(_adopt_buttons_into_layout(host_layout, widget, iter_dock_header_buttons(widget)))
    if send_window_layout is not None:
        homes.extend(
            _adopt_buttons_into_layout(
                send_window_layout, widget, iter_dock_send_window_buttons(widget)
            )
        )
    else:
        homes.extend(
            _adopt_buttons_into_layout(host_layout, widget, iter_dock_send_window_buttons(widget))
        )
    if trailing_close_layout is not None:
        homes.extend(
            _adopt_buttons_into_layout(
                trailing_close_layout, widget, iter_dock_trailing_close_buttons(widget)
            )
        )
    else:
        homes.extend(
            _adopt_buttons_into_layout(
                host_layout, widget, iter_dock_trailing_close_buttons(widget)
            )
        )
    setattr(widget, _DOCK_HEADER_HOME_ATTR, homes)
    sync_docked_footer_bar(widget, docked=True)


def sync_docked_footer_bar(widget: QWidget | None, *, docked: bool) -> None:
    """Hide an empty plot footer once its chrome buttons live in the pane header."""
    if widget is None:
        return
    sync_floating_title_chrome(widget, floating=not docked)
    bar = getattr(widget, "_footer_bar", None)
    if bar is None:
        return
    if not docked:
        try:
            bar.show()
        except RuntimeError:
            pass
        return
    ly = bar.layout()
    if ly is None:
        try:
            bar.hide()
        except RuntimeError:
            pass
        return
    try:
        for i in range(ly.count()):
            item = ly.itemAt(i)
            child = item.widget() if item is not None else None
            if child is None:
                continue
            try:
                if not child.isHidden():
                    bar.show()
                    return
            except RuntimeError:
                continue
        bar.hide()
    except RuntimeError:
        pass


def _iter_widget_layouts(widget: QWidget):
    seen: set[int] = set()
    layout = widget.layout()
    layouts = []
    if layout is not None:
        layouts.append(layout)
    try:
        layouts.extend(widget.findChildren(QLayout))
    except RuntimeError:
        pass
    for item in layouts:
        key = id(item)
        if key in seen:
            continue
        seen.add(key)
        yield item


def embed_in_plot_pane(widget: QWidget | None) -> None:
    """Let ``widget`` shrink to the current plot pane instead of growing the splitter.

    Floating windows keep large minimum sizes and ``QLayout.SetMinimumSize`` constraints.
    Those must not drive QSplitter after the widget is reparented into an existing pane.
    """
    if widget is None:
        return
    state = getattr(widget, _PANE_EMBED_ATTR, None)
    if state is None:
        layout_constraints: list[tuple[QLayout, int]] = []
        for layout in _iter_widget_layouts(widget):
            try:
                constraint = int(layout.sizeConstraint())
            except RuntimeError:
                continue
            if constraint == int(QLayout.SetMinimumSize):
                layout_constraints.append((layout, constraint))
        state = {
            "min": QSize(widget.minimumSize()),
            "max": QSize(widget.maximumSize()),
            "policy": QSizePolicy(widget.sizePolicy()),
            "layouts": layout_constraints,
        }
        setattr(widget, _PANE_EMBED_ATTR, state)
    _apply_plot_pane_fit(widget, state)


def _apply_plot_pane_fit(widget: QWidget, state: dict) -> None:
    for layout, _constraint in state.get("layouts") or ():
        try:
            layout.setSizeConstraint(QLayout.SetDefaultConstraint)
        except RuntimeError:
            pass
    widget.setMinimumSize(0, 0)
    widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)


def unembed_from_plot_pane(widget: QWidget | None) -> None:
    """Restore size constraints saved by :func:`embed_in_plot_pane`."""
    if widget is None:
        return
    restore_dock_header_buttons(widget)
    state = getattr(widget, _PANE_EMBED_ATTR, None)
    if not isinstance(state, dict):
        return
    try:
        delattr(widget, _PANE_EMBED_ATTR)
    except Exception:
        setattr(widget, _PANE_EMBED_ATTR, None)
    for layout, constraint in state.get("layouts") or ():
        try:
            layout.setSizeConstraint(constraint)
        except RuntimeError:
            pass
    try:
        widget.setMinimumSize(state["min"])
        widget.setMaximumSize(state["max"])
        widget.setSizePolicy(state["policy"])
    except RuntimeError:
        pass
