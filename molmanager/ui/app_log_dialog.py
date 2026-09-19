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

"""Session log pane: tools, status history, and application logging."""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QPalette, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..platform_support.app_logging import active_log_file
from ..platform_support.session_log import (
    SessionLogEntry,
    ensure_session_log_handler,
    format_session_log_line,
    record_status_log,
    session_log_buffer,
)
from .qt_widget_utils import monospace_text_font

_LEVEL_CHOICES: tuple[tuple[str, int], ...] = (
    ("Debug", logging.DEBUG),
    ("Info", logging.INFO),
    ("Warning", logging.WARNING),
    ("Error", logging.ERROR),
)


class StatusLogLabel(QLabel):
    """Status line that mirrors noteworthy text into the session log."""

    def __init__(self, text: str = "", parent=None) -> None:
        super().__init__(text, parent)
        self._last_recorded_status: str | None = None

    def setText(self, text: str) -> None:  # noqa: N802 — Qt API name
        super().setText(text)
        self._last_recorded_status = record_status_log(text, self._last_recorded_status)


class SessionLogPanel(QWidget):
    """Live transcript of tool output, status history, and application logging."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        ensure_session_log_handler()

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        filters = QHBoxLayout()
        filters.addWidget(QLabel("Level:"))
        self._level = QComboBox()
        for label, value in _LEVEL_CHOICES:
            self._level.addItem(label, value)
        info_idx = next(
            i for i, (_label, value) in enumerate(_LEVEL_CHOICES) if value == logging.INFO
        )
        self._level.setCurrentIndex(info_idx)
        self._level.setToolTip("Hide records below this severity.")
        filters.addWidget(self._level)

        self._search = QLineEdit()
        self._search.setPlaceholderText("Filter text…")
        self._search.setClearButtonEnabled(True)
        filters.addWidget(self._search, 1)

        self._auto_scroll = QCheckBox("Auto-scroll")
        self._auto_scroll.setChecked(True)
        filters.addWidget(self._auto_scroll)
        root.addLayout(filters)

        self._view = QPlainTextEdit()
        self._view.setReadOnly(True)
        self._view.setLineWrapMode(QPlainTextEdit.NoWrap)
        self._view.setFont(monospace_text_font())
        self._view.setPlaceholderText(
            "Tool output, status history, warnings, and application logging appear here."
        )
        root.addWidget(self._view, 1)

        row = QHBoxLayout()
        self._btn_copy = QPushButton("Copy")
        self._btn_copy.setToolTip("Copy the visible log text.")
        self._btn_clear = QPushButton("Clear")
        self._btn_clear.setToolTip(
            "Clear the in-memory session log (does not delete the log file)."
        )
        self._btn_open = QPushButton("Open log file")
        self._btn_open.setToolTip("Open the rotating log file in the default editor.")
        row.addWidget(self._btn_copy)
        row.addWidget(self._btn_clear)
        row.addWidget(self._btn_open)
        row.addStretch()
        root.addLayout(row)

        self._btn_copy.clicked.connect(self._on_copy)
        self._btn_clear.clicked.connect(self._on_clear)
        self._btn_open.clicked.connect(self._on_open_file)
        self._level.currentIndexChanged.connect(self._on_filters_changed)
        self._search.textChanged.connect(self._on_filters_changed)

        self._shown_seq = 0
        self._generation = -1
        self._timer = QTimer(self)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self._pull_new)

        self._reload()
        self._sync_open_enabled()

    def showEvent(self, event) -> None:  # noqa: N802 — Qt API name
        super().showEvent(event)
        self._reload()
        if not self._timer.isActive():
            self._timer.start()

    def hideEvent(self, event) -> None:  # noqa: N802 — Qt API name
        if self._timer.isActive():
            self._timer.stop()
        super().hideEvent(event)

    def _min_level(self) -> int:
        data = self._level.currentData()
        return int(data) if isinstance(data, int) else logging.INFO

    def _needle(self) -> str:
        return (self._search.text() or "").strip().lower()

    def _entry_visible(self, entry: SessionLogEntry) -> bool:
        if entry.levelno < self._min_level():
            return False
        needle = self._needle()
        if not needle:
            return True
        hay = f"{entry.levelname} {entry.logger_name} {entry.message}".lower()
        return needle in hay

    def _color_for_level(self, levelno: int) -> QColor:
        pal = self._view.palette()
        if levelno >= logging.ERROR:
            return QColor("#e5534b")
        if levelno >= logging.WARNING:
            return QColor("#d4a017")
        if levelno <= logging.DEBUG:
            return pal.color(QPalette.Disabled, QPalette.WindowText)
        return pal.color(QPalette.WindowText)

    def _append_entry(self, entry: SessionLogEntry) -> None:
        line = format_session_log_line(entry)
        fmt = QTextCharFormat()
        fmt.setForeground(self._color_for_level(entry.levelno))
        cursor = self._view.textCursor()
        cursor.movePosition(QTextCursor.End)
        cursor.setCharFormat(fmt)
        cursor.insertText(line + "\n")
        self._view.setTextCursor(cursor)

    def _scroll_to_end_if_needed(self) -> None:
        if self._auto_scroll.isChecked():
            self._view.moveCursor(QTextCursor.End)

    def _reload(self) -> None:
        entries, seq, generation = session_log_buffer().snapshot(since_seq=0)
        self._generation = generation
        self._shown_seq = seq
        self._view.setPlainText("")
        for entry in entries:
            if self._entry_visible(entry):
                self._append_entry(entry)
        self._scroll_to_end_if_needed()
        self._sync_open_enabled()

    def _pull_new(self) -> None:
        entries, seq, generation = session_log_buffer().snapshot(since_seq=self._shown_seq)
        if generation != self._generation:
            self._reload()
            return
        if not entries:
            return
        self._shown_seq = seq
        for entry in entries:
            if self._entry_visible(entry):
                self._append_entry(entry)
        self._scroll_to_end_if_needed()

    def _on_filters_changed(self, *_args) -> None:
        self._reload()

    def _on_copy(self) -> None:
        self._view.selectAll()
        self._view.copy()
        cursor = self._view.textCursor()
        cursor.clearSelection()
        cursor.movePosition(QTextCursor.End)
        self._view.setTextCursor(cursor)

    def _on_clear(self) -> None:
        session_log_buffer().clear()
        self._reload()

    def _sync_open_enabled(self) -> None:
        path = active_log_file()
        self._btn_open.setEnabled(path is not None and Path(path).is_file())

    def _on_open_file(self) -> None:
        path = active_log_file()
        if path is None or not Path(path).is_file():
            QMessageBox.information(
                self,
                "Log file",
                "No log file is available. File logging may be disabled.",
            )
            self._sync_open_enabled()
            return
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))):
            QMessageBox.warning(self, "Log file", f"Could not open:\n{path}")
