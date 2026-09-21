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

"""Predict ADME dialog: properties start unchecked; only checked columns are requested."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6.QtWidgets")

from mctoolkit.predictions.adme_prediction import (
    ADME_OUTPUT_COLUMNS,
    RECOMMENDED_ADME_COLUMNS,
)
from mctoolkit.ui.dialogs.adme import AdmePredictorDialog


def test_adme_dialog_starts_with_no_properties_checked(qapp):  # noqa: ARG001
    dlg = AdmePredictorDialog()
    assert dlg._selected_output_columns() == []
    assert set(dlg._endpoint_cbs) == set(ADME_OUTPUT_COLUMNS)
    assert all(not cb.isChecked() for cb in dlg._endpoint_cbs.values())


def test_adme_dialog_recommended_select_all_clear(qapp):  # noqa: ARG001
    dlg = AdmePredictorDialog()
    dlg._on_recommended()
    assert set(dlg._selected_output_columns()) == set(RECOMMENDED_ADME_COLUMNS)
    dlg._set_all_checked()
    assert set(dlg._selected_output_columns()) == set(ADME_OUTPUT_COLUMNS)
    dlg._clear_checked()
    assert dlg._selected_output_columns() == []
