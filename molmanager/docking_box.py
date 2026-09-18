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

"""Smina/Vina search-box geometry from ligand coordinates."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

DEFAULT_BOX_PADDING_A = 4.0


@dataclass(frozen=True)
class DockingBox:
    """Axis-aligned search box (Å) matching Smina ``--center_*`` / ``--size_*``."""

    center_x: float
    center_y: float
    center_z: float
    size_x: float
    size_y: float
    size_z: float
    padding: float = DEFAULT_BOX_PADDING_A

    def to_dict(self) -> dict:
        """JSON payload for the Protein Viewer overlay and session restore."""
        return {
            "active": True,
            "center": {
                "x": float(self.center_x),
                "y": float(self.center_y),
                "z": float(self.center_z),
            },
            "size": {
                "x": float(self.size_x),
                "y": float(self.size_y),
                "z": float(self.size_z),
            },
            "padding": float(self.padding),
            "color": "#3D8BFF",
        }

    def viewer_payload(self) -> dict:
        """Viewer overlay dict including wireframe edges."""
        payload = self.to_dict()
        payload["edges"] = [
            {"start": start, "end": end} for start, end in self.wireframe_edges()
        ]
        return payload

    def wireframe_edges(self) -> tuple[tuple[dict[str, float], dict[str, float]], ...]:
        """Twelve box edges as ``(start, end)`` xyz dicts for 3Dmol lines."""
        hx = float(self.size_x) * 0.5
        hy = float(self.size_y) * 0.5
        hz = float(self.size_z) * 0.5
        cx, cy, cz = float(self.center_x), float(self.center_y), float(self.center_z)
        corners = [
            (cx + sx * hx, cy + sy * hy, cz + sz * hz)
            for sx in (-1.0, 1.0)
            for sy in (-1.0, 1.0)
            for sz in (-1.0, 1.0)
        ]
        edges: list[tuple[dict[str, float], dict[str, float]]] = []
        for i, a in enumerate(corners):
            for b in corners[i + 1 :]:
                diffs = sum(1 for u, v in zip(a, b, strict=True) if abs(u - v) > 1e-9)
                if diffs != 1:
                    continue
                edges.append(
                    (
                        {"x": a[0], "y": a[1], "z": a[2]},
                        {"x": b[0], "y": b[1], "z": b[2]},
                    )
                )
        return tuple(edges)


def box_from_points(
    points: Sequence[tuple[float, float, float]],
    *,
    padding: float = DEFAULT_BOX_PADDING_A,
) -> DockingBox:
    """Smina autobox: ligand AABB expanded by *padding* on each side."""
    if not points:
        raise ValueError("Cannot build a docking box from an empty coordinate list.")
    pad = max(0.0, float(padding))
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    zs = [p[2] for p in points]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    min_z, max_z = min(zs), max(zs)
    return DockingBox(
        center_x=(min_x + max_x) * 0.5,
        center_y=(min_y + max_y) * 0.5,
        center_z=(min_z + max_z) * 0.5,
        size_x=(max_x - min_x) + 2.0 * pad,
        size_y=(max_y - min_y) + 2.0 * pad,
        size_z=(max_z - min_z) + 2.0 * pad,
        padding=pad,
    )


def box_from_xyz(
    xs: Iterable[float],
    ys: Iterable[float],
    zs: Iterable[float],
    *,
    padding: float = DEFAULT_BOX_PADDING_A,
) -> DockingBox:
    """Build a box from parallel x/y/z iterables."""
    return box_from_points(list(zip(xs, ys, zs, strict=True)), padding=padding)


def docking_box_from_dict(payload: dict | None) -> DockingBox | None:
    """Restore a :class:`DockingBox` from a viewer/session dict."""
    if not isinstance(payload, dict) or not payload.get("active"):
        return None
    center = payload.get("center") if isinstance(payload.get("center"), dict) else {}
    size = payload.get("size") if isinstance(payload.get("size"), dict) else {}
    try:
        return DockingBox(
            center_x=float(center["x"]),
            center_y=float(center["y"]),
            center_z=float(center["z"]),
            size_x=float(size["x"]),
            size_y=float(size["y"]),
            size_z=float(size["z"]),
            padding=float(payload.get("padding", DEFAULT_BOX_PADDING_A)),
        )
    except (KeyError, TypeError, ValueError):
        return None


def smina_artifact_paths(output_path: str | Path) -> dict[str, Path]:
    """Sidecar paths next to a prepared structure or Dock File PDBQT.

    When *output_path* is already ``.pdbqt`` (Dock File), that file is the apo
    receptor. Otherwise the receptor is ``{stem}_receptor.pdbqt`` beside a
    prepared mmCIF/PDB.
    """
    rec = Path(output_path)
    stem = rec.stem
    parent = rec.parent
    if rec.suffix.lower() == ".pdbqt":
        receptor = rec.with_suffix(".pdbqt")
    else:
        receptor = parent / f"{stem}_receptor.pdbqt"
    return {
        "receptor_pdbqt": receptor,
        "ligand_sdf": parent / f"{stem}_ligand.sdf",
        "ligand_pdb": parent / f"{stem}_ligand.pdb",
        "box": parent / f"{stem}_box.txt",
    }
