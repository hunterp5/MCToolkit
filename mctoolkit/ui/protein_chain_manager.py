# This file is part of MCToolkit.
# Copyright (C) 2026 Hunter Picard
#
# MCToolkit is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# MCToolkit is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with MCToolkit. If not, see <https://www.gnu.org/licenses/>.


"""Right-hand chain list for the protein viewer."""

from __future__ import annotations

from contextlib import suppress

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
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
    NamedManagerGroup,
    USER_GROUP_KIND,
    _ComponentView,
    _GROUP_ROLE,
    _ID_ROLE,
    _KIND_ROLE,
    _STRUCT_ROLE,
)


class ProteinChainManager(QWidget):
    """Right-hand chain list with stacked dock pages and a plot-pane pager."""

    visibility_changed = Signal(str, bool)
    selection_changed = Signal(list)
    focus_requested = Signal()
    delete_requested = Signal()
    duplicate_requested = Signal()
    add_to_group_requested = Signal(str)
    remove_from_group_requested = Signal(str)
    rename_group_requested = Signal(str)
    delete_group_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setMinimumWidth(240)
        self._syncing = False
        self._paging = False
        self._docked: list[QWidget] = []
        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 0)
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
        with suppress(TypeError):
            widget.destroyed.connect(self._on_docked_destroyed)
        return self.show_widget(widget)

    def undock_widget(self, widget: QWidget | None) -> bool:
        """Remove ``widget`` from the Manager stack without destroying it."""
        from .qt_widget_utils import qobject_is_deleted

        if widget is None or qobject_is_deleted(widget):
            self._prune_docked()
            return False
        if widget not in self._docked:
            return False
        with suppress(TypeError):
            widget.destroyed.disconnect(self._on_docked_destroyed)
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
        with suppress(ValueError):
            self._docked.remove(widget)
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
        named_groups: list[NamedManagerGroup] | None = None,
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
        by_id = {row.spec.component_id: row for row in rows}
        file_names = {sid: name for sid, name in ordered}
        multi_file = len(ordered) > 1
        for group in named_groups or []:
            live_rows = [by_id[cid] for cid in group.component_ids if cid in by_id]
            folder = QTreeWidgetItem([group.name, str(len(live_rows)) if live_rows else ""])
            folder.setData(0, _KIND_ROLE, USER_GROUP_KIND)
            folder.setData(0, _GROUP_ROLE, group.group_id)
            folder.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsUserCheckable)
            self.tree.addTopLevelItem(folder)
            for row in live_rows:
                extra = ""
                if multi_file:
                    extra = file_names.get(row.spec.structure_id, "")
                child = self._make_component_item(
                    row,
                    extra_label=extra,
                    group_id=group.group_id,
                )
                folder.addChild(child)
            self._sync_group_check(folder)
            folder.setExpanded(True)
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
                parent.addChild(self._make_component_item(row))
            file_item.setExpanded(True)
        self.tree.expandAll()
        self._syncing = False

    def _make_component_item(
        self,
        row: _ComponentView,
        *,
        extra_label: str = "",
        group_id: str = "",
    ) -> QTreeWidgetItem:
        label = row.spec.label
        extra = (extra_label or "").strip()
        if extra:
            label = f"{label} · {extra}"
        count = (
            f"{row.spec.n_residues} res"
            if row.spec.kind in {"polymer", "water"}
            else f"{row.spec.n_atoms} at"
        )
        item = QTreeWidgetItem([label, count])
        item.setData(0, _ID_ROLE, row.spec.component_id)
        item.setData(0, _STRUCT_ROLE, row.spec.structure_id)
        item.setData(0, _KIND_ROLE, row.spec.kind)
        if group_id:
            item.setData(0, _GROUP_ROLE, group_id)
        item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsUserCheckable)
        item.setCheckState(0, Qt.Checked if row.visible else Qt.Unchecked)
        item.setSelected(row.selected)
        return item

    def apply_row_states(self, rows: list[_ComponentView]) -> None:
        """Update checks and selection without rebuilding the tree."""
        by_id = {r.spec.component_id: r for r in rows}
        self._syncing = True
        try:

            def _walk(item: QTreeWidgetItem) -> None:
                cid = item.data(0, _ID_ROLE)
                row = by_id.get(cid) if cid else None
                if row is not None:
                    item.setCheckState(0, Qt.Checked if row.visible else Qt.Unchecked)
                    item.setSelected(row.selected)
                for i in range(item.childCount()):
                    _walk(item.child(i))
                if item.data(0, _KIND_ROLE) == USER_GROUP_KIND:
                    self._sync_group_check(item)

            for i in range(self.tree.topLevelItemCount()):
                _walk(self.tree.topLevelItem(i))
        finally:
            self._syncing = False

    def _sync_group_check(self, item: QTreeWidgetItem) -> None:
        n = item.childCount()
        if n == 0:
            item.setCheckState(0, Qt.Unchecked)
            return
        checked = 0
        unchecked = 0
        for i in range(n):
            state = item.child(i).checkState(0)
            if state == Qt.Checked:
                checked += 1
            elif state == Qt.Unchecked:
                unchecked += 1
        if checked == n:
            item.setCheckState(0, Qt.Checked)
        elif unchecked == n:
            item.setCheckState(0, Qt.Unchecked)
        else:
            item.setCheckState(0, Qt.PartiallyChecked)

    def selected_items_are_groups_only(self) -> bool:
        items = self.tree.selectedItems()
        if not items:
            return False
        return all(item.data(0, _KIND_ROLE) == USER_GROUP_KIND for item in items)

    def selected_user_group_ids(self) -> list[str]:
        ids: list[str] = []
        seen: set[str] = set()
        for item in self.tree.selectedItems():
            if item.data(0, _KIND_ROLE) != USER_GROUP_KIND:
                continue
            gid = item.data(0, _GROUP_ROLE)
            if gid and gid not in seen:
                seen.add(gid)
                ids.append(gid)
        return ids

    def _named_group_names(self) -> list[str]:
        names: list[str] = []
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            if item.data(0, _KIND_ROLE) == USER_GROUP_KIND:
                names.append(item.text(0))
        return names

    def _group_membership_for_ids(self, ids: set[str]) -> list[tuple[str, str]]:
        found: list[tuple[str, str]] = []
        if not ids:
            return found
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            if item.data(0, _KIND_ROLE) != USER_GROUP_KIND:
                continue
            gid = item.data(0, _GROUP_ROLE)
            member_ids = {item.child(j).data(0, _ID_ROLE) for j in range(item.childCount())}
            if gid and member_ids & ids:
                found.append((gid, item.text(0)))
        return found

    def _on_item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if self._syncing or column != 0:
            return
        cid = item.data(0, _ID_ROLE)
        visible = item.checkState(0) != Qt.Unchecked
        if cid:
            self.visibility_changed.emit(cid, visible)
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

    def _prompt_new_group(self) -> None:
        name, ok = QInputDialog.getText(self, "Add to Group", "Group name:")
        name = (name or "").strip()
        if ok and name:
            self.add_to_group_requested.emit(name)

    def _emit_delete_selected_groups(self) -> None:
        for gid in self.selected_user_group_ids():
            self.delete_group_requested.emit(gid)

    def _make_context_menu(self, item: QTreeWidgetItem | None = None) -> QMenu:
        menu = QMenu(self)
        if self.selected_items_are_groups_only():
            gids = self.selected_user_group_ids()
            gid = gids[0] if gids else ""
            act_rename = menu.addAction("&Rename Group…")
            act_rename.setToolTip("Change this group's name.")
            act_rename.triggered.connect(lambda: self.rename_group_requested.emit(gid))
            act_rename.setEnabled(len(gids) == 1)
            act_remove = menu.addAction("Remove &Group")
            act_remove.setToolTip("Ungroup these rows without deleting structures.")
            act_remove.triggered.connect(self._emit_delete_selected_groups)
            return menu
        act_delete = menu.addAction("&Delete")
        act_delete.setToolTip("Remove the Manager selection from the viewer.")
        act_delete.triggered.connect(self.delete_requested.emit)
        act_dup = menu.addAction("D&uplicate")
        act_dup.setToolTip("Copy the Manager selection as a new overlay structure.")
        act_dup.triggered.connect(self.duplicate_requested.emit)
        menu.addSeparator()
        add_menu = menu.addMenu("Add to &Group")
        add_menu.setToolTip("Place the selection in a named Manager group.")
        for name in self._named_group_names():
            add_menu.addAction(name, lambda n=name: self.add_to_group_requested.emit(n))
        if self._named_group_names():
            add_menu.addSeparator()
        act_new = add_menu.addAction("&New Group…")
        act_new.setToolTip("Create a named group and add the selection to it.")
        act_new.triggered.connect(self._prompt_new_group)
        clicked_gid = item.data(0, _GROUP_ROLE) if item is not None else ""
        clicked_cid = item.data(0, _ID_ROLE) if item is not None else ""
        membership = self._group_membership_for_ids(set(self.selected_component_ids()))
        if clicked_cid and clicked_gid:
            act_ungroup = menu.addAction("Remove from &Group")
            act_ungroup.setToolTip("Remove this row from the group without deleting it.")
            act_ungroup.triggered.connect(
                lambda: self.remove_from_group_requested.emit(clicked_gid)
            )
        elif membership:
            if len(membership) == 1:
                gid, name = membership[0]
                act_ungroup = menu.addAction(f"Remove from Group ({name})")
                act_ungroup.setToolTip("Remove the selection from this group.")
                act_ungroup.triggered.connect(lambda: self.remove_from_group_requested.emit(gid))
            else:
                remove_menu = menu.addMenu("Remove from Group")
                for gid, name in membership:
                    remove_menu.addAction(
                        name, lambda g=gid: self.remove_from_group_requested.emit(g)
                    )
                remove_menu.addAction(
                    "All Groups", lambda: self.remove_from_group_requested.emit("")
                )
        return menu

    def _on_context_menu(self, pos) -> None:
        item = self.tree.itemAt(pos)
        if item is None:
            return
        if item not in self.tree.selectedItems():
            self.tree.clearSelection()
            item.setSelected(True)
        menu = self._make_context_menu(item)
        menu.exec(self.tree.viewport().mapToGlobal(pos))
