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

"""Modeless dialog: browse matched molecular pairs side-by-side with activity and highlights."""

from __future__ import annotations

from typing import Any

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QImage, QKeySequence, QPainter, QPixmap
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
from ..mmp_analysis import (
    MmpPair,
    assemble_mmp_table_annotations,
    canonicalize_pair_direction,
    highlight_atoms_for_pair,
)
from .qt_widget_utils import make_window_minimizable


def _try_configure_drawer(drawer, width: int) -> None:
    try:
        from ..structure_draw import configure_mol_drawer as cfg

        cfg(drawer, width)
    except Exception:
        pass


class MmpBrowserDialog(QDialog):
    """Step through MMP pairs: two molecules, activities, Δactivity, and table properties."""

    def __init__(
        self,
        parent: Any,
        pairs: list[MmpPair],
        *,
        activity_column: str,
    ):
        super().__init__(parent)
        self._app = parent
        self._all_pairs = list(pairs)
        self._pairs = list(pairs)
        self._activity_column = activity_column
        self._idx = 0
        self._preview_cache: dict[tuple, QPixmap] = {}
        self._prefer_keys: tuple[int, int] | None = None

        self.setWindowTitle("Matched Molecular Pairs")
        self.resize(920, 620)
        # Keep the main table interactive while this window is open (same as Sketcher / Processes).
        self.setModal(False)
        self.setWindowModality(Qt.NonModal)

        root = QVBoxLayout(self)
        self._meta = QLabel()
        self._meta.setAlignment(Qt.AlignCenter)
        root.addWidget(self._meta)

        self._transform_preview = QLabel()
        self._transform_preview.setAlignment(Qt.AlignCenter)
        self._transform_preview.setMinimumHeight(72)
        self._transform_preview.setMaximumHeight(88)
        self._transform_preview.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        root.addWidget(self._transform_preview)

        self._delta_label = QLabel()
        self._delta_label.setAlignment(Qt.AlignCenter)
        self._delta_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._delta_label.setWordWrap(True)
        self._delta_label.setStyleSheet("font-weight: 600;")
        root.addWidget(self._delta_label)

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
        self._btn_write = QPushButton("Write to table")
        self._btn_write.setToolTip(
            "Write MMP_Partners / MMP_Transforms / MMP_Delta columns for all pairs"
        )
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
        nav.addWidget(self._btn_write)
        nav.addWidget(self._cb_selected_only)
        nav.addStretch()
        root.addLayout(nav)

        self._btn_first.clicked.connect(self._go_first)
        self._btn_back.clicked.connect(lambda: self._step(-1))
        self._btn_fwd.clicked.connect(lambda: self._step(1))
        self._btn_last.clicked.connect(self._go_last)
        self._btn_select.clicked.connect(self._select_current_pair)
        self._btn_write.clicked.connect(self._write_all_to_table)
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
        self._highlight_cache: dict[tuple[int, int], tuple[list[int], list[int]]] = {}

        make_window_minimizable(self)
        # setWindowFlags (used above) can reset modality on some platforms — re-assert NonModal.
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

    def set_pairs(self, pairs: list[MmpPair], *, activity_column: str | None = None) -> None:
        """Replace the pair list (e.g. when re-running MMP) and refresh the view."""
        self._all_pairs = list(pairs or [])
        if activity_column is not None:
            self._activity_column = activity_column
        prefer: tuple[int, int] | None = None
        if self._all_pairs:
            p0 = self._all_pairs[0]
            prefer = (int(p0.oid_a), int(p0.oid_b))
        self._prefer_keys = prefer
        self._preview_cache.clear()
        self._highlight_cache.clear()
        self._refresh_property_columns()
        self._rebuild_filtered_pairs(update_ui=True)

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
        cur = self._current_pair()
        if cur is not None:
            self._prefer_keys = (int(cur.oid_a), int(cur.oid_b))
        self._rebuild_filtered_pairs(update_ui=True)

    def _rebuild_filtered_pairs(self, *, update_ui: bool) -> None:
        source = list(self._all_pairs)
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
        self._pairs = source
        prefer = self._prefer_keys
        self._idx = 0
        if prefer is not None:
            for i, p in enumerate(self._pairs):
                if (int(p.oid_a), int(p.oid_b)) == prefer:
                    self._idx = i
                    break
        if update_ui:
            self._update_ui()

    def _current_pair(self) -> MmpPair | None:
        if not self._pairs or not (0 <= self._idx < len(self._pairs)):
            return None
        return self._pairs[self._idx]

    def _go_first(self) -> None:
        self._idx = 0
        self._update_ui()

    def _go_last(self) -> None:
        self._idx = max(0, len(self._pairs) - 1)
        self._update_ui()

    def _step(self, delta: int) -> None:
        if not self._pairs:
            return
        self._idx = (self._idx + int(delta)) % len(self._pairs)
        self._update_ui()

    def _select_current_pair(self) -> None:
        pair = self._current_pair()
        app = self._app
        if pair is None or app is None:
            return
        try:
            app.select_table_oids([pair.oid_a, pair.oid_b], extra_status="MMP pair")
        except Exception:
            pass

    def _write_all_to_table(self) -> None:
        app = self._app
        if app is None or not self._all_pairs:
            return
        rows, headers = assemble_mmp_table_annotations(
            self._all_pairs, activity_column=self._activity_column
        )
        if not rows:
            return
        try:
            app.on_calc_finished(rows, headers, progress_label="MMP")
        except Exception:
            pass

    def _refresh_property_columns(self) -> None:
        """Populate the 3 column pickers from current table headers, preserving selections."""
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
            row = app.get_row_by_id(int(oid))
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
        pair = self._current_pair()
        rows = [
            (self._prop_combo_1, self._prop_value_1),
            (self._prop_combo_2, self._prop_value_2),
            (self._prop_combo_3, self._prop_value_3),
        ]
        if pair is None:
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
            va = self._cell_text_for_oid(pair.oid_a, str(h))
            vb = self._cell_text_for_oid(pair.oid_b, str(h))
            vals["a"].setText(f"A: {va}" if va else "A: —")
            vals["b"].setText(f"B: {vb}" if vb else "B: —")

    def _refresh_previews(self) -> None:
        pair = self._current_pair()
        if pair is None:
            return
        self._update_molecule_panel(self._left_panel, pair.oid_a, pair.activity_a, pair, side="a")
        self._update_molecule_panel(self._right_panel, pair.oid_b, pair.activity_b, pair, side="b")

    def _update_ui(self) -> None:
        n = len(self._pairs)
        has = n > 0
        self._btn_first.setEnabled(has)
        self._btn_last.setEnabled(has)
        self._btn_back.setEnabled(n > 1)
        self._btn_fwd.setEnabled(n > 1)
        self._btn_select.setEnabled(has)
        self._btn_write.setEnabled(has)
        if not has:
            if self._cb_selected_only.isChecked():
                self._meta.setText("No matched molecular pairs involve the current table selection.")
            else:
                self._meta.setText("No matched molecular pairs found.")
            self._delta_label.setText("")
            self._transform_preview.clear()
            self._transform_preview.setPixmap(QPixmap())
            self._transform_preview.setToolTip("")
            for panel in (self._left_panel, self._right_panel):
                panel["struct"].clear()
                panel["struct"].setPixmap(QPixmap())
                panel["activity"].setText("—")
            self._update_property_values()
            return

        self._idx = max(0, min(self._idx, n - 1))
        pair = self._pairs[self._idx]
        self._meta.setText(f"Pair {self._idx + 1} of {n}")
        sign = "+" if pair.delta_activity >= 0 else ""
        canon_transform, side_from, side_to, _cd = canonicalize_pair_direction(pair)
        self._delta_label.setText(
            f"Δ{self._activity_column} = {sign}{pair.delta_activity:.4g}  "
            f"({pair.activity_a:.4g} → {pair.activity_b:.4g})"
        )
        self._delta_label.setToolTip(canon_transform)
        self._update_transform_preview(side_from, side_to, canon_transform)
        self._left_panel["box"].setTitle(f"Molecule A  (ID {pair.oid_a})")
        self._right_panel["box"].setTitle(f"Molecule B  (ID {pair.oid_b})")
        self._refresh_previews()
        self._update_property_values()

    def _update_transform_preview(self, side_from: str, side_to: str, transform: str) -> None:
        frag_w, frag_h, arrow_w = 96, 64, 28
        left = self._render_frag_smiles(side_from, frag_w, frag_h)
        right = self._render_frag_smiles(side_to, frag_w, frag_h)
        if left is None and right is None:
            self._transform_preview.clear()
            self._transform_preview.setPixmap(QPixmap())
            self._transform_preview.setText("→")
            self._transform_preview.setToolTip(transform)
            return
        if left is None:
            left = QPixmap(frag_w, frag_h)
            left.fill(Qt.transparent)
        if right is None:
            right = QPixmap(frag_w, frag_h)
            right.fill(Qt.transparent)
        out = QPixmap(frag_w + arrow_w + frag_w, frag_h)
        out.fill(Qt.transparent)
        painter = QPainter(out)
        try:
            painter.drawPixmap(0, 0, left)
            painter.setPen(self.palette().color(self.palette().WindowText))
            painter.drawText(frag_w, 0, arrow_w, frag_h, Qt.AlignCenter, "→")
            painter.drawPixmap(frag_w + arrow_w, 0, right)
        finally:
            painter.end()
        dpr = max(1.0, float(self.devicePixelRatioF()))
        out.setDevicePixelRatio(dpr)
        self._transform_preview.setPixmap(out)
        self._transform_preview.setText("")
        self._transform_preview.setToolTip(transform)

    def _render_frag_smiles(self, smiles: str, pw: int, ph: int) -> QPixmap | None:
        if not smiles:
            return None
        cache_key = ("frag", smiles, pw, ph)
        cached = self._preview_cache.get(cache_key)
        if cached is not None and not cached.isNull():
            return cached
        try:
            mol = Chem.MolFromSmiles(smiles)
        except Exception:
            mol = None
        if mol is None:
            return None
        pm = self._render_highlighted(mol, pw, ph, [])
        if pm is not None and not pm.isNull():
            self._preview_cache[cache_key] = pm
        return pm

    def _highlights_for_pair(self, pair: MmpPair) -> tuple[list[int], list[int]]:
        key = (pair.oid_a, pair.oid_b)
        cached = self._highlight_cache.get(key)
        if cached is not None:
            return cached
        mol_a = self._mol_for_oid(pair.oid_a, pair.smiles_a)
        mol_b = self._mol_for_oid(pair.oid_b, pair.smiles_b)
        ha, hb = highlight_atoms_for_pair(mol_a, mol_b) if mol_a and mol_b else ([], [])
        self._highlight_cache[key] = (ha, hb)
        return ha, hb

    def _mol_for_oid(self, oid: int, fallback_smiles: str) -> Chem.Mol | None:
        app = self._app
        mol = None
        if app is not None:
            mol = getattr(app, "mols", {}).get(oid)
        if mol is None and fallback_smiles:
            try:
                mol = Chem.MolFromSmiles(fallback_smiles)
            except Exception:
                mol = None
        return mol

    def _preview_pixel_size(self, label: QLabel) -> tuple[int, int, float]:
        dpr = max(1.0, float(self.devicePixelRatioF()))
        lw = max(label.width(), BROWSER_STRUCTURE_PREVIEW_MIN_WIDTH // 2)
        lh = max(label.height(), BROWSER_STRUCTURE_PREVIEW_MIN_HEIGHT // 2)
        return int(lw * dpr), int(lh * dpr), dpr

    def _update_molecule_panel(
        self,
        panel: dict[str, Any],
        oid: int,
        activity: float,
        pair: MmpPair,
        *,
        side: str,
    ) -> None:
        label: QLabel = panel["struct"]
        panel["activity"].setText(f"{self._activity_column}: {activity:.4g}")
        smiles = pair.smiles_a if side == "a" else pair.smiles_b
        mol = self._mol_for_oid(oid, smiles)
        pw, ph, dpr = self._preview_pixel_size(label)
        if mol is None:
            label.clear()
            label.setPixmap(QPixmap())
            label.setText("(no structure)")
            return

        ha, hb = self._highlights_for_pair(pair)
        highlight = ha if side == "a" else hb
        highlight_key = tuple(sorted(highlight))
        cache_key = (oid, pw, ph, pair.oid_a, pair.oid_b, pair.transform, highlight_key)
        cached = self._preview_cache.get(cache_key)
        if cached is not None and not cached.isNull():
            pm = cached
        else:
            pm = self._render_highlighted(mol, pw, ph, highlight)
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

    def _render_highlighted(
        self,
        mol: Chem.Mol,
        pw: int,
        ph: int,
        highlight_atoms: list[int],
    ) -> QPixmap | None:
        try:
            drawer = rdMolDraw2D.MolDraw2DCairo(pw, ph)
            _try_configure_drawer(drawer, pw)
            highlight_set = set(int(i) for i in highlight_atoms)
            colors = {i: (0.95, 0.55, 0.15) for i in highlight_set}
            if highlight_set:
                rdMolDraw2D.PrepareAndDrawMolecule(
                    drawer,
                    mol,
                    highlightAtoms=list(highlight_set),
                    highlightAtomColors=colors,
                )
            else:
                rdMolDraw2D.PrepareAndDrawMolecule(drawer, mol)
            drawer.FinishDrawing()
            img = QImage.fromData(drawer.GetDrawingText())
            return QPixmap.fromImage(img)
        except Exception:
            return None
