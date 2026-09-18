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

"""Modeless Protein Viewer dialog for placing and editing pharmacophore features."""

from __future__ import annotations

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...pharmacophore import (
    FEATURE_COLORS,
    FEATURE_TYPES,
    PharmacophoreFeature,
    default_feature_radius,
    normalize_feature_type,
)
from ..qt_widget_utils import make_window_minimizable

_COL_ON, _COL_TYPE, _COL_X, _COL_Y, _COL_Z, _COL_R = range(6)


def _type_combo(current: str = "Donor") -> QComboBox:
    combo = QComboBox()
    chosen = normalize_feature_type(current)
    for key, label in FEATURE_TYPES:
        combo.addItem(label, key)
        color = QColor(FEATURE_COLORS.get(key, "#888888"))
        combo.setItemData(combo.count() - 1, color, Qt.BackgroundRole)
    idx = combo.findData(chosen)
    if idx >= 0:
        combo.setCurrentIndex(idx)
    return combo


def _coord_spin(value: float, *, lo: float = -999.0, hi: float = 999.0) -> QDoubleSpinBox:
    spin = QDoubleSpinBox()
    spin.setRange(lo, hi)
    spin.setDecimals(3)
    spin.setSingleStep(0.1)
    spin.setValue(float(value))
    return spin


class ProteinPharmacophoreDialog(QDialog):
    """Edit pharmacophore spheres and place them by clicking atoms in 3D."""

    place_toggled = pyqtSignal(bool)
    add_at_coords = pyqtSignal(str, float, float, float, float)
    feature_changed = pyqtSignal(int, object)
    feature_removed = pyqtSignal(int)
    from_ligand_clicked = pyqtSignal()
    open_clicked = pyqtSignal()
    save_clicked = pyqtSignal()
    clear_clicked = pyqtSignal()
    send_gnina_clicked = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Pharmacophore")
        self.setModal(False)
        self.resize(560, 420)
        self._updating = False
        self._last_xyz = (0.0, 0.0, 0.0)

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(8)

        place_row = QHBoxLayout()
        self.chk_place = QCheckBox("Place on atom click")
        self.chk_place.setToolTip(
            "Click an atom in the Protein Viewer canvas to insert a feature at those "
            "coordinates. Empty space is not pickable in 3Dmol; use Add at coordinates "
            "for an explicit XYZ."
        )
        place_row.addWidget(self.chk_place)
        place_row.addWidget(QLabel("Type:"))
        self.combo_type = _type_combo()
        self.combo_type.setToolTip(
            "RDKit BaseFeatures family (plus Exclusion for a repulsive well)."
        )
        place_row.addWidget(self.combo_type, 1)
        place_row.addWidget(QLabel("Radius:"))
        self.spin_radius = QDoubleSpinBox()
        self.spin_radius.setRange(0.2, 12.0)
        self.spin_radius.setDecimals(2)
        self.spin_radius.setSingleStep(0.1)
        self.spin_radius.setSuffix(" Å")
        self.spin_radius.setValue(default_feature_radius("Donor"))
        place_row.addWidget(self.spin_radius)
        root.addLayout(place_row)

        xyz_row = QHBoxLayout()
        xyz_row.addWidget(QLabel("X:"))
        self.spin_x = _coord_spin(0.0)
        xyz_row.addWidget(self.spin_x)
        xyz_row.addWidget(QLabel("Y:"))
        self.spin_y = _coord_spin(0.0)
        xyz_row.addWidget(self.spin_y)
        xyz_row.addWidget(QLabel("Z:"))
        self.spin_z = _coord_spin(0.0)
        xyz_row.addWidget(self.spin_z)
        self.btn_add_xyz = QPushButton("Add at coordinates")
        self.btn_add_xyz.setToolTip("Insert a feature at the X/Y/Z values (Å).")
        xyz_row.addWidget(self.btn_add_xyz)
        root.addLayout(xyz_row)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["On", "Type", "X", "Y", "Z", "r (Å)"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        for col in (_COL_X, _COL_Y, _COL_Z, _COL_R):
            header.setSectionResizeMode(col, QHeaderView.ResizeToContents)
        root.addWidget(self.table, 1)

        action_row = QHBoxLayout()
        self.btn_from_ligand = QPushButton("From ligand")
        self.btn_from_ligand.setToolTip(
            "Add RDKit BaseFeatures (donors, acceptors, aromatic centroids, …) from "
            "the selected ligand, or every ligand if none is selected."
        )
        self.btn_delete = QPushButton("Delete selected")
        self.btn_clear = QPushButton("Clear")
        action_row.addWidget(self.btn_from_ligand)
        action_row.addWidget(self.btn_delete)
        action_row.addWidget(self.btn_clear)
        action_row.addStretch()
        root.addLayout(action_row)

        file_row = QHBoxLayout()
        self.btn_open = QPushButton("Open…")
        self.btn_save = QPushButton("Save…")
        self.btn_gnina = QPushButton("Send to Gnina")
        self.btn_gnina.setToolTip(
            "Write the pharmacophore (if unsaved) and fill Protein → Dock Ligand → Gnina."
        )
        self.btn_close = QPushButton("Close")
        file_row.addWidget(self.btn_open)
        file_row.addWidget(self.btn_save)
        file_row.addWidget(self.btn_gnina)
        file_row.addStretch()
        file_row.addWidget(self.btn_close)
        root.addLayout(file_row)

        self.chk_place.toggled.connect(self.place_toggled.emit)
        self.combo_type.currentIndexChanged.connect(self._on_next_type_changed)
        self.btn_add_xyz.clicked.connect(self._on_add_xyz)
        self.btn_from_ligand.clicked.connect(self.from_ligand_clicked.emit)
        self.btn_delete.clicked.connect(self._on_delete_selected)
        self.btn_clear.clicked.connect(self.clear_clicked.emit)
        self.btn_open.clicked.connect(self.open_clicked.emit)
        self.btn_save.clicked.connect(self.save_clicked.emit)
        self.btn_gnina.clicked.connect(self.send_gnina_clicked.emit)
        self.btn_close.clicked.connect(self.close)
        self.table.itemChanged.connect(self._on_item_changed)
        make_window_minimizable(self)

    def next_type(self) -> str:
        return str(self.combo_type.currentData() or "Donor")

    def next_radius(self) -> float:
        return float(self.spin_radius.value())

    def set_place_mode(self, on: bool) -> None:
        self._updating = True
        self.chk_place.blockSignals(True)
        try:
            self.chk_place.setChecked(bool(on))
        finally:
            self.chk_place.blockSignals(False)
            self._updating = False

    def set_last_xyz(self, x: float, y: float, z: float) -> None:
        self._last_xyz = (float(x), float(y), float(z))
        self._updating = True
        try:
            self.spin_x.setValue(float(x))
            self.spin_y.setValue(float(y))
            self.spin_z.setValue(float(z))
        finally:
            self._updating = False

    def set_features(self, features: list[PharmacophoreFeature]) -> None:
        self._updating = True
        try:
            self.table.blockSignals(True)
            self.table.setRowCount(0)
            for feat in features:
                self._append_row(feat)
        finally:
            self.table.blockSignals(False)
            self._updating = False

    def _append_row(self, feat: PharmacophoreFeature) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        on_item = QTableWidgetItem()
        on_item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
        on_item.setCheckState(Qt.Checked if feat.enabled else Qt.Unchecked)
        on_item.setData(Qt.UserRole, feat.id)
        self.table.setItem(row, _COL_ON, on_item)
        combo = _type_combo(feat.type)
        combo.currentIndexChanged.connect(lambda _i, r=row: self._emit_row(r))
        self.table.setCellWidget(row, _COL_TYPE, combo)
        for col, value in (
            (_COL_X, feat.x),
            (_COL_Y, feat.y),
            (_COL_Z, feat.z),
            (_COL_R, feat.radius),
        ):
            item = QTableWidgetItem(f"{float(value):.3f}")
            item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.table.setItem(row, col, item)

    def _feature_at_row(self, row: int) -> PharmacophoreFeature | None:
        on_item = self.table.item(row, _COL_ON)
        if on_item is None:
            return None
        feat_id = str(on_item.data(Qt.UserRole) or f"f{row + 1}")
        combo = self.table.cellWidget(row, _COL_TYPE)
        kind = normalize_feature_type(str(combo.currentData() if combo is not None else "Donor"))

        def _num(col: int, fallback: float) -> float:
            item = self.table.item(row, col)
            try:
                return float((item.text() if item is not None else "") or fallback)
            except (TypeError, ValueError):
                return fallback

        return PharmacophoreFeature(
            id=feat_id,
            type=kind,
            x=_num(_COL_X, 0.0),
            y=_num(_COL_Y, 0.0),
            z=_num(_COL_Z, 0.0),
            radius=_num(_COL_R, default_feature_radius(kind)),
            enabled=on_item.checkState() == Qt.Checked,
        ).normalized()

    def _emit_row(self, row: int) -> None:
        if self._updating:
            return
        feat = self._feature_at_row(row)
        if feat is not None:
            self.feature_changed.emit(row, feat)

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if self._updating or item is None:
            return
        self._emit_row(item.row())

    def _on_next_type_changed(self) -> None:
        if self._updating:
            return
        kind = self.next_type()
        self.spin_radius.setValue(default_feature_radius(kind))

    def _on_add_xyz(self) -> None:
        self.add_at_coords.emit(
            self.next_type(),
            float(self.spin_x.value()),
            float(self.spin_y.value()),
            float(self.spin_z.value()),
            self.next_radius(),
        )

    def _on_delete_selected(self) -> None:
        rows = sorted({idx.row() for idx in self.table.selectedIndexes()}, reverse=True)
        for row in rows:
            self.feature_removed.emit(row)
