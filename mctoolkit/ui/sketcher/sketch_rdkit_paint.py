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

"""RDKit MolDraw2D rendering for the interactive sketcher (matches the structure column)."""

from __future__ import annotations

import logging
from typing import Any

from PySide6.QtGui import QImage, QPixmap, QTransform
from rdkit import Chem
from rdkit.Chem.Draw import rdMolDraw2D

from ...platform_support.exception_policy import log_swallowed_exception

logger = logging.getLogger(__name__)


# MolDraw2D Cairo surface is supersampled so bonds stay crisp when the sketch is zoomed.
SKETCH_RDKIT_RENDER_SCALE = 3


def sketch_node_bounds(
    nodes: list[dict[str, Any]], *, pad_px: float
) -> tuple[int, int, int, int] | None:
    """Return ``(min_x, min_y, max_x, max_y)`` in sketch model pixels, or None when empty."""
    if not nodes:
        return None
    xs = [int(n["pos"].x()) for n in nodes]
    ys = [int(n["pos"].y()) for n in nodes]
    pad = max(24.0, float(pad_px))
    return (
        int(min(xs) - pad),
        int(min(ys) - pad),
        int(max(xs) + pad),
        int(max(ys) + pad),
    )


def fit_rdkit_draw_to_sketch_map(
    drawer: rdMolDraw2D.MolDraw2D,
    idmap: dict[int, int],
    nodes: list[dict[str, Any]],
) -> tuple[float, float, float, float] | None:
    """
    Map RDKit drawer coordinates to sketch model pixels.

    Returns ``(sx, ox, sy, oy)`` where ``model = scale * rdkit + offset`` per axis.
    """
    rd_x: list[float] = []
    sk_x: list[float] = []
    rd_y: list[float] = []
    sk_y: list[float] = []
    for node in nodes:
        sk_id = int(node["id"])
        rd_idx = idmap.get(sk_id)
        if rd_idx is None:
            continue
        dc = drawer.GetDrawCoords(int(rd_idx))
        rd_x.append(float(dc.x))
        sk_x.append(float(node["pos"].x()))
        rd_y.append(float(dc.y))
        sk_y.append(float(node["pos"].y()))
    if not rd_x:
        return None

    def _fit_1d(r_vals: list[float], s_vals: list[float]) -> tuple[float, float]:
        if len(r_vals) == 1:
            return 1.0, s_vals[0] - r_vals[0]
        r_mean = sum(r_vals) / len(r_vals)
        s_mean = sum(s_vals) / len(s_vals)
        num = sum((r - r_mean) * (s - s_mean) for r, s in zip(r_vals, s_vals))
        den = sum((r - r_mean) ** 2 for r in r_vals)
        if abs(den) < 1e-9:
            return 1.0, s_mean - r_mean
        scale = num / den
        offset = s_mean - scale * r_mean
        return scale, offset

    sx, ox = _fit_1d(rd_x, sk_x)
    sy, oy = _fit_1d(rd_y, sk_y)
    return sx, ox, sy, oy


def effective_model_per_drawer_scale(
    sx: float,
    sy: float,
    nodes: list[dict[str, Any]],
) -> float:
    """
    Average Cairo→model scale for stroke and label sizing.

    When atoms are collinear on one axis the 1D fit returns scale 1.0 for the flat axis; weight
    by sketch extent so bond width does not jump to the wrong axis.
    """
    xs = [float(n["pos"].x()) for n in nodes]
    ys = [float(n["pos"].y()) for n in nodes]
    span_x = max(xs) - min(xs)
    span_y = max(ys) - min(ys)
    if span_y < 1.0:
        return max(abs(float(sx)), 1e-6)
    if span_x < 1.0:
        return max(abs(float(sy)), 1e-6)
    return max((abs(float(sx)) * span_x + abs(float(sy)) * span_y) / (span_x + span_y), 1e-6)


def _configure_sketch_drawer_style(
    drawer: rdMolDraw2D.MolDraw2D,
    *,
    bond_scale_px: float,
    model_per_drawer_scale: float,
) -> None:
    """Set ACS1996 + IUPAC-aligned bond/label sizes in Cairo pixels."""
    from .iupac_style import iupac_sketch_style

    style = iupac_sketch_style(bond_scale_px)
    sx_eff = max(float(model_per_drawer_scale), 1e-6)
    opts = drawer.drawOptions()
    try:
        rdMolDraw2D.SetACS1996Mode(opts, 1.5)
    except Exception:
        log_swallowed_exception(logger, "SetACS1996Mode unavailable for sketcher draw options")
    opts.padding = 0.02
    opts.bondLineWidth = max(1.0, style.bond_width_px / sx_eff)
    # Keep multiple-bond offset proportional after ACS mode.
    try:
        opts.multipleBondOffset = max(
            0.12, style.double_bond_offset_px / max(style.median_bond_px, 1.0)
        )
    except Exception:
        log_swallowed_exception(logger, "multipleBondOffset unavailable for sketcher draw options")
    # Atom symbols are painted by the sketcher (ACS labels) after this pixmap is placed.
    # Cairo labels in a supersampled bitmap become illegible under the affine downscale —
    # heteroatoms like P/N/S then vanish (e.g. Thiotepa looks like a carbon skeleton).
    try:
        opts.noAtomLabels = True
    except Exception:
        log_swallowed_exception(logger, "noAtomLabels unavailable for sketcher draw options")
    font_px = max(8, int(round(style.label_font_pt / sx_eff)))
    opts.minFontSize = font_px
    opts.maxFontSize = font_px + 2
    try:
        opts.fixedBondLength = max(10.0, style.median_bond_px / sx_eff)
    except Exception:
        log_swallowed_exception(logger, "fixedBondLength unavailable for sketcher draw options")


def _draw_sketch_mol(
    drawer: rdMolDraw2D.MolDraw2D,
    mol: Chem.Mol,
) -> bool:
    try:
        rdMolDraw2D.PrepareAndDrawMolecule(drawer, mol)
        drawer.FinishDrawing()
    except Exception:
        return False
    return True


def render_sketch_mol_to_pixmap(
    mol: Chem.Mol,
    idmap: dict[int, int],
    nodes: list[dict[str, Any]],
    *,
    pad_px: float,
    bond_scale_px: float,
    render_scale: int = SKETCH_RDKIT_RENDER_SCALE,
) -> tuple[QPixmap, QTransform] | None:
    """Render *mol* with MolDraw2D and return a pixmap plus model-space placement transform."""
    bounds = sketch_node_bounds(nodes, pad_px=pad_px)
    if bounds is None:
        return None
    min_x, min_y, max_x, max_y = bounds
    width = max(80, max_x - min_x)
    height = max(80, max_y - min_y)
    scale = max(2, min(4, int(render_scale)))
    rw = int(width * scale)
    rh = int(height * scale)

    probe = rdMolDraw2D.MolDraw2DCairo(rw, rh)
    probe.drawOptions().padding = 0.02
    probe.drawOptions().bondLineWidth = 1.0
    if not _draw_sketch_mol(probe, mol):
        return None
    fit = fit_rdkit_draw_to_sketch_map(probe, idmap, nodes)
    if fit is None:
        return None
    sx, ox, sy, oy = fit
    model_scale = effective_model_per_drawer_scale(sx, sy, nodes)

    drawer = rdMolDraw2D.MolDraw2DCairo(rw, rh)
    _configure_sketch_drawer_style(
        drawer,
        bond_scale_px=bond_scale_px,
        model_per_drawer_scale=model_scale,
    )
    if not _draw_sketch_mol(drawer, mol):
        return None
    fit = fit_rdkit_draw_to_sketch_map(drawer, idmap, nodes)
    if fit is None:
        return None
    sx, ox, sy, oy = fit
    png = drawer.GetDrawingText()
    pm = QPixmap.fromImage(QImage.fromData(png))
    if pm.isNull():
        return None
    transform = QTransform(sx, 0.0, 0.0, sy, ox, oy)
    return pm, transform


def sketch_rdkit_paint_cache_key(
    nodes: list[dict[str, Any]],
    bonds: list[tuple[int, int, int, int]],
) -> tuple[Any, ...]:
    """Hashable key for the sketcher's RDKit paint cache."""
    return (
        tuple(
            (
                int(n["id"]),
                int(n["pos"].x()),
                int(n["pos"].y()),
                str(n.get("element") or ""),
                int(n.get("charge") or 0),
            )
            for n in nodes
        ),
        tuple(tuple(int(x) for x in b) for b in bonds),
    )
