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

"""Compatibility re-export.

Table helpers: ``molmanager.ui.table_dataframe``. Statistics dialog:
``molmanager.ui.dialogs.data_analysis``.
"""

from __future__ import annotations

from molmanager.analysis.table_statistics import (
    outlier_mask_iqr as _outlier_mask_iqr,
    outlier_mask_modified_z as _outlier_mask_modified_z,
    outlier_mask_zscore as _outlier_mask_zscore,
)
from .table_dataframe import (
    iter_scoped_table_analysis_rows,
    numeric_subset,
    selected_table_column_headers,
    table_to_dataframe,
)
from .dialogs.data_analysis import DataAnalysisDialog

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
