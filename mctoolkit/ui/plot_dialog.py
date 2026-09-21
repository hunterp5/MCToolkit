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

"""Floating window hosting a :class:`PlotWidget`."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QComboBox,
    QDialog,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from ..platform_support.qt_webengine_flags import set_descendant_webengine_visible
from .dockable_plot import handle_floating_plot_close_event
from .qt_widget_utils import configure_floating_webengine_window

if TYPE_CHECKING:
    from .plot import PlotWidget


class PlotDialog(QDialog):
    """Floating window hosting a :class:`PlotWidget`."""

    def __init__(self, parent_app=None, plot_widget: PlotWidget | None = None):
        from .plot import PlotWidget as PlotWidgetCls

        super().__init__(parent_app)
        self.parent_app = parent_app
        self.setWindowTitle("Plot Data")
        configure_floating_webengine_window(self)
        self.resize(960, 900)

        if plot_widget is not None:
            set_descendant_webengine_visible(plot_widget, False)
            self._plot_widget = plot_widget
            self._plot_widget.setParent(self)
        else:
            self._plot_widget = PlotWidgetCls(parent_app, qt_parent=self)
        self.only_selected_cb = self._plot_widget.only_selected_cb
        self._only_selected_scope_prefix = self._plot_widget._only_selected_scope_prefix

        root = QVBoxLayout(self)
        root.addWidget(self._plot_widget, 1)
        set_descendant_webengine_visible(self._plot_widget, True)
        self._plot_widget._sync_footer_chrome()

        self._configure_floating_plot_dialog()

    def _configure_floating_plot_dialog(self) -> None:
        self._force_close = False
        for btn in self.findChildren(QPushButton):
            btn.setAutoDefault(False)
            btn.setDefault(False)

        esc = QShortcut(QKeySequence(Qt.Key_Escape), self)
        esc.setContext(Qt.WidgetWithChildrenShortcut)
        esc.activated.connect(self.close)

    def keyPressEvent(self, event) -> None:  # noqa: N802 — Qt API name
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            fw = self.focusWidget()
            if fw is not None and isinstance(fw, (QLineEdit, QComboBox, QAbstractSpinBox)):
                event.accept()
                return
        super().keyPressEvent(event)

    def closeEvent(self, event):
        handle_floating_plot_close_event(self, event)
