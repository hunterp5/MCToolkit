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

"""Compatibility re-export; prefer ``molmanager.ui.dialogs.data_analysis``."""

from __future__ import annotations

from .dialogs.data_analysis import (
    DataAnalysisDialog,
    _outlier_mask_iqr,
    _outlier_mask_modified_z,
    _outlier_mask_zscore,
    iter_scoped_table_analysis_rows,
    numeric_subset,
    selected_table_column_headers,
    table_to_dataframe,
)

__all__ = [
    "DataAnalysisDialog",
    "_outlier_mask_iqr",
    "_outlier_mask_modified_z",
    "_outlier_mask_zscore",
    "iter_scoped_table_analysis_rows",
    "numeric_subset",
    "selected_table_column_headers",
    "table_to_dataframe",
]
