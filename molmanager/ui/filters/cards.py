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

"""Filter panel cards (numeric range, substructure, text, category)."""

from .card_chrome import (
    FilterCardsHost,
    filter_card_drop_index,
    style_filter_card_remove_button,
)
from .category_card import CategoryFilterCard
from .numeric_card import FilterCard
from .substructure_card import SubstructureFilterCard
from .text_card import TextFilterCard

__all__ = [
    "CategoryFilterCard",
    "FilterCard",
    "FilterCardsHost",
    "SubstructureFilterCard",
    "TextFilterCard",
    "filter_card_drop_index",
    "next_default_filter_title",
    "style_filter_card_remove_button",
]


def next_default_filter_title(existing_filters: list, card_cls: type) -> str:
    """Return "Type" or "Type N" for the next card of ``card_cls``."""
    if card_cls is FilterCard:
        base = "Slider"
    elif card_cls is SubstructureFilterCard:
        base = "Substructure"
    elif card_cls is TextFilterCard:
        base = "Text"
    elif card_cls is CategoryFilterCard:
        base = "Category"
    else:
        base = "Filter"
    n = sum(1 for f in existing_filters if isinstance(f, card_cls))
    return base if n == 0 else f"{base} {n + 1}"
