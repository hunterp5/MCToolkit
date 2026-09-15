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


"""Shared table column naming and numeric-bounds refresh for chemistry tools."""

from __future__ import annotations


from ..widgets import CategoryFilterCard, FilterCard, TextFilterCard


class ColumnWriteMixin:
    def _unique_table_column_names(self, bases: list[str]) -> list[str]:
        """Return column header names; append `` (n)`` when a name already exists in the table."""
        out: list[str] = []
        used = set(self.headers)
        for raw in bases:
            base = (raw or "").strip() or "Column"
            col = base
            if col in used:
                cnt = 1
                while f"{base} ({cnt})" in used:
                    cnt += 1
                col = f"{base} ({cnt})"
            out.append(col)
            used.add(col)
        return out

    def _sync_global_bounds_for_headers(
        self, headers: list[str], *, refresh_filters: bool = False
    ) -> None:
        """Refresh slider min/max for specific columns without scanning the whole table."""
        if not headers:
            return
        self._table_model.refresh_numeric_bounds_for_headers(headers)
        cache = self._table_model._numeric_bounds_cache
        if cache is not None:
            for h in headers:
                if h in cache:
                    self.global_bounds[h] = cache[h]
                else:
                    self.global_bounds.pop(h, None)
        if refresh_filters:
            cols = self._filterable_data_column_names()
            for f in self.filters:
                if isinstance(f, FilterCard):
                    f.update_prop_list(list(self.global_bounds.keys()))
                elif isinstance(f, (TextFilterCard, CategoryFilterCard)):
                    f.update_prop_list(cols)
        self._refresh_active_plot_axis_columns()
        refresh_search = getattr(self, "_refresh_table_search_column_combos", None)
        if callable(refresh_search):
            refresh_search()
