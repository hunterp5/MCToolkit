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

"""Floating pane title editor and Plot Options title fields."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt, Signal
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from .dockable_plot_constants import (
    _FLOAT_TITLE_BASE_ATTR,
    _FLOAT_TITLE_EDIT_ATTR,
    _FLOAT_TITLE_FILTER_ATTR,
    _FLOAT_TITLE_RESIZE_FILTER_ATTR,
    _FOOTER_TEXT_PAD_H,
    _GLYPH_BTN_SIZE,
)
from .dockable_plot_glyphs import style_floating_plot_title_edit


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


class _FloatingTitleResizeFilter(QObject):
    """Keep the floating title geometrically centered in the footer bar."""

    def __init__(self, host: QWidget):
        super().__init__(host)
        self._host = host

    def eventFilter(self, obj, event):  # noqa: N802 — Qt API name
        if event.type() in (QEvent.Resize, QEvent.Show, QEvent.LayoutRequest):
            position_floating_title_edit(self._host)
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
    position_floating_title_edit(widget)


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
        position_floating_title_edit(widget)
        return
    title = plot_widget_display_title(widget)
    edit.blockSignals(True)
    edit.setText(title)
    edit.blockSignals(False)
    edit.setToolTip(f"{title}\nDouble-click to rename")
    position_floating_title_edit(widget)


def position_floating_title_edit(widget: QWidget | None) -> None:
    """Center the floating title over the footer bar (true window center)."""
    if widget is None:
        return
    edit = getattr(widget, _FLOAT_TITLE_EDIT_ATTR, None)
    bar = getattr(widget, "_footer_bar", None)
    if not isinstance(edit, QLineEdit) or bar is None:
        return
    try:
        if edit.isHidden():
            return
        bar_w = max(0, int(bar.width()))
        bar_h = max(_GLYPH_BTN_SIZE, int(bar.height()))
        fm = edit.fontMetrics()
        text = edit.text() or "Plot"
        text_w = fm.horizontalAdvance(text) + (2 * _FOOTER_TEXT_PAD_H) + 12
        width = max(80, min(360, text_w, max(80, bar_w - 24)))
        height = _GLYPH_BTN_SIZE
        x = max(0, (bar_w - width) // 2)
        y = max(0, (bar_h - height) // 2)
        edit.setGeometry(x, y, width, height)
        edit.raise_()
    except RuntimeError:
        return


def ensure_floating_title_edit(widget: QWidget | None) -> QLineEdit | None:
    """Ensure a window-centered editable title overlays the floating footer chrome."""
    if widget is None:
        return None
    existing = getattr(widget, _FLOAT_TITLE_EDIT_ATTR, None)
    if isinstance(existing, QLineEdit):
        return existing
    bar = getattr(widget, "_footer_bar", None)
    if bar is None:
        return None
    edit = QLineEdit(bar)
    style_floating_plot_title_edit(edit)
    edit.setReadOnly(True)
    edit.setToolTip("Double-click to rename this plot")
    edit.editingFinished.connect(lambda w=widget: commit_floating_title_edit(w))
    filt = _FloatingTitleEditFilter(widget, edit)
    edit.installEventFilter(filt)
    resize_filt = _FloatingTitleResizeFilter(widget)
    bar.installEventFilter(resize_filt)
    setattr(widget, _FLOAT_TITLE_EDIT_ATTR, edit)
    setattr(widget, _FLOAT_TITLE_FILTER_ATTR, filt)
    setattr(widget, _FLOAT_TITLE_RESIZE_FILTER_ATTR, resize_filt)
    refresh_floating_title_edit(widget)
    return edit


def sync_floating_title_chrome(widget: QWidget | None, *, floating: bool) -> None:
    """Show the floating title editor only while the plot is undocked."""
    if widget is None:
        return
    if getattr(widget, "supports_floating_title", True) is False:
        existing = getattr(widget, _FLOAT_TITLE_EDIT_ATTR, None)
        if isinstance(existing, QLineEdit):
            try:
                existing.hide()
            except RuntimeError:
                pass
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

    changed = Signal()

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
