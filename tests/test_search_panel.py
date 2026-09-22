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

"""Search panel widgets must stay embedded — orphan Show flashes a top-level window."""

from __future__ import annotations

from PySide6.QtWidgets import QWidget

from mctoolkit.ui.search_panel import SearchCriterionRow


def test_search_criterion_row_children_are_not_top_level_windows(qapp):  # noqa: ARG001
    host = QWidget()
    row = SearchCriterionRow(host, show_add=True)
    try:
        for child in (
            row.remove_btn,
            row.add_btn,
            row.glue_combo,
            row.col_combo,
            row.query_edit,
            row.partial_cb,
            row.case_cb,
            row.substructure_cb,
        ):
            assert child.parentWidget() is not None
            assert not child.isWindow()
    finally:
        host.deleteLater()
