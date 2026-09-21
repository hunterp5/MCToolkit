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

"""Storage backends for large-table workloads."""

from .ensemble_store import (
    EnsembleStore,
    ensemble_db_path,
    ensemble_mol_for,
    ensure_confs_sidecar,
    reset_confs_sidecar,
)
from .mol_store import MolStore, ensure_mol_store, load_mols_from_parse_result, reset_mol_store
from .sqlite_table_store import SqliteTableStore

__all__ = [
    "EnsembleStore",
    "MolStore",
    "SqliteTableStore",
    "ensemble_db_path",
    "ensemble_mol_for",
    "ensure_confs_sidecar",
    "ensure_mol_store",
    "load_mols_from_parse_result",
    "reset_confs_sidecar",
    "reset_mol_store",
]
