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
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with mctoolkit.  If not, see <https://www.gnu.org/licenses/>.

"""Settings dialog to assign keyboard shortcuts to main-window commands."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QKeySequenceEdit,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from ..hotkeys import (
    HOTKEY_SPECS,
    default_shortcuts,
    effective_shortcuts,
    find_duplicate_bindings,
    load_hotkey_overrides,
    save_hotkey_overrides,
)
from ..qt_widget_utils import make_window_minimizable


class HotkeysDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Hotkeys")
        self.setMinimumSize(520, 420)
        root = QVBoxLayout(self)

        self._table = QTableWidget(len(HOTKEY_SPECS), 3)
        self._table.setHorizontalHeaderLabels(["Category", "Command", "Shortcut"])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        self._table.setSelectionMode(QTableWidget.SingleSelection)
        self._table.cellDoubleClicked.connect(self._capture_shortcut_for_cell)
        root.addWidget(self._table, 1)

        overrides = load_hotkey_overrides()
        for row, spec in enumerate(HOTKEY_SPECS):
            cat_item = QTableWidgetItem(spec.category)
            cat_item.setFlags(cat_item.flags() & ~Qt.ItemIsEditable)
            self._table.setItem(row, 0, cat_item)
            name_item = QTableWidgetItem(spec.label)
            name_item.setFlags(name_item.flags() & ~Qt.ItemIsEditable)
            name_item.setData(Qt.UserRole, spec.action_id)
            self._table.setItem(row, 1, name_item)
            shortcuts = effective_shortcuts(spec.action_id, overrides)
            self._table.setItem(row, 2, QTableWidgetItem(_format_shortcuts(shortcuts)))

        actions = QHBoxLayout()
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        bb.accepted.connect(self._on_accept)
        bb.rejected.connect(self.reject)
        actions.addWidget(bb)
        clear_btn = QPushButton("Clear Selected")
        clear_btn.clicked.connect(self._clear_selected)
        actions.addWidget(clear_btn)
        actions.addStretch(1)
        reset_btn = QPushButton("Reset to Default")
        reset_btn.clicked.connect(self._reset_defaults)
        actions.addWidget(reset_btn)
        root.addLayout(actions)
        make_window_minimizable(self)

    def _capture_shortcut_for_cell(self, row: int, column: int) -> None:
        if column != 2:
            return
        dlg = QDialog(self)
        dlg.setWindowTitle("Press shortcut keys")
        lay = QVBoxLayout(dlg)
        lay.addWidget(
            QLabel("Press the key combination, then click OK. Cancel or clear to remove.")
        )
        seq_edit = QKeySequenceEdit(dlg)
        current = self._table.item(row, 2)
        if current is not None and current.text().strip():
            first = current.text().split(";")[0].strip()
            seq_edit.setKeySequence(QKeySequence(first))
        lay.addWidget(seq_edit)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        lay.addWidget(bb)
        if dlg.exec() != QDialog.Accepted:
            return
        seq = seq_edit.keySequence()
        text = seq.toString(QKeySequence.PortableText).strip() if not seq.isEmpty() else ""
        if self._table.item(row, 2) is not None:
            self._table.item(row, 2).setText(text)

    def _reset_defaults(self) -> None:
        for row in range(self._table.rowCount()):
            aid = self._action_id_for_row(row)
            if aid:
                self._table.item(row, 2).setText(_format_shortcuts(default_shortcuts(aid)))

    def _clear_selected(self) -> None:
        rows = {idx.row() for idx in self._table.selectedIndexes()}
        if not rows and self._table.currentRow() >= 0:
            rows = {self._table.currentRow()}
        for row in rows:
            self._table.item(row, 2).setText("")

    def _action_id_for_row(self, row: int) -> str | None:
        item = self._table.item(row, 1)
        if item is None:
            return None
        aid = item.data(Qt.UserRole)
        return str(aid) if aid else None

    def _collect_bindings(self) -> dict[str, list[str]]:
        bindings: dict[str, list[str]] = {}
        for row in range(self._table.rowCount()):
            aid = self._action_id_for_row(row)
            if not aid:
                continue
            text = (self._table.item(row, 2).text() if self._table.item(row, 2) else "").strip()
            bindings[aid] = _parse_shortcut_cell(text)
        return bindings

    def _on_accept(self) -> None:
        bindings = self._collect_bindings()
        dups = find_duplicate_bindings(bindings)
        if dups:
            lines = [f"{key}: {', '.join(ids)}" for key, ids in sorted(dups.items())]
            QMessageBox.warning(
                self,
                "Hotkeys",
                "Each shortcut can only be assigned to one command:\n\n" + "\n".join(lines),
            )
            return
        overrides: dict[str, list[str]] = {}
        for spec in HOTKEY_SPECS:
            shortcuts = bindings.get(spec.action_id, default_shortcuts(spec.action_id))
            if shortcuts != default_shortcuts(spec.action_id):
                overrides[spec.action_id] = shortcuts
        save_hotkey_overrides(overrides)
        self.accept()


def _format_shortcuts(shortcuts: list[str]) -> str:
    return "; ".join(shortcuts)


def _parse_shortcut_cell(text: str) -> list[str]:
    if not (text or "").strip():
        return []
    parts = [p.strip() for p in text.replace("\n", ";").split(";")]
    out: list[str] = []
    for part in parts:
        if not part:
            continue
        seq = QKeySequence(part)
        norm = seq.toString(QKeySequence.PortableText).strip()
        if norm and norm not in out:
            out.append(norm)
    return out
