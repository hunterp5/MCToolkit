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

"""Tests for table structure rendering."""

from __future__ import annotations

from mctoolkit.table.structure_depiction_layout import (
    STRUCTURE_DEPICT_BOND_LINE_WIDTH,
    STRUCTURE_DEPICT_HEIGHT,
    STRUCTURE_DEPICT_WIDTH,
)
from mctoolkit.chem.structure_2d_depiction import (
    ReactionDrawSpec,
    render_depict_payload_png,
    render_molecule_png,
    render_reaction_png,
    structure_cairo_dimensions,
)


def test_structure_cairo_dimensions_match_target() -> None:
    cw, ch = structure_cairo_dimensions(STRUCTURE_DEPICT_WIDTH, STRUCTURE_DEPICT_HEIGHT)
    assert cw == STRUCTURE_DEPICT_WIDTH
    assert ch == STRUCTURE_DEPICT_HEIGHT


def test_structure_cairo_dimensions_zoomed() -> None:
    cw, ch = structure_cairo_dimensions(STRUCTURE_DEPICT_WIDTH * 2, STRUCTURE_DEPICT_HEIGHT * 2)
    assert cw == STRUCTURE_DEPICT_WIDTH * 2
    assert ch == STRUCTURE_DEPICT_HEIGHT * 2


def test_render_molecule_png_returns_bytes() -> None:
    from rdkit import Chem

    mol = Chem.MolFromSmiles("c1ccccc1")
    png = render_molecule_png(mol, STRUCTURE_DEPICT_WIDTH, STRUCTURE_DEPICT_HEIGHT)
    assert isinstance(png, (bytes, bytearray))
    assert len(png) > 100


def test_render_molecule_png_native_resolution() -> None:
    """Table renders are 1× (no supersample) for Render2D throughput."""
    from rdkit import Chem

    mol = Chem.MolFromSmiles("c1ccccc1")
    png = render_molecule_png(mol, STRUCTURE_DEPICT_WIDTH, STRUCTURE_DEPICT_HEIGHT)
    # PNG IHDR width/height are big-endian at bytes 16:24.
    assert int.from_bytes(png[16:20], "big") == STRUCTURE_DEPICT_WIDTH
    assert int.from_bytes(png[20:24], "big") == STRUCTURE_DEPICT_HEIGHT


def test_render_molecule_png_highlight_atoms_still_png() -> None:
    from rdkit import Chem

    mol = Chem.MolFromSmiles("c1ccccc1")
    plain = render_molecule_png(mol, STRUCTURE_DEPICT_WIDTH, STRUCTURE_DEPICT_HEIGHT)
    highlighted = render_molecule_png(
        mol,
        STRUCTURE_DEPICT_WIDTH,
        STRUCTURE_DEPICT_HEIGHT,
        highlight_atoms=[0, 1],
    )
    assert isinstance(highlighted, (bytes, bytearray))
    assert len(highlighted) > 100
    assert highlighted != plain


def test_table_bond_line_width_constant() -> None:
    assert STRUCTURE_DEPICT_BOND_LINE_WIDTH < 2.0


def test_configure_mol_drawer_uses_structure_padding() -> None:
    from rdkit.Chem.Draw import rdMolDraw2D

    from mctoolkit.table.structure_depiction_layout import STRUCTURE_DEPICT_PADDING
    from mctoolkit.chem.structure_2d_depiction import configure_mol_drawer

    assert STRUCTURE_DEPICT_PADDING == 0.05
    drawer = rdMolDraw2D.MolDraw2DCairo(STRUCTURE_DEPICT_WIDTH, STRUCTURE_DEPICT_HEIGHT)
    configure_mol_drawer(drawer, STRUCTURE_DEPICT_WIDTH)
    assert drawer.drawOptions().padding == 0.05


def test_structure_column_minimum_width() -> None:
    from mctoolkit.table.structure_depiction_layout import (
        DEFAULT_STRUCTURE_DEPICT_HEIGHT,
        DEFAULT_STRUCTURE_DEPICT_WIDTH,
        STRUCTURE_COLUMN_HORIZONTAL_PADDING,
        set_structure_depict_size,
        structure_column_minimum_width,
    )

    set_structure_depict_size(
        DEFAULT_STRUCTURE_DEPICT_WIDTH,
        DEFAULT_STRUCTURE_DEPICT_HEIGHT,
        persist=False,
    )
    assert (
        structure_column_minimum_width()
        == DEFAULT_STRUCTURE_DEPICT_WIDTH + STRUCTURE_COLUMN_HORIZONTAL_PADDING
    )
    assert (
        structure_column_minimum_width(zoomed=True)
        == DEFAULT_STRUCTURE_DEPICT_WIDTH * 2 + STRUCTURE_COLUMN_HORIZONTAL_PADDING
    )


def test_compound_table_view_clamps_structure_column_width(qapp) -> None:  # noqa: ARG001
    from mctoolkit.ui.compound_table_model import CompoundTableModel, CompoundTableView

    model = CompoundTableModel(["ID", "Structure", "SMILES"])
    view = CompoundTableView()
    view.set_compound_model(model)
    col = CompoundTableModel.STRUCTURE_COL
    min_w = view.structure_column_minimum_width()
    view.setColumnWidth(col, min_w - 40)
    assert view.columnWidth(col) == min_w


def test_render_reaction_png_is_wider_than_molecule() -> None:
    from rdkit import Chem

    from mctoolkit.table.structure_depiction_layout import (
        REACTION_DEPICT_WIDTH_MULTIPLIER,
        reaction_depict_size,
    )

    mol_png = render_molecule_png(
        Chem.MolFromSmiles("CCO"),
        STRUCTURE_DEPICT_WIDTH,
        STRUCTURE_DEPICT_HEIGHT,
    )
    rxn_w, rxn_h = reaction_depict_size()
    assert rxn_w == STRUCTURE_DEPICT_WIDTH * REACTION_DEPICT_WIDTH_MULTIPLIER
    assert rxn_h == STRUCTURE_DEPICT_HEIGHT
    png = render_reaction_png(
        "[C:1](=[O:2])-[OH].[N]>>[C:1](=[O:2])-[N]",
        rxn_w,
        rxn_h,
    )
    assert png.startswith(b"\x89PNG")
    assert int.from_bytes(png[16:20], "big") == rxn_w
    assert int.from_bytes(png[20:24], "big") == rxn_h
    assert int.from_bytes(mol_png[16:20], "big") == STRUCTURE_DEPICT_WIDTH
    assert int.from_bytes(mol_png[20:24], "big") == STRUCTURE_DEPICT_HEIGHT


def test_render_depict_payload_png_dispatches_reaction() -> None:
    spec = ReactionDrawSpec("[C:1]>>[C:1]")
    png = render_depict_payload_png(spec, 400, 120)
    assert png.startswith(b"\x89PNG")
    assert int.from_bytes(png[16:20], "big") == 400


def test_render_worker_emits_reaction_scheme_png(qapp) -> None:  # noqa: ARG001
    from mctoolkit.table.structure_depiction_layout import reaction_depict_size
    from mctoolkit.workers.load_render import RenderWorker
    from mctoolkit.workers.signals import WorkerSignals

    captured: list[tuple] = []
    signals = WorkerSignals()
    signals.rendered.connect(lambda *args: captured.append(args))
    width, height = reaction_depict_size()
    worker = RenderWorker(3, ReactionDrawSpec("[C:1]>>[C:1]"), signals, width=width, height=height)
    worker.run()
    assert len(captured) == 1
    oid, props, png, ok, rw, rh, _sid = captured[0]
    assert oid == 3
    assert ok is True
    assert props == {}
    assert png.startswith(b"\x89PNG")
    assert (rw, rh) == (width, height)


def _prepared(smiles: str):
    from rdkit import Chem
    from rdkit.Chem.Draw import rdMolDraw2D

    mol = Chem.MolFromSmiles(smiles)
    assert mol is not None
    return rdMolDraw2D.PrepareMolForDrawing(mol)


def test_acyclic_alkene_double_bonds_marked_for_parallel_redraw() -> None:
    from mctoolkit.chem.structure_2d_depiction import acyclic_offset_double_bond_indices

    linalyl = _prepared("C=CC(C)(CCC=C(C)C)OC(C)=O")
    idxs = acyclic_offset_double_bond_indices(linalyl)
    assert len(idxs) == 2
    for bid in idxs:
        bond = linalyl.GetBondWithIdx(bid)
        assert bond.GetBondType().name == "DOUBLE"
        assert bond.GetBeginAtom().GetAtomicNum() == 6
        assert bond.GetEndAtom().GetAtomicNum() == 6

    ketotifen = _prepared("CN1CCC(=C2c3ccccc3CC(=O)c3sccc32)CC1")
    keto_idxs = acyclic_offset_double_bond_indices(ketotifen)
    assert len(keto_idxs) == 1
    bond = ketotifen.GetBondWithIdx(keto_idxs[0])
    assert {bond.GetBeginAtom().GetAtomicNum(), bond.GetEndAtom().GetAtomicNum()} == {6}


def test_carbonyl_and_ring_doubles_not_marked_for_parallel_redraw() -> None:
    from mctoolkit.chem.structure_2d_depiction import acyclic_offset_double_bond_indices

    assert acyclic_offset_double_bond_indices(_prepared("CC(=O)C")) == []
    assert acyclic_offset_double_bond_indices(_prepared("c1ccccc1")) == []
    assert acyclic_offset_double_bond_indices(_prepared("CCOC(C)=O")) == []


def test_offset_double_inner_stroke_is_parallel() -> None:
    from mctoolkit.chem.structure_2d_depiction import offset_double_inner_strokes

    mol = _prepared("C=CC(C)(CCC=C(C)C)OC(C)=O")
    strokes = offset_double_inner_strokes(mol, multiple_bond_offset=0.15)
    assert len(strokes) == 2
    for (x1, y1), (x2, y2), (sx, sy), (ex, ey) in strokes:
        mx, my = x2 - x1, y2 - y1
        ix, iy = ex - sx, ey - sy
        mag_m = (mx * mx + my * my) ** 0.5
        mag_i = (ix * ix + iy * iy) ** 0.5
        assert mag_m > 0.5 and mag_i > 0.5
        # Parallel: cross product of unit directions is ~0.
        cross = abs(mx * iy - my * ix) / (mag_m * mag_i)
        assert cross < 1e-9


def test_render_linalyl_acetate_and_ketotifen_png() -> None:
    from rdkit import Chem

    for smi in ("C=CC(C)(CCC=C(C)C)OC(C)=O", "CN1CCC(=C2c3ccccc3CC(=O)c3sccc32)CC1"):
        mol = Chem.MolFromSmiles(smi)
        png = render_molecule_png(mol, STRUCTURE_DEPICT_WIDTH, STRUCTURE_DEPICT_HEIGHT)
        assert png.startswith(b"\x89PNG")
        assert len(png) > 100
