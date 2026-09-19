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
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with MolManager.  If not, see <https://www.gnu.org/licenses/>.

"""Unit tests for SureChEMBL client helpers (no network)."""

from __future__ import annotations

import pytest

from molmanager.sources.surechembl_api import _similarity_options_string


def test_similarity_options_string() -> None:
    assert _similarity_options_string(0.7) == "0.7"
    assert _similarity_options_string(1.0) == "1"
    assert _similarity_options_string(0.5) == "0.5"


def test_similarity_options_out_of_range() -> None:
    with pytest.raises(ValueError):
        _similarity_options_string(-0.1)
    with pytest.raises(ValueError):
        _similarity_options_string(1.1)
