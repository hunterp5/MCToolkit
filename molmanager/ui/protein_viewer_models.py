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


"""Shared models and render constants for the protein viewer."""

from __future__ import annotations


from dataclasses import dataclass
from pathlib import Path

from PyQt5.QtCore import Qt

from ..structure_components import StructureComponent

COMPONENT_STYLE_CHOICES = (
    ("cartoon", "Cartoon"),
    ("surface", "Surface"),
    ("stick", "Sticks"),
    ("ballstick", "Ball and stick"),
    ("sphere", "Spheres"),
    ("line", "Wireframe"),
)

COMPONENT_COLOR_CHOICES = (
    ("default", "Default"),
    ("gray", "Gray"),
    ("green", "Green"),
    ("cyan", "Cyan"),
    ("magenta", "Magenta"),
    ("yellow", "Yellow"),
    ("orange", "Orange"),
    ("purple", "Purple"),
    ("blue", "Blue"),
)

# cartoon color, 3Dmol carbon colorscheme (hex keeps Jmol heteroatoms)
_RENDER_COLOR_SPEC = {
    "gray": ("#888888", "#888888"),
    "green": ("green", "greenCarbon"),
    "cyan": ("cyan", "cyanCarbon"),
    "magenta": ("magenta", "magentaCarbon"),
    "yellow": ("yellow", "yellowCarbon"),
    "orange": ("orange", "orangeCarbon"),
    "purple": ("purple", "purpleCarbon"),
    "blue": ("blue", "blueCarbon"),
}

STRUCTURE_FILE_FILTER = (
    "Crystallographic files (*.pdb *.ent *.cif *.mmcif *.mcif *.pdbqt *.pqr);;"
    "PDB (*.pdb *.ent);;"
    "mmCIF (*.cif *.mmcif *.mcif);;"
    "PDBQT (*.pdbqt);;"
    "PQR (*.pqr);;"
    "Other 3D (*.gro *.mol2 *.sdf *.xyz);;"
    "All files (*.*)"
)

STRUCTURE_SAVE_FILTER = "mmCIF (*.cif *.mmcif *.mcif);;PDB (*.pdb);;All files (*.*)"

_ID_ROLE = Qt.UserRole
_KIND_ROLE = Qt.UserRole + 1
_STRUCT_ROLE = Qt.UserRole + 2


@dataclass
class _ComponentView:
    spec: StructureComponent
    visible: bool
    selected: bool
    style: str
    color_scheme: str = "default"


@dataclass
class _LoadedSlot:
    structure_id: str
    name: str
    path: Path
    text: str
    fmt: str
    rows: list[_ComponentView]


def _component_state_key(item) -> tuple[str, str, str, str, str]:
    if isinstance(item, dict):
        return (
            str(item.get("kind") or ""),
            str(item.get("chain") or ""),
            str(item.get("resn") or ""),
            str(item.get("resi") or ""),
            str(item.get("icode") or ""),
        )
    return (item.kind, item.chain, item.resn, item.resi, item.icode)
