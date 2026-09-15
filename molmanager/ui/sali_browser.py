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

"""Modeless dialog: browse SALI pairs side-by-side with activity and properties."""

from __future__ import annotations

from typing import Any

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QImage, QKeySequence, QPixmap
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QShortcut,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from rdkit import Chem
from rdkit.Chem.Draw import rdMolDraw2D

from ..display_constants import (
    BROWSER_STRUCTURE_PREVIEW_MIN_HEIGHT,
    BROWSER_STRUCTURE_PREVIEW_MIN_WIDTH,
)
from ..sali_analysis import SaliPoint
from .qt_widget_utils import make_window_minimizable


def _try_configure_drawer(drawer, width: int) -> None:
    try:
        from ..structure_draw import configure_mol_drawer as cfg

        cfg(drawer, width)
    except Exception:
        pass


class SaliBrowserDialog(QDialog):
    """Step through SALI pairs: two molecules, activities, similarity, and SALI."""

    def __init__(
        self,
        parent: Any,
        points: list[SaliPoint],
        *,
        activity_column: str,
        fp_choice: str = "",
        metric: str = "Tanimoto",
        start_index: int = 0,
    ):
        super().__init__(parent)
        self._app = parent
        self._all_points = list(points)
        self._points = list(points)
        self._activity_column = activity_column
        self._fp_choice = fp_choice or ""
        self._metric = metric or "Tanimoto"
        self._idx = max(0, int(start_index))
        self._preview_cache: dict[tuple, QPixmap] = {}
        self._prefer_keys: tuple[int, int] | None = None
        if self._all_points and 0 <= self._idx < len(self._all_points):
            p0 = self._all_points[self._idx]
            self._prefer_keys = (int(p0.oid_a), int(p0.oid_b))

        self.setWindowTitle("SALI Pairs")
        self.resize(920, 620)
        self.setModal(False)
        self.setWindowModality(Qt.NonModal)

        root = QVBoxLayout(self)
        self._meta = QLabel()
        self._meta.setAlignment(Qt.AlignCenter)
        root.addWidget(self._meta)

        self._metrics_label = QLabel()
        self._metrics_label.setAlignment(Qt.AlignCenter)
        self._metrics_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._metrics_label.setWordWrap(True)
        self._metrics_label.setStyleSheet("font-weight: 600;")
        root.addWidget(self._metrics_label)

        pair_row = QHBoxLayout()
        self._left_panel = self._make_mol_panel("Molecule A")
        self._right_panel = self._make_mol_panel("Molecule B")
        pair_row.addWidget(self._left_panel["box"], 1)
        pair_row.addWidget(self._right_panel["box"], 1)
        root.addLayout(pair_row, 1)

        self._prop_box = QGroupBox()
        self._prop_box.setStyleSheet(
            "QGroupBox { margin-top: 10px; background-color: palette(base); "
            "border: 1px solid palette(mid); border-radius: 4px; }"
        )
        self._prop_form = QFormLayout(self._prop_box)
        self._prop_form.setLabelAlignment(Qt.AlignRight)
        self._prop_form.setFormAlignment(Qt.AlignTop)
        self._prop_form.setContentsMargins(12, 12, 12, 10)
        self._prop_form.setVerticalSpacing(8)
        self._prop_form.setHorizontalSpacing(10)

        self._prop_combo_1 = QComboBox()
        self._prop_combo_2 = QComboBox()
        self._prop_combo_3 = QComboBox()
        for cb in (self._prop_combo_1, self._prop_combo_2, self._prop_combo_3):
            cb.setSizeAdjustPolicy(QComboBox.AdjustToContents)

        self._prop_value_1 = self._make_prop_value_row()
        self._prop_value_2 = self._make_prop_value_row()
        self._prop_value_3 = self._make_prop_value_row()

        self._prop_form.addRow(self._prop_combo_1, self._prop_value_1["host"])
        self._prop_form.addRow(self._prop_combo_2, self._prop_value_2["host"])
        self._prop_form.addRow(self._prop_combo_3, self._prop_value_3["host"])
        root.addWidget(self._prop_box)

        nav = QHBoxLayout()
        self._btn_first = QPushButton("<<")
        self._btn_first.setToolTip("First pair (Home)")
        self._btn_back = QPushButton("←")
        self._btn_back.setToolTip("Previous pair (←)")
        self._btn_fwd = QPushButton("→")
        self._btn_fwd.setToolTip("Next pair (→)")
        self._btn_last = QPushButton(">>")
        self._btn_last.setToolTip("Last pair (End)")
        self._btn_select = QPushButton("Select pair in table")
        self._btn_select.setToolTip("Select both molecules of this pair in the main table")
        self._cb_selected_only = QCheckBox("Selected Only")
        self._cb_selected_only.setToolTip(
            "When checked, browse only pairs that involve at least one molecule "
            "from the current table selection."
        )
        nav.addWidget(self._btn_first)
        nav.addWidget(self._btn_back)
        nav.addWidget(self._btn_fwd)
        nav.addWidget(self._btn_last)
        nav.addWidget(self._btn_select)
        nav.addWidget(self._cb_selected_only)
        nav.addStretch()
        root.addLayout(nav)

        self._btn_first.clicked.connect(self._go_first)
        self._btn_back.clicked.connect(lambda: self._step(-1))
        self._btn_fwd.clicked.connect(lambda: self._step(1))
        self._btn_last.clicked.connect(self._go_last)
        self._btn_select.clicked.connect(self._select_current_pair)
        self._cb_selected_only.toggled.connect(self._on_selected_only_toggled)
        self._prop_combo_1.currentIndexChanged.connect(lambda _i: self._update_property_values())
        self._prop_combo_2.currentIndexChanged.connect(lambda _i: self._update_property_values())
        self._prop_combo_3.currentIndexChanged.connect(lambda _i: self._update_property_values())

        QShortcut(QKeySequence(Qt.Key_Home), self, activated=self._go_first)
        QShortcut(QKeySequence(Qt.Key_Left), self, activated=lambda: self._step(-1))
        QShortcut(QKeySequence(Qt.Key_Right), self, activated=lambda: self._step(1))
        QShortcut(QKeySequence(Qt.Key_End), self, activated=self._go_last)

        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.setInterval(60)
        self._resize_timer.timeout.connect(self._refresh_previews)

        make_window_minimizable(self)
        self.setModal(False)
        self.setWindowModality(Qt.NonModal)
        self._refresh_property_columns()
        self._update_ui()

    @staticmethod
    def _make_prop_value_row() -> dict[str, Any]:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)
        lab_a = QLabel("—")
        lab_b = QLabel("—")
        for lab in (lab_a, lab_b):
            lab.setTextInteractionFlags(Qt.TextSelectableByMouse)
            lab.setWordWrap(True)
            lab.setMinimumWidth(120)
        row.addWidget(lab_a, 1)
        row.addWidget(lab_b, 1)
        field = QWidget()
        field.setLayout(row)
        return {"host": field, "a": lab_a, "b": lab_b}

    def _make_mol_panel(self, title: str) -> dict[str, Any]:
        box = QGroupBox(title)
        lyt = QVBoxLayout(box)
        struct = QLabel()
        struct.setAlignment(Qt.AlignCenter)
        struct.setMinimumSize(
            BROWSER_STRUCTURE_PREVIEW_MIN_WIDTH // 2,
            BROWSER_STRUCTURE_PREVIEW_MIN_HEIGHT // 2,
        )
        struct.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        struct.setStyleSheet(
            "background-color: palette(base); border: 1px solid palette(mid); border-radius: 4px;"
        )
        activity = QLabel("—")
        activity.setAlignment(Qt.AlignCenter)
        activity.setTextInteractionFlags(Qt.TextSelectableByMouse)
        activity.setWordWrap(True)
        lyt.addWidget(struct, 1)
        lyt.addWidget(activity)
        return {"box": box, "struct": struct, "activity": activity}

    def set_points(
        self,
        points: list[SaliPoint],
        *,
        activity_column: str | None = None,
        fp_choice: str | None = None,
        metric: str | None = None,
        start_index: int | None = None,
    ) -> None:
        """Replace the pair list and refresh the view."""
        self._all_points = list(points or [])
        if activity_column is not None:
            self._activity_column = activity_column
        if fp_choice is not None:
            self._fp_choice = fp_choice
        if metric is not None:
            self._metric = metric
        prefer: tuple[int, int] | None = None
        if start_index is not None and self._all_points:
            si = max(0, min(int(start_index), len(self._all_points) - 1))
            p0 = self._all_points[si]
            prefer = (int(p0.oid_a), int(p0.oid_b))
        elif self._all_points:
            prefer = (int(self._all_points[0].oid_a), int(self._all_points[0].oid_b))
        self._prefer_keys = prefer
        self._preview_cache.clear()
        self._refresh_property_columns()
        self._rebuild_filtered_points(update_ui=True)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._resize_timer.start()

    def _selected_oids(self) -> set[int]:
        app = self._app
        if app is None:
            return set()
        try:
            return {int(o) for o in app._selected_oids_set()}
        except Exception:
            return set()

    def _on_selected_only_toggled(self, _checked: bool) -> None:
        cur = self._current_point()
        if cur is not None:
            self._prefer_keys = (int(cur.oid_a), int(cur.oid_b))
        self._rebuild_filtered_points(update_ui=True)

    def _rebuild_filtered_points(self, *, update_ui: bool) -> None:
        source = list(self._all_points)
        if self._cb_selected_only.isChecked():
            selected = self._selected_oids()
            if selected:
                source = [
                    p
                    for p in source
                    if int(p.oid_a) in selected or int(p.oid_b) in selected
                ]
            else:
                source = []
        self._points = source
        prefer = self._prefer_keys
        self._idx = 0
        if prefer is not None:
            for i, p in enumerate(self._points):
                if (int(p.oid_a), int(p.oid_b)) == prefer:
                    self._idx = i
                    break
        if update_ui:
            self._update_ui()

    def _current_point(self) -> SaliPoint | None:
        if not self._points or not (0 <= self._idx < len(self._points)):
            return None
        return self._points[self._idx]

    def _go_first(self) -> None:
        self._idx = 0
        self._update_ui()

    def _go_last(self) -> None:
        self._idx = max(0, len(self._points) - 1)
        self._update_ui()

    def _step(self, delta: int) -> None:
        if not self._points:
            return
        self._idx = (self._idx + int(delta)) % len(self._points)
        self._update_ui()

    def _select_current_pair(self) -> None:
        point = self._current_point()
        app = self._app
        if point is None or app is None:
            return
        try:
            app.select_table_oids([point.oid_a, point.oid_b], extra_status="SALI pair")
        except Exception:
            pass

    def _activity_for_oid(self, oid: int) -> float | None:
        app = self._app
        header = self._activity_column
        if app is None or not header:
            return None
        text = self._cell_text_for_oid(int(oid), header)
        if not text:
            return None
        try:
            return float(text.replace(",", ""))
        except ValueError:
            return None

    def _refresh_property_columns(self) -> None:
        try:
            headers = list(getattr(self._app, "headers", []) or [])
        except Exception:
            headers = []
        choices = [h for h in headers if h not in ("ID_HIDDEN", "Structure")]
        combos = (self._prop_combo_1, self._prop_combo_2, self._prop_combo_3)
        prev = [cb.currentText() for cb in combos]
        for cb in combos:
            cb.blockSignals(True)
            cb.clear()
            cb.addItem("—", userData=None)
            for h in choices:
                cb.addItem(h, userData=h)
            cb.blockSignals(False)
        for cb, p in zip(combos, prev, strict=False):
            if p and p != "—":
                j = cb.findText(p)
                if j >= 0:
                    cb.setCurrentIndex(j)

        def _set_default(cb: QComboBox, prefer: list[str]) -> None:
            if cb.currentData() is not None:
                return
            for h in prefer:
                j = cb.findText(h)
                if j >= 0:
                    cb.setCurrentIndex(j)
                    return

        act = self._activity_column
        _set_default(self._prop_combo_1, [act, "SMILES", "Name", "CompoundName", "ID"])
        _set_default(self._prop_combo_2, ["Name", "CompoundName", "CAS", "InChIKey", "SMILES"])
        _set_default(self._prop_combo_3, ["MW", "MolWt", "cLogP", "LogP", "TPSA"])

    def _cell_text_for_oid(self, oid: int, header: str) -> str:
        app = self._app
        if app is None or not header:
            return ""
        try:
            row = app.logical_row_for_oid(int(oid))
        except Exception:
            return ""
        if row is None or row < 0:
            return ""
        try:
            col = int(app.headers.index(header))
        except Exception:
            return ""
        try:
            text = (app._table_cell_text(row, col) or "").strip()
            if not text:
                text = (app._table_model.backing_value_for_row_header(row, header) or "").strip()
            return text
        except Exception:
            return ""

    def _update_property_values(self) -> None:
        point = self._current_point()
        rows = [
            (self._prop_combo_1, self._prop_value_1),
            (self._prop_combo_2, self._prop_value_2),
            (self._prop_combo_3, self._prop_value_3),
        ]
        if point is None:
            for _cb, vals in rows:
                vals["a"].setText("—")
                vals["b"].setText("—")
            return
        for cb, vals in rows:
            h = cb.currentData()
            if not h:
                vals["a"].setText("—")
                vals["b"].setText("—")
                continue
            va = self._cell_text_for_oid(point.oid_a, str(h))
            vb = self._cell_text_for_oid(point.oid_b, str(h))
            vals["a"].setText(f"A: {va}" if va else "A: —")
            vals["b"].setText(f"B: {vb}" if vb else "B: —")

    def _refresh_previews(self) -> None:
        point = self._current_point()
        if point is None:
            return
        act_a = self._activity_for_oid(point.oid_a)
        act_b = self._activity_for_oid(point.oid_b)
        self._update_molecule_panel(self._left_panel, point.oid_a, act_a)
        self._update_molecule_panel(self._right_panel, point.oid_b, act_b)

    def _update_ui(self) -> None:
        n = len(self._points)
        has = n > 0
        self._btn_first.setEnabled(has)
        self._btn_last.setEnabled(has)
        self._btn_back.setEnabled(n > 1)
        self._btn_fwd.setEnabled(n > 1)
        self._btn_select.setEnabled(has)
        if not has:
            if self._cb_selected_only.isChecked():
                self._meta.setText("No SALI pairs involve the current table selection.")
            else:
                self._meta.setText("No SALI pairs to browse.")
            self._metrics_label.setText("")
            for panel in (self._left_panel, self._right_panel):
                panel["struct"].clear()
                panel["struct"].setPixmap(QPixmap())
                panel["activity"].setText("—")
            self._update_property_values()
            return

        self._idx = max(0, min(self._idx, n - 1))
        point = self._points[self._idx]
        fp_txt = self._fp_choice or "fingerprint"
        self._meta.setText(f"Pair {self._idx + 1} of {n}  ·  {fp_txt} / {self._metric}")
        sign = "+" if point.signed_delta >= 0 else ""
        self._metrics_label.setText(
            f"similarity = {point.similarity:.3f}  ·  "
            f"Δ{self._activity_column} = {sign}{point.signed_delta:.4g}  ·  "
            f"SALI = {point.sali:.4g}"
        )
        self._left_panel["box"].setTitle(f"Molecule A  (ID {point.oid_a})")
        self._right_panel["box"].setTitle(f"Molecule B  (ID {point.oid_b})")
        self._refresh_previews()
        self._update_property_values()

    def _mol_for_oid(self, oid: int) -> Chem.Mol | None:
        app = self._app
        if app is None:
            return None
        return getattr(app, "mols", {}).get(int(oid))

    def _preview_pixel_size(self, label: QLabel) -> tuple[int, int, float]:
        dpr = max(1.0, float(self.devicePixelRatioF()))
        lw = max(label.width(), BROWSER_STRUCTURE_PREVIEW_MIN_WIDTH // 2)
        lh = max(label.height(), BROWSER_STRUCTURE_PREVIEW_MIN_HEIGHT // 2)
        return int(lw * dpr), int(lh * dpr), dpr

    def _update_molecule_panel(
        self,
        panel: dict[str, Any],
        oid: int,
        activity: float | None,
    ) -> None:
        label: QLabel = panel["struct"]
        if activity is None:
            panel["activity"].setText(f"{self._activity_column}: —")
        else:
            panel["activity"].setText(f"{self._activity_column}: {activity:.4g}")
        mol = self._mol_for_oid(oid)
        pw, ph, dpr = self._preview_pixel_size(label)
        if mol is None:
            label.clear()
            label.setPixmap(QPixmap())
            label.setText("(no structure)")
            return

        cache_key = (int(oid), pw, ph)
        cached = self._preview_cache.get(cache_key)
        if cached is not None and not cached.isNull():
            pm = cached
        else:
            pm = self._render_mol(mol, pw, ph)
            if pm is not None and not pm.isNull():
                self._preview_cache[cache_key] = pm
        if pm is None or pm.isNull():
            label.clear()
            label.setPixmap(QPixmap())
            label.setText("(render failed)")
            return
        if pm.width() != pw or pm.height() != ph:
            pm = pm.scaled(pw, ph, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        pm.setDevicePixelRatio(dpr)
        label.setPixmap(pm)
        label.setText("")

    def _render_mol(self, mol: Chem.Mol, pw: int, ph: int) -> QPixmap | None:
        try:
            drawer = rdMolDraw2D.MolDraw2DCairo(pw, ph)
            _try_configure_drawer(drawer, pw)
            rdMolDraw2D.PrepareAndDrawMolecule(drawer, mol)
            drawer.FinishDrawing()
            img = QImage.fromData(drawer.GetDrawingText())
            return QPixmap.fromImage(img)
        except Exception:
            return None
