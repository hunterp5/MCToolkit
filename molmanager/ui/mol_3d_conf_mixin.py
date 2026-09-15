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

"""Conformer table, overlay scope, and 3Dmol.js navigation."""

from __future__ import annotations

import json
import logging

from PyQt5.QtCore import QItemSelectionModel, Qt
from PyQt5.QtGui import QKeySequence
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QHeaderView,
    QPushButton,
    QShortcut,
    QSizePolicy,
    QTableWidget,
    QHBoxLayout,
)

from .mol_3d_html import conf_legend_entries, distinct_superpose_colors
from .mol_3d_strain import _STRAIN_TABLE_BASE_HEADERS, populate_strain_energy_table

logger = logging.getLogger(__name__)


class Mol3DConfMixin:
    """Strain-energy table, selected-conformer overlay, and pose stepping."""

    def _build_strain_energy_table(self) -> QTableWidget:
        table = QTableWidget(0, len(_STRAIN_TABLE_BASE_HEADERS), self)
        table.setObjectName("StrainEnergyTable")
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        table.setSortingEnabled(True)
        table.setToolTip(
            "One row per conformer. Click a row to show that pose in 3D. "
            "Ctrl+click or Shift+click to select several. With Selected Conformers checked, "
            "the overlay follows the selection. Click a column header to sort."
        )
        table.setMinimumHeight(140)
        table.setMaximumHeight(240)
        table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        hdr = table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.Stretch)
        hdr.setSectionsClickable(True)
        hdr.setSortIndicatorShown(True)
        populate_strain_energy_table(table, self._strain_overlay)
        start = int(getattr(self, "_initial_conf_index", 0) or 0)
        table.blockSignals(True)
        try:
            self._select_strain_table_conf(table, start)
        finally:
            table.blockSignals(False)
        table.itemSelectionChanged.connect(self._on_strain_table_selection_changed)
        return table

    def _select_strain_table_conf(self, table: QTableWidget, conf_idx: int) -> None:
        want = int(conf_idx)
        for row in range(table.rowCount()):
            item = table.item(row, 0)
            if item is None:
                continue
            data = item.data(Qt.UserRole)
            try:
                if int(data) == want:
                    table.selectRow(row)
                    table.scrollToItem(item)
                    return
            except (TypeError, ValueError):
                continue

    def _highlight_current_conf_in_table(self, table: QTableWidget, conf_idx: int) -> None:
        """Move the current row marker without clearing a multi-row selection."""
        want = int(conf_idx)
        model = table.model()
        sm = table.selectionModel()
        if model is None or sm is None:
            return
        for row in range(table.rowCount()):
            item = table.item(row, 0)
            if item is None:
                continue
            data = item.data(Qt.UserRole)
            try:
                if int(data) != want:
                    continue
            except (TypeError, ValueError):
                continue
            index = model.index(row, 0)
            sm.setCurrentIndex(index, QItemSelectionModel.NoUpdate)
            table.scrollTo(index)
            return

    def _only_selected_in_3d(self) -> bool:
        cb = getattr(self, "_cb_only_selected_confs", None)
        return bool(cb is not None and cb.isChecked())

    def _selected_conf_indices(self) -> list[int]:
        table = self._strain_table
        if table is None:
            return []
        sm = table.selectionModel()
        if sm is None:
            return []
        out: list[int] = []
        for idx in sm.selectedRows():
            item = table.item(idx.row(), 0)
            if item is None:
                continue
            try:
                out.append(int(item.data(Qt.UserRole)))
            except (TypeError, ValueError):
                continue
        return sorted(set(out))

    def _visible_conf_indices(self) -> list[int]:
        n = int(self._conf_count)
        if n <= 0:
            return []
        if not self._only_selected_in_3d():
            return list(range(n))
        selected = [i for i in self._selected_conf_indices() if 0 <= i < n]
        return selected

    def _current_table_conf_index(self) -> int | None:
        table = self._strain_table
        if table is None:
            return None
        sm = table.selectionModel()
        if sm is None:
            return None
        cur = sm.currentIndex()
        if cur.isValid():
            item = table.item(cur.row(), 0)
            if item is not None:
                try:
                    return int(item.data(Qt.UserRole))
                except (TypeError, ValueError):
                    pass
        selected = self._selected_conf_indices()
        return selected[0] if selected else None

    def _on_strain_table_selection_changed(self) -> None:
        self._sync_superpose_enabled()
        if self._only_selected_in_3d():
            self._refresh_3d_from_scope()
            return
        self._sync_conf_legend()
        if self._conf_superposed:
            return
        idx = self._current_table_conf_index()
        if idx is not None:
            self._show_conformer(idx, preserve_selection=True)

    def _on_only_selected_confs_toggled(self, _checked: bool = False) -> None:
        self._sync_superpose_enabled()
        self._refresh_3d_from_scope()

    def _sync_superpose_enabled(self) -> None:
        cb = getattr(self, "_cb_superpose", None)
        if cb is None:
            return
        n_vis = len(self._visible_conf_indices())
        can_super = n_vis >= 2
        cb.setEnabled(can_super)
        if can_super:
            cb.setToolTip("Overlay conformers in the 3D view.")
        else:
            cb.setToolTip("Need at least two visible conformers to superpose.")
            if cb.isChecked():
                self._set_superpose_checked(False)
                self._conf_superposed = False

    def _wants_selected_superpose(self, vis: list[int] | None = None) -> bool:
        idxs = self._visible_conf_indices() if vis is None else vis
        return self._only_selected_in_3d() and len(idxs) >= 2

    def _conf_legend_payload(self) -> list[dict[str, str]] | None:
        """Legend entries when Selected Conformers is on and two-plus poses are overlaid."""
        if not self._only_selected_in_3d() or not self._conf_superposed:
            return None
        vis = self._visible_conf_indices()
        if len(vis) < 2:
            return None
        return conf_legend_entries(vis)

    def _sync_conf_legend(self) -> None:
        payload = self._conf_legend_payload()
        arg = "null" if not payload else json.dumps(payload)
        self._run_viewer_js(f"if (window.molmanagerSetConfLegend) molmanagerSetConfLegend({arg});")

    def _refresh_3d_from_scope(self) -> None:
        vis = self._visible_conf_indices()
        if self._wants_selected_superpose(vis) or (self._conf_superposed and len(vis) >= 2):
            self._show_superpose()
            return
        if not vis:
            self._conf_superposed = False
            self._set_superpose_checked(False)
            self._run_viewer_js("if (window.molmanagerShowSuperpose) molmanagerShowSuperpose([]);")
            self._sync_conf_legend()
            return
        if self._conf_idx not in vis:
            self._conf_idx = vis[0]
        self._show_conformer(self._conf_idx, preserve_selection=True)

    def _add_conf_nav_controls(self, row: QHBoxLayout) -> None:
        self._btn_conf_first = QPushButton("<<")
        self._btn_conf_first.setToolTip("First conformer (Home)")
        self._btn_conf_back = QPushButton("←")
        self._btn_conf_back.setToolTip("Previous conformer (←)")
        self._btn_conf_fwd = QPushButton("→")
        self._btn_conf_fwd.setToolTip("Next conformer (→)")
        self._btn_conf_last = QPushButton(">>")
        self._btn_conf_last.setToolTip("Last conformer (End)")
        for btn in (
            self._btn_conf_first,
            self._btn_conf_back,
            self._btn_conf_fwd,
            self._btn_conf_last,
        ):
            btn.setAutoDefault(False)
            btn.setDefault(False)
            row.addWidget(btn)

        self._cb_superpose = QCheckBox("Superpose")
        self._cb_superpose.setToolTip("Overlay conformers in the 3D view.")
        if self._conf_count < 2:
            self._cb_superpose.setEnabled(False)
            self._cb_superpose.setToolTip("Need at least two conformers to superpose.")
        self._cb_superpose.setChecked(
            bool(self._conf_superposed) and self._cb_superpose.isEnabled()
        )
        row.addWidget(self._cb_superpose)

        if self._strain_table is not None:
            self._cb_only_selected_confs = QCheckBox("Selected Conformers")
            self._cb_only_selected_confs.setToolTip(
                "When checked, the 3D view follows the table selection. "
                "Two or more selected rows are superposed, with a color legend on the right."
            )
            self._cb_only_selected_confs.toggled.connect(self._on_only_selected_confs_toggled)
            row.addWidget(self._cb_only_selected_confs)

        self._btn_conf_first.clicked.connect(self._go_first_conf)
        self._btn_conf_back.clicked.connect(lambda: self._step_conf(-1))
        self._btn_conf_fwd.clicked.connect(lambda: self._step_conf(1))
        self._btn_conf_last.clicked.connect(self._go_last_conf)
        self._cb_superpose.toggled.connect(self._on_conf_view_mode_toggled)

        for key, slot in (
            (Qt.Key_Home, self._go_first_conf),
            (Qt.Key_Left, lambda: self._step_conf(-1)),
            (Qt.Key_Right, lambda: self._step_conf(1)),
            (Qt.Key_End, self._go_last_conf),
        ):
            sc = QShortcut(QKeySequence(key), self)
            sc.setContext(Qt.WidgetWithChildrenShortcut)
            sc.activated.connect(slot)

    def _on_conf_view_mode_toggled(self, checked: bool) -> None:
        if getattr(self, "_conf_mode_busy", False):
            return
        self._conf_mode_busy = True
        try:
            if bool(checked):
                self._show_superpose()
            else:
                self._show_conformer(self._conf_idx, preserve_selection=True)
        finally:
            self._conf_mode_busy = False

    def _go_first_conf(self) -> None:
        vis = self._visible_conf_indices()
        if vis:
            self._show_conformer(vis[0], preserve_selection=True)

    def _go_last_conf(self) -> None:
        vis = self._visible_conf_indices()
        if vis:
            self._show_conformer(vis[-1], preserve_selection=True)

    def _step_conf(self, delta: int) -> None:
        vis = self._visible_conf_indices()
        if not vis:
            return
        try:
            pos = vis.index(self._conf_idx)
        except ValueError:
            pos = 0 if int(delta) >= 0 else len(vis) - 1
        else:
            pos = (pos + int(delta)) % len(vis)
        self._show_conformer(vis[pos], preserve_selection=True)

    def _run_viewer_js(self, script: str) -> None:
        web = getattr(self, "_standalone_web", None)
        if web is None:
            return
        try:
            web.page().runJavaScript(script)
        except Exception:
            logger.debug("viewer JS failed", exc_info=True)

    def _show_superpose(self) -> None:
        vis = self._visible_conf_indices()
        if len(vis) < 2:
            if vis:
                self._show_conformer(vis[0], preserve_selection=True)
            else:
                self._conf_superposed = False
                self._set_superpose_checked(False)
                self._run_viewer_js(
                    "if (window.molmanagerShowSuperpose) molmanagerShowSuperpose([]);"
                )
                self._sync_conf_legend()
            return
        was_superposed = bool(self._conf_superposed)
        self._conf_superposed = True
        self._set_superpose_checked(True)
        payload = json.dumps(vis) if self._only_selected_in_3d() else "null"
        zoom_js = "false" if was_superposed else "true"
        colors_js = json.dumps(distinct_superpose_colors(len(vis)))
        self._run_viewer_js(
            "if (window.molmanagerShowSuperpose) "
            f"molmanagerShowSuperpose({payload}, {{zoom: {zoom_js}, colors: {colors_js}}});"
        )
        self._sync_conf_legend()

    def _show_conformer(self, conf_idx: int, *, preserve_selection: bool = True) -> None:
        n = int(self._conf_count)
        if n <= 0:
            return
        vis = self._visible_conf_indices()
        idx = max(0, min(int(conf_idx), n - 1))
        if vis and idx not in vis:
            idx = vis[0]
        self._conf_idx = idx
        self._conf_superposed = False
        self._set_superpose_checked(False)
        table = self._strain_table
        if table is not None:
            table.blockSignals(True)
            try:
                if preserve_selection:
                    self._highlight_current_conf_in_table(table, idx)
                else:
                    self._select_strain_table_conf(table, idx)
            finally:
                table.blockSignals(False)
        self._run_viewer_js(f"if (window.molmanagerLoadConf) molmanagerLoadConf({idx});")
        self._sync_conf_legend()

    def _set_superpose_checked(self, superpose: bool) -> None:
        cb = getattr(self, "_cb_superpose", None)
        if cb is None:
            return
        cb.blockSignals(True)
        try:
            cb.setChecked(bool(superpose) and cb.isEnabled())
        finally:
            cb.blockSignals(False)
