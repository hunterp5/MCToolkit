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

"""MMP Pair Network configuration dialog (legacy; network opens from Transform Ledger)."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QSpinBox,
    QVBoxLayout,
)

from ..qt_widget_utils import make_window_minimizable
from .mmp import activity_columns_for_mmp, select_preferred_activity_column
from .scope import selection_scope_checked


@dataclass(frozen=True)
class MmpNeighborhoodDialogParams:
    """Arguments for the MMP pair-network worker."""

    structure_source: str
    activity_column: str
    max_cuts: int
    max_variable_heavy_atoms: int
    min_activity_difference: float
    max_activity_difference: float


class MmpNeighborhoodDialog(QDialog):
    """Configure MMP fragmentation for the pair neighborhood network."""

    def __init__(
        self,
        *,
        structure_sources: list[str],
        activity_columns: list[str],
        selected_row_count: int,
        parent=None,
    ):
        super().__init__(parent)
        self.parent_app = parent
        self.setWindowTitle("MMP Pair Network")
        self.setMinimumWidth(440)
        self.resize(500, 0)
        self._have_selection = selected_row_count > 0

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 8)
        root.setSpacing(8)

        form = QFormLayout()
        self.src_combo = QComboBox()
        self.src_combo.addItems(structure_sources)
        form.addRow("Molecules from:", self.src_combo)

        self.activity_combo = QComboBox()
        self.activity_combo.setMinimumWidth(220)
        if activity_columns:
            self.activity_combo.addItems(activity_columns)
            select_preferred_activity_column(self.activity_combo)
        else:
            self.activity_combo.addItem("(no numeric columns)")
            self.activity_combo.setEnabled(False)
        self.activity_combo.setToolTip(
            "Numeric activity used to color nodes and sign edge Δ values."
        )
        form.addRow("Activity column:", self.activity_combo)

        self.max_cuts_sb = QSpinBox()
        self.max_cuts_sb.setRange(1, 3)
        self.max_cuts_sb.setValue(1)
        form.addRow("Max cuts:", self.max_cuts_sb)

        self.max_var_atoms_sb = QSpinBox()
        self.max_var_atoms_sb.setRange(1, 50)
        self.max_var_atoms_sb.setValue(13)
        form.addRow("Max variable heavy atoms:", self.max_var_atoms_sb)

        self.min_dact_sb = QDoubleSpinBox()
        self.min_dact_sb.setDecimals(6)
        self.min_dact_sb.setRange(0.0, 1e12)
        self.min_dact_sb.setValue(0.0)
        self.min_dact_sb.setSingleStep(0.1)
        self.min_dact_sb.setToolTip(
            "Report only pairs whose absolute activity difference is at least this value. "
            "0 reports all pairs."
        )
        form.addRow("Minimum activity difference:", self.min_dact_sb)

        self.max_dact_sb = QDoubleSpinBox()
        self.max_dact_sb.setDecimals(6)
        self.max_dact_sb.setRange(0.0, 1e12)
        self.max_dact_sb.setValue(0.0)
        self.max_dact_sb.setSingleStep(0.1)
        self.max_dact_sb.setToolTip(
            "Report only pairs whose absolute activity difference is at most this value. "
            "0 disables the upper bound."
        )
        form.addRow("Maximum activity difference:", self.max_dact_sb)
        root.addLayout(form)

        self.only_selected_cb = QCheckBox("Selected Rows Only")
        self._only_selected_scope_prefix = "Selected Rows Only"
        if self._have_selection:
            self.only_selected_cb.setText(
                f"{self._only_selected_scope_prefix} ({selected_row_count} row(s))"
            )
        else:
            self.only_selected_cb.setEnabled(False)
        root.addWidget(self.only_selected_cb)

        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        ok = box.button(QDialogButtonBox.Ok)
        if ok is not None:
            ok.setEnabled(bool(activity_columns))
        root.addWidget(box)
        make_window_minimizable(self)

    def only_selected_rows(self) -> bool:
        return selection_scope_checked(self)

    def params(self) -> MmpNeighborhoodDialogParams:
        return MmpNeighborhoodDialogParams(
            structure_source=self.src_combo.currentText(),
            activity_column=self.activity_combo.currentText(),
            max_cuts=int(self.max_cuts_sb.value()),
            max_variable_heavy_atoms=int(self.max_var_atoms_sb.value()),
            min_activity_difference=float(self.min_dact_sb.value()),
            max_activity_difference=float(self.max_dact_sb.value()),
        )


__all__ = [
    "MmpNeighborhoodDialog",
    "MmpNeighborhoodDialogParams",
    "activity_columns_for_mmp",
]
