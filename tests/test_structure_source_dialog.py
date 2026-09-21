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

"""Tests for structure-source column ranking (no Qt event loop)."""

from mctoolkit.ui.dialogs.structure_source import rank_structure_column_names


def test_rank_structure_column_names_prefers_smiles():
    names = ["MOL_BLOCK", "InChIKey", "SMILES", "canonical_smiles", "notes"]
    ranked = rank_structure_column_names(names)
    assert ranked[0] == "SMILES"
    assert "canonical_smiles" in ranked[:3]
    assert "InChIKey" in ranked
