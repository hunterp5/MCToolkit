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

"""Element symbols and wildcard defaults shared by sketch chemistry."""

from __future__ import annotations

WILDCARD_ELEMENT = "*"
DEFAULT_WILDCARD_ELEMENTS = ["C", "N", "O"]

SKETCH_ELEMENT_SYMBOLS: tuple[str, ...] = (
    "H",
    "D",
    "T",
    "C",
    "N",
    "O",
    "F",
    "P",
    "S",
    "Cl",
    "Br",
    "I",
    "B",
    "Si",
    "Se",
    "Li",
    "Na",
    "K",
    "Rb",
    "Cs",
    "Mg",
    "Ca",
    "Sr",
    "Ba",
    "Al",
    "Ti",
    "V",
    "Cr",
    "Mn",
    "Fe",
    "Co",
    "Ni",
    "Cu",
    "Zn",
    "Ga",
    "Ge",
    "As",
    "Mo",
    "Ru",
    "Rh",
    "Pd",
    "Ag",
    "Cd",
    "Sn",
    "Sb",
    "Te",
    "W",
    "Re",
    "Os",
    "Ir",
    "Pt",
    "Au",
    "Hg",
    "Tl",
    "Pb",
    "Bi",
    "Gd",
    "Lu",
    "Eu",
    "Sm",
)

WILDCARD_ELEMENT_CHOICES = SKETCH_ELEMENT_SYMBOLS

ELEMENT_UPPER_MAP: dict[str, str] = {s.upper(): s for s in SKETCH_ELEMENT_SYMBOLS}
