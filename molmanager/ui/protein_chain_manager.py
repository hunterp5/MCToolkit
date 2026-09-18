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
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .dockable_plot import (
    _FOOTER_TEXT_FONT_PX,
    _GLYPH_BTN_SIZE,
    style_plot_pane_nav_arrow,
    style_plot_pane_title_edit,
)
from .protein_viewer_models import (
    _ComponentView,
    _ID_ROLE,
    _KIND_ROLE,
    _STRUCT_ROLE,
)


class ProteinChainManager(QWidget):
    """Right-hand chain list with stacked dock pages and a plot-pane pager."""

    visibility_changed = pyqtSignal(str, bool)
    selection_changed = pyqtSignal(list)
    focus_requested = pyqtSignal()
    delete_requested = pyqtSignal()
    duplicate_requested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setMinimumWidth(240)
        self._syncing = False
        self._paging = False
        self._docked: list[QWidget] = []
        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(0)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Name", "Count"])
        self.tree.setRootIsDecorated(True)
        self.tree.setUniformRowHeights(True)
        self.tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.tree.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.tree.header().setStretchLastSection(False)
        self.tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.tree.itemChanged.connect(self._on_item_changed)
        self.tree.itemSelectionChanged.connect(self._on_selection_changed)
        self.tree.itemDoubleClicked.connect(lambda *_a: self.focus_requested.emit())
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._on_context_menu)

        self._nav_host = QWidget()
        nav_ly = QHBoxLayout(self._nav_host)
        nav_ly.setContentsMargins(0, 0, 0, 0)
        nav_ly.setSpacing(2)
        self._prev_btn = QPushButton()
        self._next_btn = QPushButton()
        style_plot_pane_nav_arrow(self._prev_btn, "left", "Previous Manager page")
        style_plot_pane_nav_arrow(self._next_btn, "right", "Next Manager page")
        self._prev_btn.clicked.connect(self.show_previous_page)
        self._next_btn.clicked.connect(self.show_next_page)
        self._title_edit = QLineEdit()
        self._title_edit.setReadOnly(True)
        self._title_edit.setFocusPolicy(Qt.NoFocus)
        style_plot_pane_title_edit(self._title_edit)
        self._page_label = QLabel("")
        self._page_label.setAlignment(Qt.AlignCenter)
        self._page_label.setFixedWidth(38)
        self._page_label.setFixedHeight(_GLYPH_BTN_SIZE)
        self._page_label.setStyleSheet(
            f"QLabel {{ font-size: {_FOOTER_TEXT_FONT_PX}px; padding: 0px 1px; }}"
        )
        nav_ly.addWidget(self._prev_btn)
        nav_ly.addWidget(self._title_edit)
        nav_ly.addWidget(self._page_label)
        nav_ly.addWidget(self._next_btn)

        self._header = QWidget()
        self._header.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._header.setFixedHeight(_GLYPH_BTN_SIZE)
        header_ly = QHBoxLayout(self._header)
        header_ly.setContentsMargins(2, 0, 2, 0)
        header_ly.setSpacing(2)
        header_ly.addStretch(1)
        header_ly.addWidget(self._nav_host, 0)
        header_ly.addStretch(1)
        self._header.hide()

        self._stack = QStackedWidget()
        self._stack.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._stack.addWidget(self.tree)
        self._stack.currentChanged.connect(lambda *_a: self._refresh_pager())

        root.addWidget(self._header)
        root.addWidget(self._stack, 1)

    def dock_widget(self, widget: QWidget | None) -> bool:
        """Stack ``widget`` as a full-height Manager page and show it."""
        from .qt_widget_utils import qobject_is_deleted

        if widget is None or qobject_is_deleted(widget) or widget is self.tree:
            return False
        self._prune_docked()
        if widget in self._docked:
            return self.show_widget(widget)
        parent = widget.parentWidget()
        if parent is not None:
            ly = parent.layout()
            if ly is not None:
                ly.removeWidget(widget)
        self._stack.addWidget(widget)
        self._docked.append(widget)
        widget.show()
        try:
            widget.destroyed.connect(self._on_docked_destroyed)
        except TypeError:
            pass
        return self.show_widget(widget)

    def undock_widget(self, widget: QWidget | None) -> bool:
        """Remove ``widget`` from the Manager stack without destroying it."""
        from .qt_widget_utils import qobject_is_deleted

        if widget is None or qobject_is_deleted(widget):
            self._prune_docked()
            return False
        if widget not in self._docked:
            return False
        try:
            widget.destroyed.disconnect(self._on_docked_destroyed)
        except TypeError:
            pass
        self._remove_docked_page(widget)
        widget.setParent(None)
        return True

    def show_widget(self, widget: QWidget | None) -> bool:
        """Show a Manager page (chain list or a docked panel)."""
        from .qt_widget_utils import qobject_is_deleted

        if widget is None or qobject_is_deleted(widget):
            return False
        if widget is not self.tree and widget not in self._docked:
            return False
        self._stack.setCurrentWidget(widget)
        widget.show()
        self._refresh_pager()
        return True

    def show_previous_page(self) -> None:
        n = self._stack.count()
        if n < 2:
            return
        self._stack.setCurrentIndex((self._stack.currentIndex() - 1) % n)
        self._refresh_pager()

    def show_next_page(self) -> None:
        n = self._stack.count()
        if n < 2:
            return
        self._stack.setCurrentIndex((self._stack.currentIndex() + 1) % n)
        self._refresh_pager()

    def page_count(self) -> int:
        return int(self._stack.count())

    def page_index(self) -> int:
        return int(self._stack.currentIndex())

    def is_docked(self, widget: QWidget | None) -> bool:
        self._prune_docked()
        return widget is not None and widget in self._docked

    def docked_widgets(self) -> list[QWidget]:
        self._prune_docked()
        return list(self._docked)

    def _on_docked_destroyed(self, *_args) -> None:
        sender = self.sender()
        if sender in self._docked:
            self._remove_docked_page(sender)

    def _remove_docked_page(self, widget: QWidget) -> None:
        try:
            self._docked.remove(widget)
        except ValueError:
            pass
        idx = self._stack.indexOf(widget)
        if idx >= 0:
            self._stack.removeWidget(widget)
            next_idx = min(max(idx - 1, 0), max(self._stack.count() - 1, 0))
            self._stack.setCurrentIndex(next_idx)
        self._refresh_pager()

    def _prune_docked(self) -> None:
        from .qt_widget_utils import qobject_is_deleted

        live: list[QWidget] = []
        for widget in self._docked:
            if qobject_is_deleted(widget):
                continue
            live.append(widget)
        if live != self._docked:
            self._docked = live
            self._refresh_pager()

    def _title_for_page(self, widget: QWidget | None) -> str:
        if widget is None or widget is self.tree:
            return "Manager"
        from .dockable_plot_title import plot_widget_display_title

        text = plot_widget_display_title(widget)
        return text if text and text != "empty" else "Pose Browser"

    def _refresh_pager(self) -> None:
        if self._paging:
            return
        self._paging = True
        try:
            n = self._stack.count()
            if n < 2:
                self._header.hide()
                if self._stack.currentWidget() is not self.tree:
                    self._stack.setCurrentWidget(self.tree)
                return
            self._header.show()
            idx = max(0, int(self._stack.currentIndex()))
            current = self._stack.currentWidget()
            title = self._title_for_page(current)
            self._title_edit.setText(title)
            self._title_edit.setToolTip(title)
            self._page_label.setText(f"({idx + 1}/{n})")
            self._page_label.setVisible(True)
            tip = f"Page {idx + 1} of {n}"
            self._prev_btn.setToolTip(f"Previous page ({tip})")
            self._next_btn.setToolTip(f"Next page ({tip})")
        finally:
            self._paging = False

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

    def clear_component_selection(self) -> None:
        """Deselect Manager rows without emitting selection_changed."""
        self._syncing = True
        try:
            self.tree.clearSelection()
        finally:
            self._syncing = False

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

    def _make_context_menu(self) -> QMenu:
        menu = QMenu(self)
        act_delete = menu.addAction("&Delete")
        act_delete.setToolTip("Remove the Manager selection from the viewer.")
        act_delete.triggered.connect(self.delete_requested.emit)
        act_dup = menu.addAction("D&uplicate")
        act_dup.setToolTip("Copy the Manager selection as a new overlay structure.")
        act_dup.triggered.connect(self.duplicate_requested.emit)
        return menu

    def _on_context_menu(self, pos) -> None:
        item = self.tree.itemAt(pos)
        if item is None:
            return
        if item not in self.tree.selectedItems():
            self.tree.clearSelection()
            item.setSelected(True)
        menu = self._make_context_menu()
        menu.exec_(self.tree.viewport().mapToGlobal(pos))
