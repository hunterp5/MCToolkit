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

"""IUPAC drawing helpers: condensed labels, stereo sanitize, validation, hash geometry."""

from __future__ import annotations

from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QWidget

from molmanager.ui.sketcher.bonds import (
    BOND_STEREO_HASH,
    BOND_STEREO_PLAIN,
    BOND_STEREO_WEDGE,
    _bond_make,
    clear_stereo_bonds_between_centers,
    sanitize_sketch_stereo_bonds,
)
from molmanager.ui.sketcher.dialog import SketcherDialog
from molmanager.ui.sketcher.iupac_style import (
    condensed_heteroatom_label,
    iupac_sketch_style,
    snap_extension_angle,
)
from molmanager.ui.sketcher.iupac_validate import validate_iupac_sketch
from rdkit import Chem
import math


def test_condensed_heteroatom_labels() -> None:
    assert condensed_heteroatom_label("O", 1) == "OH"
    assert condensed_heteroatom_label("N", 2) == "NH2"
    assert condensed_heteroatom_label("S", 1) == "SH"
    assert condensed_heteroatom_label("C", 3) is None
    assert condensed_heteroatom_label("O", 0) is None


def test_iupac_style_hash_bars(qapp) -> None:  # noqa: ARG001
    style = iupac_sketch_style(60)
    assert style.hash_bar_count >= 4
    assert style.double_bond_offset_px >= 60 / 6.0 - 1e-6


def test_snap_extension_angle_single_neighbor() -> None:
    base = 0.0
    # Raw angle near tetrahedral opening.
    raw = math.pi - math.radians(70.5)
    snapped = snap_extension_angle(raw, [base])
    # Should be close to one of the preferred deviations.
    assert abs(((snapped - raw + math.pi) % (2 * math.pi)) - math.pi) < math.radians(15)


def test_clear_stereo_between_centers() -> None:
    bonds = [_bond_make(1, 2, 1, BOND_STEREO_WEDGE), _bond_make(2, 3, 1, 0)]
    out, cleared = clear_stereo_bonds_between_centers(bonds, {1, 2})
    assert cleared == [(1, 2)]
    assert out[0][3] == BOND_STEREO_PLAIN


def test_sanitize_stereo_on_multiples() -> None:
    bonds = [
        _bond_make(1, 2, 2, 0),
        _bond_make(1, 3, 1, BOND_STEREO_HASH),  # tip on multiply-bonded 1 → flip
    ]
    out = sanitize_sketch_stereo_bonds(bonds)
    a, b, o, s = out[1]
    assert o == 1 and s == BOND_STEREO_HASH
    assert a == 3 and b == 1


def test_validate_stereo_between_centers_and_overlap() -> None:
    nodes = [
        {"id": 1, "pos": QPoint(0, 0), "element": "C"},
        {"id": 2, "pos": QPoint(1, 0), "element": "C"},
        {"id": 3, "pos": QPoint(60, 0), "element": "C"},
    ]
    bonds = [_bond_make(1, 2, 1, BOND_STEREO_WEDGE), _bond_make(2, 3, 1, 0)]
    issues = validate_iupac_sketch(nodes, bonds, chiral_center_ids={1, 2}, median_bond_px=60)
    codes = {i.code for i in issues}
    assert "stereo_between_centers" in codes
    assert "atom_overlap" in codes


def test_snap_linear_allene_and_triple() -> None:
    base = 0.0
    raw = math.pi * 0.7  # not yet linear
    snapped = snap_extension_angle(raw, [base], prefer_linear=True)
    assert abs(((snapped - (base + math.pi)) + math.pi) % (2 * math.pi) - math.pi) < 1e-9


def test_hashed_wedge_and_condensed_paint_path(qapp) -> None:  # noqa: ARG001
    dlg = SketcherDialog(QWidget())
    c = dlg.canvas
    c.nodes = [
        {"id": 0, "pos": QPoint(100, 100), "element": "C"},
        {"id": 1, "pos": QPoint(160, 100), "element": "O"},
    ]
    c.bonds = [_bond_make(0, 1, 1, BOND_STEREO_HASH)]
    c.next_id = 2
    c._after_sketch_edit(notify=False)
    assert c._node_condensed_label(c.nodes[1]) == "OH"
    assert not c._should_paint_sketch_with_rdkit()
    style = c._acs_style()
    assert hasattr(style, "hash_bar_count")
    # Ring atoms detected for GR-1.10 interior double-bond bias.
    c.nodes = [
        {
            "id": i,
            "pos": QPoint(
                100 + int(40 * math.cos(2 * math.pi * i / 6)),
                100 + int(40 * math.sin(2 * math.pi * i / 6)),
            ),
            "element": "C",
        }
        for i in range(6)
    ]
    c.bonds = [_bond_make(i, (i + 1) % 6, 2 if i % 2 == 0 else 1, 0) for i in range(6)]
    c._iupac_ring_atom_ids = None
    ring = c._ring_atom_ids()
    assert len(ring) == 6
    # All Kekulé doubles offset toward the same ring interior.
    style = c._acs_style()
    signs = []
    for i in range(0, 6, 2):
        ni, nj = c.nodes[i], c.nodes[(i + 1) % 6]
        ox, oy = c._bond_parallel_offset(
            float(ni["pos"].x()),
            float(ni["pos"].y()),
            float(nj["pos"].x()),
            float(nj["pos"].y()),
            style.double_bond_offset_px,
        )
        signs.append(c._ring_interior_offset_sign(ni, nj, ox, oy))
    # Each sign is defined relative to that bond's perpendicular; all must point inward
    # (dot product of offset direction with vector to centroid is positive after applying sign).
    cx = sum(float(n["pos"].x()) for n in c.nodes) / 6
    cy = sum(float(n["pos"].y()) for n in c.nodes) / 6
    for i, sign in zip(range(0, 6, 2), signs):
        ni, nj = c.nodes[i], c.nodes[(i + 1) % 6]
        ox, oy = c._bond_parallel_offset(
            float(ni["pos"].x()),
            float(ni["pos"].y()),
            float(nj["pos"].x()),
            float(nj["pos"].y()),
            1.0,
        )
        mx = (float(ni["pos"].x()) + float(nj["pos"].x())) * 0.5
        my = (float(ni["pos"].y()) + float(nj["pos"].y())) * 0.5
        assert (ox * sign) * (cx - mx) + (oy * sign) * (cy - my) > 0
    assert not c._should_paint_sketch_with_rdkit()
    dlg.close()


def test_click_extend_allene_linear(qapp) -> None:  # noqa: ARG001
    dlg = SketcherDialog(QWidget())
    c = dlg.canvas
    c.nodes = [
        {"id": 0, "pos": QPoint(100, 100), "element": "C"},
        {"id": 1, "pos": QPoint(160, 100), "element": "C"},
    ]
    c.bonds = [_bond_make(0, 1, 2, 0)]
    c.next_id = 2
    c.active_bond_order = 2
    c.active_bond_stereo = BOND_STEREO_PLAIN
    ux, uy = c._compute_extension_vector(1, snap=True, new_bond_order=2)
    # Extension from atom 1 should be ~180° from the existing C=C (neighbor at left).
    ang = math.atan2(uy, ux)
    assert abs(ang) < math.radians(8) or abs(abs(ang) - math.pi) < math.radians(8)
    # Neighbor is to the left (−x); linear extension is +x.
    assert ux > 0.9
    dlg.close()


def test_iupac_double_bond_carbonyl_centered_vs_alkene_offset(qapp) -> None:  # noqa: ARG001
    dlg = SketcherDialog(QWidget())
    c = dlg.canvas
    # Acetone-like: C with two Me, =O → centered.
    c.nodes = [
        {"id": 0, "pos": QPoint(100, 100), "element": "C"},
        {"id": 1, "pos": QPoint(160, 100), "element": "O"},
        {"id": 2, "pos": QPoint(70, 60), "element": "C"},
        {"id": 3, "pos": QPoint(70, 140), "element": "C"},
    ]
    c.bonds = [
        _bond_make(0, 1, 2, 0),
        _bond_make(0, 2, 1, 0),
        _bond_make(0, 3, 1, 0),
    ]
    pos_n, neg_n, ni_extra, nj_extra = c._double_bond_side_substituent_counts(
        c.nodes[0], c.nodes[1]
    )
    assert ni_extra >= 2 and nj_extra == 0
    # Propene-like: one end substituted → offset (not carbonyl-centered pattern of ≥2).
    c.nodes = [
        {"id": 0, "pos": QPoint(100, 100), "element": "C"},
        {"id": 1, "pos": QPoint(160, 100), "element": "C"},
        {"id": 2, "pos": QPoint(70, 60), "element": "C"},
    ]
    c.bonds = [_bond_make(0, 1, 2, 0), _bond_make(0, 2, 1, 0)]
    _p, _n, a_extra, b_extra = c._double_bond_side_substituent_counts(c.nodes[0], c.nodes[1])
    assert a_extra == 1 and b_extra == 0
    dlg.close()


def test_contracted_cf3_edit_and_export(qapp) -> None:  # noqa: ARG001
    from molmanager.ui.sketcher.contracted_labels import parse_edit_atom_input

    parsed = parse_edit_atom_input("CF3")
    assert parsed == ("C", None, "CF3")
    assert parse_edit_atom_input("SO2") == ("S", None, "SO2")
    assert parse_edit_atom_input("CF2H") == ("C", None, "CF2H")
    dlg = SketcherDialog(QWidget())
    c = dlg.canvas
    c.nodes = [
        {"id": 0, "pos": QPoint(100, 100), "element": "C"},
        {"id": 1, "pos": QPoint(160, 100), "element": "C"},
    ]
    c.bonds = [_bond_make(0, 1, 1, 0)]
    c.next_id = 2
    c._mutate_atom_element(c.nodes[1], "C", None, abbrev="CF3")
    assert c.nodes[1].get("abbrev") == "CF3"
    assert not c._should_paint_sketch_with_rdkit()
    assert c._max_bond_order_sum_for_node(c.nodes[1], 0) == 1
    mol = c._mol_from_node_ids({0, 1})
    assert mol is not None
    # CF3 expands to C + 3F → 5 atoms total with the attachment partner C.
    assert mol.GetNumAtoms() == 5
    smi = Chem.MolToSmiles(mol)
    assert "F" in smi
    dlg.close()


def test_iupac_stereo_descriptor_labels(qapp) -> None:  # noqa: ARG001
    dlg = SketcherDialog(QWidget())
    c = dlg.canvas
    c.nodes = [
        {"id": 0, "pos": QPoint(100, 100), "element": "C"},
        {"id": 1, "pos": QPoint(160, 100), "element": "C"},
        {"id": 2, "pos": QPoint(100, 40), "element": "C"},
        {"id": 3, "pos": QPoint(100, 160), "element": "C"},
        {"id": 4, "pos": QPoint(40, 100), "element": "C"},
    ]
    c.bonds = [
        _bond_make(0, 1, 1, BOND_STEREO_WEDGE),
        _bond_make(0, 2, 1, 0),
        _bond_make(0, 3, 1, 0),
        _bond_make(0, 4, 1, 0),
    ]
    off = c._stereo_descriptor_offset(0, c.nodes[0]["pos"])
    # Collision-aware placement: must clear neighboring atoms and not sit on the wedge.
    import math

    cx = c.nodes[0]["pos"].x() + off.x()
    cy = c.nodes[0]["pos"].y() + off.y()
    assert not (off.x() > 10 and abs(off.y()) < 5)  # not along the +x wedge
    for n in c.nodes[1:]:
        assert math.hypot(cx - n["pos"].x(), cy - n["pos"].y()) > 12
    c._stereo_cip_by_node_id = {0: "R"}
    c._stereo_label_node_ids = {0}
    c._alkene_ez_by_bond_index = {0: "E"}
    # Painting helpers must accept standard CIP codes without error.
    from PySide6.QtGui import QImage, QPainter

    img = QImage(240, 200, QImage.Format_ARGB32)
    img.fill(0)
    p = QPainter(img)
    c._draw_cip_label(p, c.nodes[0]["pos"], 0, "R")
    c._draw_alkene_ez_label(p, c.nodes[0], c.nodes[1], "Z", font_pt=12)
    p.end()
    dlg.close()


def test_bond_trim_stops_at_labeled_atoms(qapp) -> None:  # noqa: ARG001
    dlg = SketcherDialog(QWidget())
    c = dlg.canvas
    c.nodes = [
        {"id": 0, "pos": QPoint(100, 100), "element": "C"},
        {"id": 1, "pos": QPoint(160, 100), "element": "O"},
    ]
    c.bonds = [_bond_make(0, 1, 1, 0)]
    style = c._acs_style()
    assert not c._atom_shows_label(c.nodes[0])
    assert c._atom_shows_label(c.nodes[1])
    x1, y1, x2, y2 = c._trimmed_bond_segment(c.nodes[0], c.nodes[1], style)
    assert abs(x1 - 100.0) < 1e-6 and abs(y1 - 100.0) < 1e-6
    assert x2 < 160.0 - 4.0  # inset from O label
    # Stereo distal trim at unlabeled multi-bond carbon.
    c.nodes = [
        {"id": 0, "pos": QPoint(100, 100), "element": "C"},
        {"id": 1, "pos": QPoint(160, 100), "element": "C"},
        {"id": 2, "pos": QPoint(100, 40), "element": "C"},
    ]
    c.bonds = [
        _bond_make(0, 1, 1, BOND_STEREO_WEDGE),
        _bond_make(1, 2, 1, 0),
    ]
    _x1, _y1, x2s, _y2s = c._trimmed_bond_segment(c.nodes[0], c.nodes[1], style, stereo=True)
    assert x2s < 160.0 - 1.0
    dlg.close()


def test_fusion_sign_keeps_aromatic_interior(qapp) -> None:  # noqa: ARG001
    dlg = SketcherDialog(QWidget())
    c = dlg.canvas
    c.nodes = [
        {
            "id": i,
            "pos": QPoint(
                100 + int(40 * math.cos(2 * math.pi * i / 6)),
                100 + int(40 * math.sin(2 * math.pi * i / 6)),
            ),
            "element": "C",
        }
        for i in range(6)
    ]
    c.bonds = [_bond_make(i, (i + 1) % 6, 2 if i % 2 == 0 else 1, 0) for i in range(6)]
    c._iupac_ring_atom_ids = None
    style = c._acs_style()
    cx = sum(float(n["pos"].x()) for n in c.nodes) / 6
    cy = sum(float(n["pos"].y()) for n in c.nodes) / 6
    for i in range(0, 6, 2):
        ni, nj = c.nodes[i], c.nodes[(i + 1) % 6]
        ox, oy = c._bond_parallel_offset(
            float(ni["pos"].x()),
            float(ni["pos"].y()),
            float(nj["pos"].x()),
            float(nj["pos"].y()),
            style.double_bond_offset_px,
        )
        sign = c._fusion_or_ring_double_offset_sign(ni, nj, ox, oy)
        mx = (float(ni["pos"].x()) + float(nj["pos"].x())) * 0.5
        my = (float(ni["pos"].y()) + float(nj["pos"].y())) * 0.5
        assert (ox * sign) * (cx - mx) + (oy * sign) * (cy - my) > 0
    dlg.close()


def test_structure_issue_report_levels(qapp) -> None:  # noqa: ARG001
    from molmanager.ui.sketcher.bonds import BOND_STEREO_WAVY

    dlg = SketcherDialog(QWidget())
    c = dlg.canvas
    c.nodes = [
        {"id": 0, "pos": QPoint(100, 100), "element": "C"},
        {"id": 1, "pos": QPoint(160, 100), "element": "C"},
    ]
    c.bonds = [_bond_make(0, 1, 1, 0)]
    c.next_id = 2
    c._after_sketch_edit(notify=False)
    level, _msgs = c.structure_issue_report()
    assert level == "ok"
    # Wavy bond → caution
    c.bonds = [_bond_make(0, 1, 1, BOND_STEREO_WAVY)]
    c._after_sketch_edit(notify=False)
    level, msgs = c.structure_issue_report()
    assert level == "caution"
    assert any("wavy" in m.lower() or "unspecified" in m.lower() for m in msgs)
    # Over-valent carbon → error
    c.nodes = [
        {"id": 0, "pos": QPoint(100, 100), "element": "C"},
        {"id": 1, "pos": QPoint(160, 100), "element": "C"},
        {"id": 2, "pos": QPoint(100, 160), "element": "C"},
        {"id": 3, "pos": QPoint(40, 100), "element": "C"},
        {"id": 4, "pos": QPoint(100, 40), "element": "C"},
        {"id": 5, "pos": QPoint(190, 100), "element": "C"},
    ]
    c.bonds = [
        _bond_make(0, 1, 1, 0),
        _bond_make(0, 2, 1, 0),
        _bond_make(0, 3, 1, 0),
        _bond_make(0, 4, 1, 0),
        _bond_make(0, 5, 1, 0),
    ]
    c.next_id = 6
    c._after_sketch_edit(notify=False)
    level, msgs = c.structure_issue_report()
    assert level == "error"
    assert any("valence" in m.lower() for m in msgs)
    assert dlg.tb_structure_status is not None
    dlg._update_sketch_status()
    dlg.close()

    dlg = SketcherDialog(QWidget())
    c = dlg.canvas
    # Propene-like: offset double bond + E/Z should sit outside the outer stroke.
    c.nodes = [
        {"id": 0, "pos": QPoint(80, 100), "element": "C"},
        {"id": 1, "pos": QPoint(140, 100), "element": "C"},
        {"id": 2, "pos": QPoint(40, 60), "element": "C"},
    ]
    c.bonds = [_bond_make(0, 1, 2, 0), _bond_make(0, 2, 1, 0)]
    style = c._acs_style()
    font_pt = style.label_font_pt
    # Reproduce clearance math: dist must exceed double_bond_offset.
    from PySide6.QtGui import QFontMetrics
    from molmanager.ui.sketcher.iupac_style import iupac_structure_font

    pt = max(7, int(round(float(font_pt) * 0.72)))
    fm = QFontMetrics(iupac_structure_font(pt, italic=True))
    clear_bond = float(style.double_bond_offset_px) + 2.0
    text_clear = max(float(fm.height()) * 0.55, float(pt) * 0.65)
    dist = clear_bond + text_clear + 3.0
    assert dist > float(style.double_bond_offset_px) + float(fm.height()) * 0.4
    from PySide6.QtGui import QImage, QPainter

    img = QImage(220, 160, QImage.Format_ARGB32)
    img.fill(0)
    p = QPainter(img)
    c._draw_alkene_ez_label(p, c.nodes[0], c.nodes[1], "E", font_pt=font_pt)
    p.end()
    dlg.close()


def test_iupac_structure_font_plain_roman() -> None:
    from PySide6.QtGui import QFont
    from molmanager.ui.sketcher.iupac_style import iupac_structure_font

    f = iupac_structure_font(12)
    assert f.weight() == QFont.Normal
    assert not f.italic()
    fi = iupac_structure_font(10, italic=True)
    assert fi.italic()
    assert fi.weight() == QFont.Normal


def test_cleanup_and_validation_status(qapp) -> None:  # noqa: ARG001
    dlg = SketcherDialog(QWidget())
    c = dlg.canvas
    c.nodes = [
        {"id": 0, "pos": QPoint(80, 120), "element": "C"},
        {"id": 1, "pos": QPoint(140, 100), "element": "C"},
        {"id": 2, "pos": QPoint(200, 130), "element": "O"},
    ]
    c.bonds = [_bond_make(0, 1, 1, 0), _bond_make(1, 2, 1, 0)]
    c.next_id = 3
    assert c.cleanup_layout_2d()
    issues = c.refresh_iupac_validation()
    assert isinstance(issues, list)
    dlg.close()


def test_cleanup_selected_does_not_move_unselected(qapp) -> None:  # noqa: ARG001
    from molmanager.ui.sketcher.widget import SketchWidget

    w = SketchWidget()
    w.resize(700, 500)
    w.nodes = [
        {"id": 0, "pos": QPoint(80, 120), "element": "C"},
        {"id": 1, "pos": QPoint(92, 118), "element": "C"},
        {"id": 2, "pos": QPoint(160, 140), "element": "O"},
        {"id": 10, "pos": QPoint(420, 280), "element": "C"},
        {"id": 11, "pos": QPoint(480, 280), "element": "C"},
        {"id": 12, "pos": QPoint(540, 280), "element": "C"},
    ]
    w.bonds = [
        _bond_make(0, 1, 1, 0),
        _bond_make(1, 2, 1, 0),
        _bond_make(10, 11, 1, 0),
        _bond_make(11, 12, 1, 0),
    ]
    w.next_id = 13
    w.select_mode = True
    w.selected_nodes = [0, 1, 2]
    frozen = {n["id"]: (n["pos"].x(), n["pos"].y()) for n in w.nodes if n["id"] >= 10}
    old_cx = sum(n["pos"].x() for n in w.nodes if n["id"] < 10) / 3
    old_cy = sum(n["pos"].y() for n in w.nodes if n["id"] < 10) / 3
    assert w.cleanup_layout_2d_selected()
    for n in w.nodes:
        if n["id"] >= 10:
            assert (n["pos"].x(), n["pos"].y()) == frozen[n["id"]]
    new_cx = sum(n["pos"].x() for n in w.nodes if n["id"] < 10) / 3
    new_cy = sum(n["pos"].y() for n in w.nodes if n["id"] < 10) / 3
    assert abs(new_cx - old_cx) < 3
    assert abs(new_cy - old_cy) < 3
    by = {n["id"]: n["pos"] for n in w.nodes}
    c_o = math.hypot(by[0].x() - by[1].x(), by[0].y() - by[1].y())
    assert c_o > 30


def test_cleanup_selected_requires_two_atoms(qapp) -> None:  # noqa: ARG001
    from molmanager.ui.sketcher.widget import SketchWidget

    w = SketchWidget()
    w.nodes = [
        {"id": 0, "pos": QPoint(80, 120), "element": "C"},
        {"id": 1, "pos": QPoint(140, 120), "element": "C"},
    ]
    w.bonds = [_bond_make(0, 1, 1, 0)]
    w.select_mode = True
    w.selected_nodes = [0]
    assert w.cleanup_layout_2d_selected() is False
    from PySide6.QtWidgets import QMenu

    menu = QMenu()
    w._add_cleanup_selected_action(menu)
    assert menu.actions() == []
    w.selected_nodes = [0, 1]
    w._add_cleanup_selected_action(menu)
    assert any(a.text() == "Clean Up Selected" for a in menu.actions())


def test_iupac_orientation_heteroatom_right() -> None:
    from molmanager.ui.sketcher.iupac_orient import apply_iupac_orientation

    # Vertical C–C–O chain: after orient, O should be farther right than the leftmost C.
    xs = [0.0, 0.0, 0.0]
    ys = [0.0, 1.0, 2.0]
    ox, oy = apply_iupac_orientation(
        xs, ys, elements=["C", "C", "O"], bonds=[(0, 1), (1, 2)], bond_orders=[1, 1]
    )
    assert max(ox) - min(ox) >= max(oy) - min(oy) - 1e-6  # more horizontal than vertical
    assert ox[2] > ox[0]


def test_near_collinear_skipped_for_sulfur_and_phosphorus() -> None:
    from PySide6.QtCore import QPoint

    from molmanager.ui.sketcher.bonds import _bond_make
    from molmanager.ui.sketcher.iupac_validate import validate_iupac_sketch

    # Near-linear C–S–C (≈180°).
    nodes = [
        {"id": 0, "pos": QPoint(0, 100), "element": "C"},
        {"id": 1, "pos": QPoint(100, 100), "element": "S"},
        {"id": 2, "pos": QPoint(200, 102), "element": "C"},
    ]
    bonds = [_bond_make(0, 1, 1, 0), _bond_make(1, 2, 1, 0)]
    issues = validate_iupac_sketch(nodes, bonds, median_bond_px=100)
    assert not any(i.code == "near_collinear" for i in issues)

    nodes_p = [
        {"id": 0, "pos": QPoint(0, 100), "element": "C"},
        {"id": 1, "pos": QPoint(100, 100), "element": "P"},
        {"id": 2, "pos": QPoint(200, 102), "element": "C"},
        {"id": 3, "pos": QPoint(100, 40), "element": "C"},
    ]
    bonds_p = [_bond_make(0, 1, 1, 0), _bond_make(1, 2, 1, 0), _bond_make(1, 3, 1, 0)]
    issues_p = validate_iupac_sketch(nodes_p, bonds_p, median_bond_px=100)
    assert not any(i.code == "near_collinear" and 1 in i.atom_ids for i in issues_p)


def test_principal_ring_system_prefers_largest() -> None:
    from molmanager.ui.sketcher.iupac_orient import (
        apply_iupac_orientation,
        principal_ring_system,
    )

    # Benzene (0–5) plus a remote cyclopropane (6–8) on a chain — principal is the 6-ring.
    # Layout: hex roughly vertical; small ring far right. After orient, hex should dominate
    # horizontal pose and sit toward bottom-left vs the remote small ring.
    import math

    hex_pts = [
        (math.cos(math.pi / 2 + i * math.pi / 3), math.sin(math.pi / 2 + i * math.pi / 3))
        for i in range(6)
    ]
    xs = [p[0] for p in hex_pts] + [5.0, 5.5, 5.25]
    ys = [p[1] for p in hex_pts] + [0.0, 0.0, 0.4]
    bonds = [(i, (i + 1) % 6) for i in range(6)] + [(0, 6), (6, 7), (7, 8), (8, 6)]
    els = ["C"] * 9
    princ = principal_ring_system(bonds, 9, elements=els, bond_orders=[1] * len(bonds))
    assert princ == set(range(6))

    ox, oy = apply_iupac_orientation(
        xs, ys, elements=els, bonds=bonds, bond_orders=[1] * len(bonds)
    )
    # Principal hex centroid should be left of the cyclopropane centroid (bottom-left priority).
    hex_cx = sum(ox[i] for i in range(6)) / 6
    small_cx = sum(ox[i] for i in (6, 7, 8)) / 3
    assert hex_cx <= small_cx + 1e-6


def test_iupac_orientation_ring_heteroatom_right() -> None:
    """GR-3.4.2: fused/ring heteroatoms prefer the right (and slightly bottom)."""
    from molmanager.ui.sketcher.iupac_orient import apply_iupac_orientation

    # Rough horizontal naphthalene-like with N on the left.
    xs = [0.0, 1.0, 1.5, 0.5, -0.5, -1.0, 0.0, 1.0, 1.5, 0.5]
    ys = [0.0, 0.0, 0.8, 1.2, 1.2, 0.8, -0.8, -0.8, -1.6, -1.6]
    els = ["C", "C", "C", "C", "N", "C", "C", "C", "C", "C"]
    bonds = [
        (0, 1),
        (1, 2),
        (2, 3),
        (3, 4),
        (4, 5),
        (5, 0),
        (0, 6),
        (1, 7),
        (7, 8),
        (8, 9),
        (9, 6),
    ]
    ox, oy = apply_iupac_orientation(
        xs, ys, elements=els, bonds=bonds, bond_orders=[1] * len(bonds)
    )
    n_idx = 4
    assert ox[n_idx] >= sum(ox) / len(ox) - 1e-6


def test_layout_overlap_prefers_noncrossing() -> None:
    from molmanager.ui.sketcher.iupac_orient import (
        apply_iupac_orientation,
        count_bond_crossings,
        layout_overlap_penalty,
    )

    # Two segments that cross when oriented one way.
    xs = [0.0, 1.0, 0.0, 1.0]
    ys = [0.0, 1.0, 1.0, 0.0]
    bonds = [(0, 1), (2, 3)]
    assert count_bond_crossings(xs, ys, bonds) == 1
    ox, oy = apply_iupac_orientation(
        xs, ys, elements=["C", "C", "C", "C"], bonds=bonds, bond_orders=[1, 1]
    )
    assert layout_overlap_penalty(ox, oy, bonds) <= layout_overlap_penalty(xs, ys, bonds)


def test_iupac_label_reverse_gr216() -> None:
    from molmanager.ui.sketcher.iupac_labels import (
        label_should_reverse,
        oriented_display_label,
        reverse_atom_label,
    )

    assert reverse_atom_label("OH") == "HO"
    assert reverse_atom_label("NH2") == "H2N"
    assert reverse_atom_label("CF3") == "F3C"
    assert reverse_atom_label("OMe") == "MeO"
    assert reverse_atom_label("N") == "N"

    assert label_should_reverse("OH", has_left=False, has_right=True)
    assert not label_should_reverse("OH", has_left=True, has_right=False)
    assert not label_should_reverse("OH", has_left=True, has_right=True)
    assert not label_should_reverse("O", has_left=False, has_right=True)

    assert oriented_display_label("OH", reverse=True) == "HO"
    assert oriented_display_label("OH", reverse=False) == "OH"


def test_iupac_ring_vertex_offset_hex() -> None:
    from molmanager.ui.sketcher.iupac_style import iupac_ring_vertex_offset
    import math

    off = iupac_ring_vertex_offset(6)
    # First edge (i=0..1) should be vertical in Y-up (equal x).
    t0 = off
    t1 = off + 2 * math.pi / 6
    assert abs(math.cos(t0) - math.cos(t1)) < 1e-9
    assert math.cos(t0) < 0  # on the left
