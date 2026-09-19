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

"""Browse SALI pairs side-by-side with activity and properties."""

from __future__ import annotations

from typing import Any

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QImage, QPixmap
from PyQt5.QtWidgets import QLabel, QVBoxLayout
from rdkit import Chem
from rdkit.Chem.Draw import rdMolDraw2D

from ...analysis.sali_analysis import SaliPoint
from .chrome import configure_browser_mol_drawer, style_browser_emphasis_label
from .pair_browser import PairBrowserDialog


class SaliBrowserDialog(PairBrowserDialog):
    """Step through SALI pairs: two molecules, activities, similarity, and SALI."""

    window_title = "SALI Pairs"
    select_status = "SALI pair"

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
        self._all_points = list(points)
        self._points = list(points)
        self._fp_choice = fp_choice or ""
        self._metric = metric or "Tanimoto"
        self._idx = max(0, int(start_index))
        if self._all_points and 0 <= self._idx < len(self._all_points):
            p0 = self._all_points[self._idx]
            self._prefer_keys = (int(p0.oid_a), int(p0.oid_b))
        super().__init__(parent, activity_column=activity_column)

    def _populate_header(self, root: QVBoxLayout) -> None:
        self._metrics_label = QLabel()
        self._metrics_label.setAlignment(Qt.AlignCenter)
        self._metrics_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._metrics_label.setWordWrap(True)
        style_browser_emphasis_label(self._metrics_label)
        root.addWidget(self._metrics_label)

    def _item_count(self) -> int:
        return len(self._points)

    def _current_pair_oids(self) -> tuple[int, int] | None:
        point = self._current_point()
        if point is None:
            return None
        return (int(point.oid_a), int(point.oid_b))

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
                source = [p for p in source if int(p.oid_a) in selected or int(p.oid_b) in selected]
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

    def _activity_for_oid(self, oid: int) -> float | None:
        header = self._activity_column
        if not header:
            return None
        text = self._cell_text_for_oid(int(oid), header)
        if not text:
            return None
        try:
            return float(text.replace(",", ""))
        except ValueError:
            return None

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
        self._sync_nav_enabled(count=n)
        if n <= 0:
            if self._cb_selected_only.isChecked():
                self._meta.setText("No SALI pairs involve the current table selection.")
            else:
                self._meta.setText("No SALI pairs to browse.")
            self._metrics_label.setText("")
            self._clear_pair_panels()
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
            configure_browser_mol_drawer(drawer, pw)
            rdMolDraw2D.PrepareAndDrawMolecule(drawer, mol)
            drawer.FinishDrawing()
            img = QImage.fromData(drawer.GetDrawingText())
            return QPixmap.fromImage(img)
        except Exception:
            return None
