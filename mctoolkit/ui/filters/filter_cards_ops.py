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

"""Add, remove, reorder, and toggle filter cards on the side panel."""

from __future__ import annotations
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QDialog, QMessageBox
from .cards import (
    CategoryFilterCard,
    FilterCard,
    SubstructureFilterCard,
    TextFilterCard,
    next_default_filter_title,
)


class FilterCards:
    """Filter-panel card host (numeric, text, category, substructure)."""

    def add_filter_card(self, initial_property: str | None = None):
        if isinstance(initial_property, bool):
            initial_property = None
        if not self._app.headers:
            return
        props = list(self._app.global_bounds.keys())
        if not props:
            props = ["SMILES"]
        init = initial_property if initial_property and initial_property in props else None
        self._app.f_panel.setVisible(True)
        card = FilterCard(props, self._app, initial_property=init)
        card.set_filter_title(next_default_filter_title(self._app.filters, FilterCard))
        card.changed.connect(self.apply_filters)
        card.removed.connect(lambda c: self.remove_filter(c))
        self._app.f_container.addWidget(card)
        self._app.filters.append(card)
        self.apply_filters()
        self._sync_filter_panel_scroll_content()

    def add_text_filter_card(self, initial_column: str | None = None):
        if isinstance(initial_column, bool):
            initial_column = None
        if not self._app.headers:
            return
        cols = self._filterable_data_column_names()
        if not cols:
            QMessageBox.warning(self._app, "Add Filter", "No text columns are available.")
            return
        self._app.f_panel.setVisible(True)
        card = TextFilterCard(cols, self._app)
        card.set_filter_title(next_default_filter_title(self._app.filters, TextFilterCard))
        card.changed.connect(self.apply_filters)
        card.removed.connect(lambda c: self.remove_filter(c))
        self._app.f_container.addWidget(card)
        self._app.filters.append(card)
        if initial_column and card.cb.findText(initial_column) >= 0:
            card.set_column(initial_column)
        self.apply_filters()
        self._sync_filter_panel_scroll_content()

    def add_category_filter_card(self, initial_column: str | None = None):
        if isinstance(initial_column, bool):
            initial_column = None
        if not self._app.headers:
            return
        cols = self._filterable_data_column_names()
        if not cols:
            QMessageBox.warning(self._app, "Add Filter", "No text columns are available.")
            return
        self._app.f_panel.setVisible(True)
        card = CategoryFilterCard(cols, self._app)
        card.set_filter_title(next_default_filter_title(self._app.filters, CategoryFilterCard))
        card.changed.connect(self.apply_filters)
        card.removed.connect(lambda c: self.remove_filter(c))
        self._app.f_container.addWidget(card)
        self._app.filters.append(card)
        if initial_column and card.cb.findText(initial_column) >= 0:
            card.set_column(initial_column)
        self.apply_filters()
        self._sync_filter_panel_scroll_content()

    def open_add_filter_dialog(self) -> None:
        """Show a dialog to choose which filter type to add."""
        from ..dialogs.add_filter import AddFilterDialog

        if not self._app.headers:
            return
        dlg = AddFilterDialog(self._app)
        if dlg.exec() != QDialog.Accepted:
            return
        kind = dlg.selected_kind()
        if kind == "substructure":
            self.add_substructure_filter_card()
        elif kind == "slider":
            self.add_filter_card()
        elif kind == "text":
            self.add_text_filter_card()
        elif kind == "category":
            self.add_category_filter_card()

    def add_substructure_filter_card(self, *_args, **_kwargs):
        if not self._app.headers:
            return
        self._app.f_panel.setVisible(True)
        sources = ["Structure"]
        get_srcs = getattr(self._app, "chemistry_tool_structure_sources", None)
        if callable(get_srcs):
            sources = get_srcs() or sources
        card = SubstructureFilterCard(structure_sources=sources)
        card.set_filter_title(next_default_filter_title(self._app.filters, SubstructureFilterCard))
        card.changed.connect(self.apply_filters)
        card.removed.connect(lambda c: self.remove_filter(c))
        self._app.f_container.addWidget(card)
        self._app.filters.append(card)
        self.apply_filters()
        self._sync_filter_panel_scroll_content()

    def remove_filter(self, card):
        if card in self._app.filters:
            self._app.filters.remove(card)
            card.deleteLater()
            self.apply_filters()
            self._sync_filter_panel_scroll_content()

    def reorder_filter_card(self, card, target_index: int) -> None:
        """Move ``card`` so it sits at ``target_index`` among the other filter cards."""
        if card not in self._app.filters:
            return
        others = [f for f in self._app.filters if f is not card]
        n = len(others)
        target_index = max(0, min(int(target_index), n))
        new_order = list(others)
        new_order.insert(target_index, card)
        if new_order == self._app.filters:
            return
        self._app.filters = new_order
        self._app.f_container.removeWidget(card)
        self._app.f_container.insertWidget(target_index, card)
        self._sync_filter_panel_scroll_content()

    def delete_all_filters_from_panel(self) -> None:
        """Remove every filter card from the panel (same as deleting each card)."""
        for card in list(self._app.filters):
            self.remove_filter(card)

    def _sync_filter_panel_scroll_content(self) -> None:
        """Refresh scroll-area geometry after cards are added or the panel is shown."""
        scroll = getattr(self._app, "_filter_scroll", None)
        if scroll is None:
            return
        clamp = getattr(scroll, "_clamp_host_width", None)
        if callable(clamp):
            clamp()
        host = getattr(self._app, "_filter_cards_host", None)
        if host is not None:
            host.updateGeometry()
        scroll.updateGeometry()

    def toggle_filter_panel(self) -> None:
        """Show or hide the filter panel and resync card width when opening."""
        self._app.f_panel.setVisible(not self._app.f_panel.isVisible())
        if self._app.f_panel.isVisible():
            QTimer.singleShot(0, self._sync_filter_panel_scroll_content)

    def enable_all_filters_keep_panel(self) -> None:
        """Turn on every filter card but leave the filter panel open."""
        for f in self._app.filters:
            f.restore_filter_flags(enabled=True, inverted=f.filter_inverted())
        self.apply_filters()

    def disable_all_filters_keep_panel(self) -> None:
        """Turn off every filter card but leave the filter panel open."""
        for f in self._app.filters:
            f.restore_filter_flags(enabled=False, inverted=f.filter_inverted())
        self.apply_filters()

    def close_filter_panel_and_disable_filters(self) -> None:
        """Hide the filter panel and turn off every filter card (cards remain; re-enable with On)."""
        self.disable_all_filters_keep_panel()
        self._app.f_panel.setVisible(False)

    def close_filter_panel_keep_filters(self) -> None:
        """Hide the filter panel only; active filters keep affecting the table."""
        self._app.f_panel.setVisible(False)
