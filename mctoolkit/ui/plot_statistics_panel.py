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

"""Statistics / curve-fit summary panel for the Plotter options column."""

from __future__ import annotations

from PySide6.QtWidgets import QLabel, QTextEdit, QVBoxLayout, QWidget

from .qt_widget_utils import apply_monospace_to_text_edit


class PlotStatisticsPanel(QWidget):
    """Embedded statistics and curve-fit summary beside the plot options."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumWidth(240)
        root = QVBoxLayout(self)
        root.setContentsMargins(4, 0, 0, 0)
        root.setSpacing(4)
        title = QLabel("Statistics")
        title.setStyleSheet("font-weight: bold;")
        root.addWidget(title)
        self.summary_text = QTextEdit()
        self.summary_text.setReadOnly(True)
        self.summary_text.setMinimumHeight(120)
        apply_monospace_to_text_edit(self.summary_text)
        root.addWidget(self.summary_text, 1)
        self.set_lines(["Plot data to see summary statistics."])

    def set_lines(self, lines: list[str]) -> None:
        self.summary_text.setPlainText("\n".join(lines) if lines else "")
