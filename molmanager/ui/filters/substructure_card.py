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

"""Substructure SMARTS filter card."""

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import (
    QComboBox,
    QFrame,
    QLineEdit,
    QSizePolicy,
)

from .card_chrome import (
    _FILTER_CARD_MIN_HEIGHT_SUBSTRUCTURE,
    _FilterCardDragMixin,
    _FilterCardEnableInvertMixin,
    _fc_card_layout,
    _fc_configure_column_combo,
    _fc_install_card_shell,
)


class SubstructureFilterCard(_FilterCardDragMixin, _FilterCardEnableInvertMixin, QFrame):
    changed = pyqtSignal()
    removed = pyqtSignal(object)

    def __init__(self, structure_sources: list[str] | None = None):
        super().__init__()
        self._last_smarts = ""
        self._last_query = None
        _fc_install_card_shell(self, _FILTER_CARD_MIN_HEIGHT_SUBSTRUCTURE)
        l = _fc_card_layout(self)
        self._fc_add_title_row(l, "Substructure")
        self.src_combo = QComboBox()
        _fc_configure_column_combo(self.src_combo)
        self.set_structure_sources(structure_sources or ["Structure"])
        self.src_combo.currentIndexChanged.connect(self._on_source_change)
        self._fc_init_enable_invert("Hide rows that match SMARTS instead of showing them.")
        self._fc_add_header_toolbar(l)
        l.addWidget(self.src_combo)

        self.smarts_edit = QLineEdit()
        self.smarts_edit.setPlaceholderText("SMARTS, e.g. [F,Cl], [!C;R], or [M]")
        self.smarts_edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.smarts_edit.setMinimumWidth(0)
        self.smarts_edit.textChanged.connect(self._on_change)
        l.addWidget(self.smarts_edit)

    def _on_change(self, _txt: str) -> None:
        self._last_query = None
        self._last_smarts = ""
        self.changed.emit()

    def _on_source_change(self, _idx: int = 0) -> None:
        self.changed.emit()

    def _compiled_query(self):
        from ...chem.smarts_macropatterns import mol_from_smarts

        s = (self.smarts_edit.text() or "").strip()
        if not s:
            self._last_smarts = ""
            self._last_query = None
            return None
        if s == self._last_smarts:
            return self._last_query
        q = mol_from_smarts(s)
        self._last_smarts = s
        self._last_query = q
        return q

    def match_mol(self, mol) -> bool:
        q = self._compiled_query()
        if q is None:
            s = (self.smarts_edit.text() or "").strip()
            return True if not s else False
        try:
            return bool(mol is not None and mol.HasSubstructMatch(q))
        except Exception:
            return False

    def structure_source(self) -> str:
        return (self.src_combo.currentText() or "").strip() or "Structure"

    def set_structure_sources(self, sources: list[str]) -> None:
        """Refresh available structure sources, preserving the current selection when possible."""
        prev = self.structure_source() if self.src_combo.count() else "Structure"
        self.src_combo.blockSignals(True)
        self.src_combo.clear()
        items = [s for s in sources if s] or ["Structure"]
        self.src_combo.addItems(items)
        idx = self.src_combo.findText(prev)
        self.src_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.src_combo.blockSignals(False)

    def set_structure_source(self, source: str) -> None:
        name = (source or "").strip() or "Structure"
        idx = self.src_combo.findText(name)
        if idx < 0:
            self.src_combo.addItem(name)
            idx = self.src_combo.findText(name)
        if idx >= 0:
            self.src_combo.blockSignals(True)
            self.src_combo.setCurrentIndex(idx)
            self.src_combo.blockSignals(False)

    def get_cfg(self):
        return {
            "type": "substructure",
            "smarts": (self.smarts_edit.text() or "").strip(),
            "structure_source": self.structure_source(),
            "enabled": self._filter_enabled_on,
            "inverted": self._invert_on,
        }

    def set_smarts(self, smarts: str) -> None:
        self.smarts_edit.blockSignals(True)
        self.smarts_edit.setText(smarts or "")
        self.smarts_edit.blockSignals(False)
        self._last_smarts = ""
        self._last_query = None
