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

"""Dialog to choose which imported column defines the Structure column."""

from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QDialog, QDialogButtonBox, QLabel, QVBoxLayout

KEEP_STRUCTURES_AS_LOADED = "[Keep structures as loaded]"


def rank_structure_column_names(names: list[str]) -> list[str]:
    """Order likely structure columns first (header names only — no row scans)."""

    def sort_key(name: str) -> tuple[int, str]:
        lo = (name or "").strip().lower()
        if lo == "smiles":
            return (0, name)
        if "canonical" in lo and "smiles" in lo:
            return (1, name)
        if lo in ("smi", "structure"):
            return (2, name)
        if "smiles" in lo and "inchikey" not in lo:
            return (3, name)
        if lo == "inchi" or lo.startswith("inchi="):
            return (4, name)
        if "inchi" in lo and "key" not in lo:
            return (5, name)
        if "molblock" in lo or "mol_block" in lo or "molfile" in lo:
            return (6, name)
        return (20, name)

    return sorted({n for n in names if n}, key=sort_key)


class StructureSourcePickerDialog(QDialog):
    """Pick a structure-bearing column after file import."""

    def __init__(self, parent=None, columns: list[str] | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Structure source")
        self.setModal(True)
        self._picked: str | None = None

        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel(
                "Multiple structure-related columns were detected.\n"
                "Which column should define the molecule used for the Structure column?"
            )
        )
        self._combo = QComboBox(self)
        self._combo.addItem(KEEP_STRUCTURES_AS_LOADED)
        for name in rank_structure_column_names(columns or []):
            self._combo.addItem(name)
        layout.addWidget(self._combo)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, parent=self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @classmethod
    def pick_column(cls, parent, columns: list[str]) -> tuple[str | None, bool]:
        """
        Returns ``(column_name_or_None, accepted)``.

        ``None`` means keep structures as loaded (no override).
        """
        if len(columns) < 2:
            return None, True
        dlg = cls(parent, columns)
        if dlg.exec() != QDialog.Accepted:
            return None, False
        text = dlg._combo.currentText().strip()
        if not text or text == KEEP_STRUCTURES_AS_LOADED:
            return None, True
        return text, True
