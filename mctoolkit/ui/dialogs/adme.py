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

"""Tools → Predict → ADME."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ...predictions.adme_prediction import (
    ADME_ENDPOINTS,
    ADME_GROUP_ORDER,
    RECOMMENDED_ADME_COLUMNS,
)
from ...reference.method_citations import adme_dialog_footer_html
from ..qt_widget_utils import make_window_minimizable
from .conformer_output import citation_footer_label
from .scope import selection_scope_checked


class AdmePredictorDialog(QDialog):
    """Predict selected TDC ADME endpoints (local Chemprop weights)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_app = parent
        self.setWindowTitle("Predict ADME")
        self.setMinimumWidth(440)
        n_sel = len(parent._selected_logical_rows()) if parent is not None else 0
        self._have_selection = n_sel > 0

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 6)
        root.setSpacing(4)

        hint = QLabel(
            "Check the properties to write. Nothing is calculated until you choose at least one."
        )
        hint.setWordWrap(True)
        root.addWidget(hint)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setMinimumHeight(280)
        groups_host = QWidget()
        groups_layout = QVBoxLayout(groups_host)
        groups_layout.setContentsMargins(0, 0, 0, 0)
        groups_layout.setSpacing(6)

        self._endpoint_cbs: dict[str, QCheckBox] = {}
        by_group: dict[str, list] = {g: [] for g in ADME_GROUP_ORDER}
        for ep in ADME_ENDPOINTS:
            by_group.setdefault(ep.group, []).append(ep)
        for group in ADME_GROUP_ORDER:
            box = QGroupBox(group)
            ep_layout = QVBoxLayout(box)
            ep_layout.setContentsMargins(8, 8, 8, 8)
            ep_layout.setSpacing(2)
            for ep in by_group.get(group, []):
                cb = QCheckBox(ep.label)
                cb.setChecked(False)
                self._endpoint_cbs[ep.column] = cb
                ep_layout.addWidget(cb)
            groups_layout.addWidget(box)
        groups_layout.addStretch()
        scroll.setWidget(groups_host)
        root.addWidget(scroll, 1)

        sel_row = QHBoxLayout()
        sel_row.setSpacing(6)
        self.recommended_btn = QPushButton("Recommended")
        self.recommended_btn.setToolTip(
            "Check hERG, CYP3A4 inhibitor, oral bioavailability, BBB, DILI, PPB, "
            "hepatocyte clearance, and aqueous solubility."
        )
        self.select_all_btn = QPushButton("Select all")
        self.clear_btn = QPushButton("Clear")
        self.recommended_btn.clicked.connect(self._on_recommended)
        self.select_all_btn.clicked.connect(self._set_all_checked)
        self.clear_btn.clicked.connect(self._clear_checked)
        sel_row.addWidget(self.recommended_btn)
        sel_row.addWidget(self.select_all_btn)
        sel_row.addWidget(self.clear_btn)
        sel_row.addStretch()
        root.addLayout(sel_row)

        src_row = QHBoxLayout()
        src_row.setSpacing(6)
        src_row.addWidget(QLabel("Structure source:"))
        self.src_combo = QComboBox()
        self.src_combo.setMinimumWidth(160)
        src_row.addWidget(self.src_combo, 1)
        root.addLayout(src_row)

        self.only_selected_cb = QCheckBox("Selected Rows Only")
        self._only_selected_scope_prefix = "Selected Rows Only"
        if self._have_selection:
            self.only_selected_cb.setText(f"{self._only_selected_scope_prefix} ({n_sel} row(s))")
        else:
            self.only_selected_cb.setEnabled(False)
        root.addWidget(self.only_selected_cb)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)
        self.predict_btn = QPushButton("Predict")
        self.predict_btn.clicked.connect(self._on_predict)
        btn_row.addWidget(self.predict_btn)
        btn_row.addStretch()
        root.addLayout(btn_row)

        root.addWidget(citation_footer_label(adme_dialog_footer_html(), self))

        if parent is not None:
            self.src_combo.addItems(parent.chemistry_tool_structure_sources())
        self.resize(460, 560)
        make_window_minimizable(self)

    def _selected_output_columns(self) -> list[str]:
        return [col for col, cb in self._endpoint_cbs.items() if cb.isChecked()]

    def _set_checked_columns(self, columns: tuple[str, ...] | list[str], *, checked: bool) -> None:
        wanted = set(columns)
        for col, cb in self._endpoint_cbs.items():
            if col in wanted:
                cb.setChecked(checked)

    def _on_recommended(self) -> None:
        self._clear_checked()
        self._set_checked_columns(RECOMMENDED_ADME_COLUMNS, checked=True)

    def _set_all_checked(self) -> None:
        self._set_checked_columns(tuple(self._endpoint_cbs), checked=True)

    def _clear_checked(self) -> None:
        self._set_checked_columns(tuple(self._endpoint_cbs), checked=False)

    def _on_predict(self) -> None:
        if self.parent_app is None:
            return
        output_columns = self._selected_output_columns()
        if not output_columns:
            QMessageBox.warning(
                self,
                "Predict ADME",
                "Select at least one property.",
            )
            return
        only_selected = selection_scope_checked(self)
        allowed = self.parent_app._selected_oids_set() if only_selected else None
        if only_selected and not allowed:
            QMessageBox.warning(
                self,
                "Predict ADME",
                "\u201cSelected Rows Only\u201d is checked but nothing is selected.",
            )
            return
        src = self.src_combo.currentText()
        self.parent_app.schedule_adme_prediction(
            src, only_selected=only_selected, output_columns=tuple(output_columns)
        )
        self.close()
