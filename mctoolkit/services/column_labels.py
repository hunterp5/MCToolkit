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

"""Shared table/column display labels (no Qt)."""

from __future__ import annotations

COLUMN_TANIMOTO_SIMILARITY = "Tanimoto Similarity"

# Lineage column for derived rows (conformers, protomers, dock poses, …).
COLUMN_PARENT_OID = "Parent OID"

# Legacy header written by older protomer exports; treat as Parent OID when present.
COLUMN_PROTOMER_SOURCE_OID_LEGACY = "Protomer source OID"
