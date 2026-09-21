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


"""Qt-to-Mol* file/session bridge (load, overlay shapes, molj, trajectories, maps)."""

from __future__ import annotations

from typing import Protocol

MOLSTAR_TRAJECTORY_FORMATS = frozenset(
    {"pdb", "mmcif", "pdbqt", "gro", "mol2", "sdf", "xyz", "mol", "cif"}
)
MOLSTAR_COORDINATE_FORMATS = frozenset({"dcd", "xtc", "trr", "nctraj", "nc"})
MOLSTAR_VOLUME_FORMATS = frozenset({"ccp4", "mrc", "map", "dsn6", "brix", "dx", "dxbin", "cube", "cub"})


def molstar_structure_format(fmt: str) -> str:
    """Map a viewer/slot format string to a Mol* trajectory format id."""
    key = (fmt or "pdb").strip().lower()
    if key in {"cif", "mmcif", "mcif"}:
        return "mmcif"
    if key in {"ent", "pqr"}:
        return "pdb"
    if key in {"mol", "sd"}:
        return "sdf"
    if key in MOLSTAR_TRAJECTORY_FORMATS:
        return key
    return "pdb"


def molstar_coordinate_format(fmt: str) -> str:
    key = (fmt or "dcd").strip().lower().lstrip(".")
    if key == "nc":
        return "nctraj"
    if key in MOLSTAR_COORDINATE_FORMATS:
        return key
    return "dcd"


def molstar_volume_format(fmt: str) -> str:
    key = (fmt or "ccp4").strip().lower().lstrip(".")
    if key in {"cub"}:
        return "cube"
    if key in MOLSTAR_VOLUME_FORMATS:
        return key
    return "ccp4"


class ProteinCanvas(Protocol):
    """Host API the Protein Viewer dialog uses to talk to Mol*."""

    def load_structures(self, payload: dict) -> None: ...

    def add_structures(self, payload: dict) -> None: ...

    def clear_structures(self) -> None: ...

    def set_docking_box(self, spec: dict | None) -> None: ...

    def set_pharmacophore(self, spec: dict | None) -> None: ...

    def set_dock_pose(self, pose: dict | None) -> None: ...

    def load_trajectory(self, spec: dict) -> None: ...

    def load_volume(self, spec: dict) -> None: ...

    def load_molj(self, state) -> None: ...

    def fetch_molj(self, timeout_ms: int = 400): ...

    def reset_camera(self) -> None: ...
