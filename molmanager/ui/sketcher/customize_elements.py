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

"""Customize which element buttons appear in the sketcher left panel."""

from __future__ import annotations

from collections.abc import Sequence

from PyQt5.QtCore import QSettings, Qt
from PyQt5.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from .constants import (
    ELEMENT_FAMILY_GROUPS,
    SKETCH_ELEMENT_SYMBOLS,
    TOOLBAR_ELEMENT_SYMBOLS,
)

_SETTINGS_ORG = "MolManager"
_SETTINGS_APP = "MolManager"
_SETTINGS_KEY_ELEMENTS = "sketcher/toolbar_elements"


def default_toolbar_element_symbols() -> list[str]:
    return list(TOOLBAR_ELEMENT_SYMBOLS)


def _canonical_symbol(raw: str) -> str | None:
    s = (raw or "").strip()
    if not s:
        return None
    for sym in SKETCH_ELEMENT_SYMBOLS:
        if sym.lower() == s.lower():
            return sym
    for sym in TOOLBAR_ELEMENT_SYMBOLS:
        if sym.lower() == s.lower():
            return sym
    return None


def normalize_toolbar_element_symbols(symbols: Sequence[str]) -> list[str]:
    """Deduplicate and order symbols by informal PT family, then any leftovers."""
    selected: set[str] = set()
    for raw in symbols:
        canon = _canonical_symbol(str(raw))
        if canon is not None:
            selected.add(canon)
    if not selected:
        return default_toolbar_element_symbols()
    out: list[str] = []
    for _title, group_syms in ELEMENT_FAMILY_GROUPS:
        for sym in group_syms:
            if sym in selected and sym not in out:
                out.append(sym)
    for sym in SKETCH_ELEMENT_SYMBOLS:
        if sym in selected and sym not in out:
            out.append(sym)
    return out


def load_toolbar_element_symbols() -> list[str]:
    """Load persisted left-panel elements, or the built-in defaults."""
    raw = QSettings(_SETTINGS_ORG, _SETTINGS_APP).value(_SETTINGS_KEY_ELEMENTS, None)
    if raw is None or raw == "":
        return default_toolbar_element_symbols()
    if isinstance(raw, str):
        parts = [p.strip() for p in raw.replace(";", ",").split(",") if p.strip()]
    elif isinstance(raw, (list, tuple)):
        parts = [str(p).strip() for p in raw if str(p).strip()]
    else:
        return default_toolbar_element_symbols()
    return normalize_toolbar_element_symbols(parts)


def save_toolbar_element_symbols(symbols: Sequence[str]) -> None:
    ordered = normalize_toolbar_element_symbols(symbols)
    QSettings(_SETTINGS_ORG, _SETTINGS_APP).setValue(_SETTINGS_KEY_ELEMENTS, ",".join(ordered))


def element_groups_for_symbols(
    symbols: Sequence[str],
) -> list[tuple[str, tuple[str, ...]]]:
    """Partition visible symbols into informal PT family groups for the left panel."""
    remaining = list(normalize_toolbar_element_symbols(symbols))
    groups: list[tuple[str, tuple[str, ...]]] = []
    for title, group_syms in ELEMENT_FAMILY_GROUPS:
        present = tuple(s for s in remaining if s in group_syms)
        if not present:
            continue
        groups.append((title, present))
        remaining = [s for s in remaining if s not in present]
    if remaining:
        groups.append(("Other", tuple(remaining)))
    return groups


class CustomizeElementsDialog(QDialog):
    """Choose which element buttons appear beside the sketch canvas."""

    def __init__(self, parent: QWidget | None = None, selected: Sequence[str] | None = None):
        super().__init__(parent)
        self.setWindowTitle("Customize Elements")
        self.setModal(True)
        self.setMinimumWidth(360)
        self.setMinimumHeight(420)

        current = set(normalize_toolbar_element_symbols(selected or load_toolbar_element_symbols()))
        self._checks: dict[str, QCheckBox] = {}

        root = QVBoxLayout(self)
        root.addWidget(QLabel("Select elements shown in the sketcher element panel."))

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        body = QWidget()
        body_l = QVBoxLayout(body)
        body_l.setSpacing(8)

        used: set[str] = set()
        for title, group_syms in ELEMENT_FAMILY_GROUPS:
            box = QGroupBox(title)
            box_l = QVBoxLayout(box)
            row = QHBoxLayout()
            col_n = 0
            for sym in group_syms:
                used.add(sym)
                cb = QCheckBox(sym)
                cb.setChecked(sym in current)
                self._checks[sym] = cb
                row.addWidget(cb)
                col_n += 1
                if col_n >= 4:
                    box_l.addLayout(row)
                    row = QHBoxLayout()
                    col_n = 0
            if col_n:
                row.addStretch(1)
                box_l.addLayout(row)
            body_l.addWidget(box)

        other_syms = [s for s in SKETCH_ELEMENT_SYMBOLS if s not in used]
        if other_syms:
            box = QGroupBox("Other")
            box_l = QVBoxLayout(box)
            row = QHBoxLayout()
            col_n = 0
            for sym in other_syms:
                cb = QCheckBox(sym)
                cb.setChecked(sym in current)
                self._checks[sym] = cb
                row.addWidget(cb)
                col_n += 1
                if col_n >= 4:
                    box_l.addLayout(row)
                    row = QHBoxLayout()
                    col_n = 0
            if col_n:
                row.addStretch(1)
                box_l.addLayout(row)
            body_l.addWidget(box)

        body_l.addStretch(1)
        scroll.setWidget(body)
        root.addWidget(scroll, 1)

        btn_row = QHBoxLayout()
        reset_btn = QPushButton("Reset Defaults")
        reset_btn.clicked.connect(self._reset_defaults)
        btn_row.addWidget(reset_btn)
        btn_row.addStretch(1)
        root.addLayout(btn_row)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def accept(self) -> None:
        if not any(cb.isChecked() for cb in self._checks.values()):
            QMessageBox.warning(
                self,
                "Customize Elements",
                "Select at least one element for the panel.",
            )
            return
        super().accept()

    def _reset_defaults(self) -> None:
        defaults = set(default_toolbar_element_symbols())
        for sym, cb in self._checks.items():
            cb.setChecked(sym in defaults)

    def selected_symbols(self) -> list[str]:
        picked = [sym for sym, cb in self._checks.items() if cb.isChecked()]
        return normalize_toolbar_element_symbols(picked)
