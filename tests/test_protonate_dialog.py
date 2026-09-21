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
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with mctoolkit.  If not, see <https://www.gnu.org/licenses/>.

"""Protonate dialog configuration."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6.QtWidgets")

from mctoolkit.ui.dialogs.protonate import ProtonateDialog


def test_protonate_dialog_render_targets_output_column(qapp):  # noqa: ARG001
    dlg = ProtonateDialog(["Structure"], 0)
    assert "separate" not in dlg.render_cb.text().lower()
    _src, _ph, col, _only, render = dlg.config()
    assert col == "Protonated"
    assert render is True
    assert "output column" in dlg.render_cb.text().lower()
