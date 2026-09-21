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

"""Periodic-table element parsing for the sketcher ? tool."""

from __future__ import annotations

from mctoolkit.ui.sketcher.chem import _parse_atom_symbol_input, _parse_periodic_element_symbol


def test_parse_periodic_element_symbol_accepts_toolbar_and_extra() -> None:
    assert _parse_periodic_element_symbol("Au") == "Au"
    assert _parse_periodic_element_symbol("ru") == "Ru"
    assert _parse_periodic_element_symbol("SE") == "Se"
    assert _parse_periodic_element_symbol("C") == "C"
    assert _parse_periodic_element_symbol("*") is None
    assert _parse_periodic_element_symbol("?") is None
    assert _parse_periodic_element_symbol("Xx") is None


def test_parse_atom_symbol_wildcard_star_only() -> None:
    assert _parse_atom_symbol_input("*") == ("*", None)
    assert _parse_atom_symbol_input("?") is None
    assert _parse_atom_symbol_input("Au") == ("Au", None)


def test_sketch_valence_helpers_match_common_elements() -> None:
    from mctoolkit.chem.sketch_atoms import (
        sketch_default_valence,
        sketch_max_valence,
        sketch_valence_list,
    )

    assert sketch_valence_list("H") == [1]
    assert sketch_default_valence("C") == 4
    assert sketch_max_valence("S") >= 6
    assert sketch_default_valence("S") == 2
