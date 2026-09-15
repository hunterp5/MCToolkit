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


"""Right-hand chain list for the protein viewer."""

from __future__ import annotations


from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .protein_viewer_models import (
    _ComponentView,
    _ID_ROLE,
    _KIND_ROLE,
    _STRUCT_ROLE,
)


class ProteinChainManager(QWidget):
    """Right-hand chain list for selecting components."""

    visibility_changed = pyqtSignal(str, bool)
    selection_changed = pyqtSignal(list)
    focus_requested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setMinimumWidth(240)
        self._syncing = False
        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(0)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Name", "Count"])
        self.tree.setRootIsDecorated(True)
        self.tree.setUniformRowHeights(True)
        self.tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.tree.header().setStretchLastSection(False)
        self.tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.tree.itemChanged.connect(self._on_item_changed)
        self.tree.itemSelectionChanged.connect(self._on_selection_changed)
        self.tree.itemDoubleClicked.connect(lambda *_a: self.focus_requested.emit())
        root.addWidget(self.tree, 1)

    def selected_component_ids(self) -> list[str]:
        ids: list[str] = []
        seen: set[str] = set()

        def _add(cid: str) -> None:
            if cid and cid not in seen:
                seen.add(cid)
                ids.append(cid)

        def _collect(item: QTreeWidgetItem) -> None:
            cid = item.data(0, _ID_ROLE)
            if cid:
                _add(cid)
            for i in range(item.childCount()):
                _collect(item.child(i))

        for item in self.tree.selectedItems():
            _collect(item)
        return ids

    def set_structure(
        self,
        rows: list[_ComponentView],
        *,
        filename: str = "",
        groups: list[tuple[str, str]] | None = None,
    ) -> None:
        self._syncing = True
        self.tree.clear()
        if not rows:
            self._syncing = False
            return
        by_sid: dict[str, list[_ComponentView]] = {}
        if groups:
            for sid, _name in groups:
                by_sid[sid] = []
            for row in rows:
                sid = row.spec.structure_id or (groups[0][0] if groups else "")
                by_sid.setdefault(sid, []).append(row)
            ordered = [(sid, name) for sid, name in groups if by_sid.get(sid)]
        else:
            by_sid[""] = list(rows)
            ordered = [("", filename or "Structure")]
        for sid, name in ordered:
            file_item = QTreeWidgetItem([name, ""])
            file_item.setData(0, _STRUCT_ROLE, sid)
            file_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            self.tree.addTopLevelItem(file_item)
            slot_rows = by_sid.get(sid) or []
            chain_items: dict[str, QTreeWidgetItem] = {}
            for row in slot_rows:
                chain = (row.spec.chain or "").strip() or "?"
                parent = chain_items.get(chain)
                if parent is None:
                    parent = QTreeWidgetItem([f"Chain {chain}", ""])
                    parent.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                    parent.setData(0, _STRUCT_ROLE, sid)
                    file_item.addChild(parent)
                    chain_items[chain] = parent
                count = (
                    f"{row.spec.n_residues} res"
                    if row.spec.kind in {"polymer", "water"}
                    else f"{row.spec.n_atoms} at"
                )
                item = QTreeWidgetItem([row.spec.label, count])
                item.setData(0, _ID_ROLE, row.spec.component_id)
                item.setData(0, _STRUCT_ROLE, sid)
                item.setData(0, _KIND_ROLE, row.spec.kind)
                item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsUserCheckable)
                item.setCheckState(0, Qt.Checked if row.visible else Qt.Unchecked)
                item.setSelected(row.selected)
                parent.addChild(item)
            file_item.setExpanded(True)
        self.tree.expandAll()
        self._syncing = False

    def apply_row_states(self, rows: list[_ComponentView]) -> None:
        """Update checks and selection without rebuilding the tree."""
        by_id = {r.spec.component_id: r for r in rows}
        self._syncing = True
        try:
            for i in range(self.tree.topLevelItemCount()):
                file_item = self.tree.topLevelItem(i)
                for j in range(file_item.childCount()):
                    group = file_item.child(j)
                    for k in range(group.childCount()):
                        item = group.child(k)
                        cid = item.data(0, _ID_ROLE)
                        row = by_id.get(cid)
                        if row is None:
                            continue
                        item.setCheckState(0, Qt.Checked if row.visible else Qt.Unchecked)
                        item.setSelected(row.selected)
        finally:
            self._syncing = False

    def _on_item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if self._syncing or column != 0:
            return
        cid = item.data(0, _ID_ROLE)
        visible = item.checkState(0) != Qt.Unchecked
        if cid:
            self.visibility_changed.emit(cid, visible)
            return
        sid = item.data(0, _STRUCT_ROLE)
        if not sid:
            return
        ids: list[str] = []

        def _collect(node: QTreeWidgetItem) -> None:
            child_id = node.data(0, _ID_ROLE)
            if child_id:
                ids.append(child_id)
            for i in range(node.childCount()):
                _collect(node.child(i))

        _collect(item)
        for child_id in ids:
            self.visibility_changed.emit(child_id, visible)

    def _on_selection_changed(self) -> None:
        if self._syncing:
            return
        self.selection_changed.emit(self.selected_component_ids())
