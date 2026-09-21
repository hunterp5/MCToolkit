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
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with MCToolkit.  If not, see <https://www.gnu.org/licenses/>.

"""Neutralize dialog configuration."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6.QtWidgets")

from mctoolkit.ui.dialogs.mol_tools import NeutralizeDialog


def test_neutralize_dialog_defaults(qapp):  # noqa: ARG001
    dlg = NeutralizeDialog(["Structure", "SMILES"], 0)
    src, only_sel, no_render = dlg.config()
    assert src == "Structure"
    assert only_sel is False
    assert no_render is False


def test_neutralize_dialog_no_render_2d(qapp):  # noqa: ARG001
    dlg = NeutralizeDialog(["Structure"], 0)
    dlg.no_render_2d_cb.setChecked(True)
    _, _, no_render = dlg.config()
    assert no_render is True
