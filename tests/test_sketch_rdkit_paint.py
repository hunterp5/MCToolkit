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
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with mctoolkit.  If not, see <https://www.gnu.org/licenses/>.

from __future__ import annotations

from PySide6.QtCore import QPoint
from rdkit import Chem
from rdkit.Chem.rdchem import Conformer
from rdkit.Chem.Draw import rdMolDraw2D

from mctoolkit.ui.sketcher.acs_style import acs_sketch_style
from mctoolkit.ui.sketcher.sketch_rdkit_paint import (
    effective_model_per_drawer_scale,
    fit_rdkit_draw_to_sketch_map,
    render_sketch_mol_to_pixmap,
    sketch_node_bounds,
)


def _mol_with_sketch_coords(
    nodes: list[tuple[int, int]],
) -> tuple[Chem.Mol, dict[int, int], list[dict]]:
    scale = 40.0
    m = Chem.MolFromSmiles("CCC")
    conf = Conformer(3)
    sketch_nodes = []
    idmap: dict[int, int] = {}
    for i, (x, y) in enumerate(nodes):
        conf.SetAtomPosition(i, (x / scale, -y / scale, 0.0))
        sk_id = 100 + i
        idmap[sk_id] = i
        sketch_nodes.append({"id": sk_id, "pos": QPoint(x, y), "element": "C"})
    m.AddConformer(conf, assignId=True)
    return m, idmap, sketch_nodes


def test_sketch_node_bounds_empty() -> None:
    assert sketch_node_bounds([], pad_px=20.0) is None


def test_fit_rdkit_draw_to_sketch_map_linear(qapp) -> None:  # noqa: ARG001
    m, idmap, nodes = _mol_with_sketch_coords([(100, 100), (160, 200), (220, 100)])
    bounds = sketch_node_bounds(nodes, pad_px=40.0)
    assert bounds is not None
    min_x, min_y, max_x, max_y = bounds
    w = max(80, max_x - min_x)
    h = max(80, max_y - min_y)
    drawer = rdMolDraw2D.MolDraw2DCairo(w, h)
    rdMolDraw2D.PrepareAndDrawMolecule(drawer, m)
    fit = fit_rdkit_draw_to_sketch_map(drawer, idmap, nodes)
    assert fit is not None
    sx, ox, sy, oy = fit
    for node in nodes:
        rd_idx = idmap[node["id"]]
        dc = drawer.GetDrawCoords(rd_idx)
        pred_x = sx * dc.x + ox
        pred_y = sy * dc.y + oy
        assert abs(pred_x - node["pos"].x()) < 1.5
        assert abs(pred_y - node["pos"].y()) < 1.5


def test_render_sketch_mol_to_pixmap(qapp) -> None:  # noqa: ARG001
    m, idmap, nodes = _mol_with_sketch_coords([(120, 140), (180, 140), (240, 140)])
    rendered = render_sketch_mol_to_pixmap(
        m, idmap, nodes, pad_px=40.0, bond_scale_px=60.0, render_scale=3
    )
    assert rendered is not None
    pm, transform = rendered
    assert not pm.isNull()
    assert pm.width() >= 240
    assert not transform.isIdentity()


def _chain_mol_and_nodes(count: int) -> tuple[Chem.Mol, dict[int, int], list[dict]]:
    scale = 40.0
    m = Chem.MolFromSmiles("C" * count)
    conf = Conformer(count)
    sketch_nodes = []
    idmap: dict[int, int] = {}
    for i in range(count):
        x = 100 + i * 60
        y = 200
        conf.SetAtomPosition(i, (x / scale, -y / scale, 0.0))
        sk_id = 100 + i
        idmap[sk_id] = i
        sketch_nodes.append({"id": sk_id, "pos": QPoint(x, y), "element": "C"})
    m.AddConformer(conf, assignId=True)
    return m, idmap, sketch_nodes


def test_effective_model_per_drawer_scale_prefers_span_axis() -> None:
    nodes = [
        {"id": 1, "pos": QPoint(0, 0)},
        {"id": 2, "pos": QPoint(120, 0)},
    ]
    assert effective_model_per_drawer_scale(0.25, 1.0, nodes) == 0.25


def test_render_sketch_bond_width_stable_as_atoms_removed(qapp) -> None:  # noqa: ARG001
    """Deleting peripheral atoms must not shrink bond stroke as the render bbox tightens."""
    target = acs_sketch_style(60.0).bond_width_px
    strokes: list[float] = []
    for count in range(6, 2, -1):
        mol, idmap, nodes = _chain_mol_and_nodes(count)
        bounds = sketch_node_bounds(nodes, pad_px=40.0)
        assert bounds is not None
        width = max(80, bounds[2] - bounds[0])
        height = max(80, bounds[3] - bounds[1])
        rw, rh = width * 3, height * 3
        probe = rdMolDraw2D.MolDraw2DCairo(rw, rh)
        probe.drawOptions().padding = 0.02
        probe.drawOptions().bondLineWidth = 1.0
        rdMolDraw2D.PrepareAndDrawMolecule(probe, mol)
        fit = fit_rdkit_draw_to_sketch_map(probe, idmap, nodes)
        assert fit is not None
        sx, _, sy, _ = fit
        model_scale = effective_model_per_drawer_scale(sx, sy, nodes)
        line_w = max(1.0, target / model_scale)
        drawer = rdMolDraw2D.MolDraw2DCairo(rw, rh)
        drawer.drawOptions().padding = 0.02
        drawer.drawOptions().bondLineWidth = line_w
        rdMolDraw2D.PrepareAndDrawMolecule(drawer, mol)
        fit2 = fit_rdkit_draw_to_sketch_map(drawer, idmap, nodes)
        assert fit2 is not None
        sx2, _, sy2, _ = fit2
        model_scale2 = effective_model_per_drawer_scale(sx2, sy2, nodes)
        strokes.append(line_w * model_scale2)
        rendered = render_sketch_mol_to_pixmap(
            mol, idmap, nodes, pad_px=40.0, bond_scale_px=60.0, render_scale=3
        )
        assert rendered is not None
    for stroke in strokes:
        assert abs(stroke - target) < 0.75


def test_thiotepa_sketcher_paints_heteroatom_labels(qapp) -> None:  # noqa: ARG001
    """RDKit bond pixmap alone drops P/N/S glyphs; ACS overlays must restore them."""
    from PySide6.QtGui import QColor, QImage, QPainter

    from mctoolkit.ui.sketcher.widget import SketchWidget

    mol = Chem.MolFromSmiles("S=P(N1CC1)(N1CC1)N1CC1")
    assert mol is not None
    w = SketchWidget()
    w.resize(700, 500)
    assert w.load_from_rdkit_mol(mol)
    assert w._should_paint_sketch_with_rdkit()
    w.ensure_sketch_fits_viewport()
    w._invalidate_rdkit_sketch_paint_cache()

    img = QImage(700, 500, QImage.Format_ARGB32)
    img.fill(QColor("white"))
    painter = QPainter(img)
    w.render(painter)
    painter.end()

    # Colored ACS element labels (P orange, N blue, S yellow-ish) must appear.
    colored = 0
    for y in range(0, img.height(), 2):
        for x in range(0, img.width(), 2):
            c = img.pixelColor(x, y)
            if c.red() == c.green() == c.blue():
                continue
            colored += 1
    assert colored >= 40, f"expected heteroatom label ink, found {colored} colored pixels"


def test_sketch_rdkit_paint_disables_cairo_atom_labels(qapp) -> None:  # noqa: ARG001
    from mctoolkit.ui.sketcher.sketch_rdkit_paint import _configure_sketch_drawer_style

    drawer = rdMolDraw2D.MolDraw2DCairo(200, 200)
    _configure_sketch_drawer_style(drawer, bond_scale_px=60.0, model_per_drawer_scale=0.4)
    assert drawer.drawOptions().noAtomLabels is True
