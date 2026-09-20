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

"""SQL-load row mapping helpers with no Qt."""

from __future__ import annotations

from typing import Any

from ..chem.molecule_conversion import mol_blob_from_smiles

__all__ = ["cells_from_sql_mapping", "mol_blob_from_smiles"]


def cells_from_sql_mapping(cols: list[str], mapping: Any) -> dict[str, str]:
    """Stringify one SQLAlchemy row mapping into table cells."""
    row_cells: dict[str, str] = {}
    for c in cols:
        v = mapping.get(c)
        row_cells[c] = "" if v is None else str(v)
    return row_cells
