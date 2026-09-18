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

"""Compatibility re-export; prefer ``molmanager.ui.dialogs.gnina_dock``."""

from __future__ import annotations

from .dialogs.gnina_dock import (
    GninaDockDialog,
    SminaDockDialog,
    _ligand_cli_args,
    _write_smina_config,
    ensemble_column_headers,
    flex_out_path,
    ligand_mol_from_ensemble,
    normalize_flexres,
)

__all__ = [
    "GninaDockDialog",
    "SminaDockDialog",
    "_ligand_cli_args",
    "_write_smina_config",
    "ensemble_column_headers",
    "flex_out_path",
    "ligand_mol_from_ensemble",
    "normalize_flexres",
]
