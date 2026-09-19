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

"""Shared table-rows vs SMILES input for Predict pKa, SOM, Protomers, and BioTransformer."""

from __future__ import annotations

from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLineEdit,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from ...chem.molecule_conversion import parse_molecule_from_cell_text
from ..analysis_job_support import prepare_scoped_structure_mols
from .scope import selection_scope_checked

STRUCTURE_INPUT_MODE_LABELS: tuple[tuple[str, str], ...] = (
    ("table", "Table rows"),
    ("smiles", "SMILES string"),
)


class StructureInputPanel(QWidget):
    """Input mode combo, structure source, selected-rows scope, and SMILES field."""

    def __init__(self, *, selected_row_count: int = 0, parent=None):
        super().__init__(parent)
        self._have_selection = selected_row_count > 0
        self._only_selected_scope_prefix = "Selected Rows Only"

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(4)

        self.mode_combo = QComboBox()
        for key, label in STRUCTURE_INPUT_MODE_LABELS:
            self.mode_combo.addItem(label, key)
        mode_row = QHBoxLayout()
        mode_row.setSpacing(6)
        mode_row.addWidget(QLabel("Input:"))
        mode_row.addWidget(self.mode_combo, 1)
        root.addLayout(mode_row)

        self._table_cfg = QWidget()
        tc_lyt = QVBoxLayout(self._table_cfg)
        tc_lyt.setContentsMargins(0, 0, 0, 0)
        tc_lyt.setSpacing(4)
        src_row = QHBoxLayout()
        src_row.setSpacing(6)
        src_row.addWidget(QLabel("Source:"))
        self.src_combo = QComboBox()
        self.src_combo.setMinimumWidth(160)
        src_row.addWidget(self.src_combo, 1)
        tc_lyt.addLayout(src_row)
        self.only_selected_cb = QCheckBox("Selected Rows Only")
        if self._have_selection:
            self.only_selected_cb.setText(
                f"{self._only_selected_scope_prefix} ({selected_row_count} row(s))"
            )
        else:
            self.only_selected_cb.setEnabled(False)
        tc_lyt.addWidget(self.only_selected_cb)
        root.addWidget(self._table_cfg)

        self._smiles_cfg = QWidget()
        sm_lyt = QVBoxLayout(self._smiles_cfg)
        sm_lyt.setContentsMargins(0, 0, 0, 0)
        sm_lyt.setSpacing(4)
        self.smiles_edit = QLineEdit()
        self.smiles_edit.setPlaceholderText("SMILES")
        sm_lyt.addWidget(self.smiles_edit)
        self._smiles_cfg.setVisible(False)
        root.addWidget(self._smiles_cfg)

        self.mode_combo.currentIndexChanged.connect(self._sync_mode)
        self._sync_mode()

    def mode(self) -> str:
        return str(self.mode_combo.currentData() or "table")

    def refresh_sources(self, parent_app) -> None:
        self.src_combo.clear()
        if parent_app is None:
            return
        self.src_combo.addItems(parent_app.chemistry_tool_structure_sources())

    def collect_rows(self, dialog, tool_label: str) -> list | None:
        """Return ``(oid, mol)`` rows, or ``None`` after showing a validation message."""
        parent_app = getattr(dialog, "parent_app", None)
        if parent_app is None:
            return None
        if self.mode() == "smiles":
            smi = (self.smiles_edit.text() or "").strip()
            if not smi:
                QMessageBox.warning(dialog, tool_label, "Enter a SMILES string.")
                return None
            mol = parse_molecule_from_cell_text(smi)
            if mol is None:
                QMessageBox.warning(dialog, tool_label, "Could not parse SMILES.")
                return None
            return [(None, mol)]
        rows_m = prepare_scoped_structure_mols(
            parent_app,
            tool_label=tool_label,
            structure_source=self.src_combo.currentText(),
            only_selected=selection_scope_checked(dialog),
            empty_message="No valid structures were found for this scope and source.",
        )
        if not rows_m:
            return None
        return list(rows_m)

    def _sync_mode(self, _idx: int = 0) -> None:
        is_smiles = self.mode() == "smiles"
        self._table_cfg.setVisible(not is_smiles)
        self._smiles_cfg.setVisible(is_smiles)


def attach_structure_input(
    dialog, layout: QLayout, *, selected_row_count: int = 0
) -> StructureInputPanel:
    """Add the panel to *layout* and alias its widgets onto *dialog* for existing tests."""
    panel = StructureInputPanel(selected_row_count=selected_row_count, parent=dialog)
    layout.addWidget(panel)
    dialog._structure_input = panel
    dialog.mode_combo = panel.mode_combo
    dialog.src_combo = panel.src_combo
    dialog.only_selected_cb = panel.only_selected_cb
    dialog.smiles_edit = panel.smiles_edit
    dialog._table_cfg = panel._table_cfg
    dialog._smiles_cfg = panel._smiles_cfg
    dialog._only_selected_scope_prefix = panel._only_selected_scope_prefix
    return panel
