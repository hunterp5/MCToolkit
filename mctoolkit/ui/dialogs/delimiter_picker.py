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

"""Shared delimiter combo + custom line edit for Split Column and Join Columns."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Generic, TypeVar

from PySide6.QtWidgets import QComboBox, QFormLayout, QLineEdit

_ModeT = TypeVar("_ModeT", bound=str)


class DelimiterPicker(Generic[_ModeT]):
    """Named delimiter modes in a combo, with a Custom field enabled only for that mode."""

    def __init__(
        self,
        modes: Sequence[tuple[str, _ModeT]],
        *,
        combo_tooltip: str,
        custom_placeholder: str,
        custom_tooltip: str,
        custom_max_length: int,
    ) -> None:
        self._modes = tuple(modes)
        self.combo = QComboBox()
        for label, _mode in self._modes:
            self.combo.addItem(label)
        self.combo.setToolTip(combo_tooltip)
        self.custom_input = QLineEdit()
        self.custom_input.setPlaceholderText(custom_placeholder)
        self.custom_input.setMaxLength(custom_max_length)
        self.custom_input.setToolTip(custom_tooltip)
        self.sync_custom_enabled()

    def add_rows(
        self,
        form: QFormLayout,
        *,
        combo_label: str,
        custom_label: str = "Custom:",
    ) -> None:
        form.addRow(combo_label, self.combo)
        form.addRow(custom_label, self.custom_input)

    def mode(self) -> _ModeT:
        idx = max(0, min(self.combo.currentIndex(), len(self._modes) - 1))
        return self._modes[idx][1]

    def custom_text(self) -> str:
        return self.custom_input.text()

    def sync_custom_enabled(self) -> None:
        self.custom_input.setEnabled(self.mode() == "custom")

    def connect_changed(self, on_changed: Callable[[], None]) -> None:
        self.combo.currentIndexChanged.connect(lambda *_args: self._on_combo_changed(on_changed))
        self.custom_input.textChanged.connect(lambda *_args: on_changed())

    def _on_combo_changed(self, on_changed: Callable[[], None]) -> None:
        self.sync_custom_enabled()
        on_changed()
