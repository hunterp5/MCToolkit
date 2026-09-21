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

"""RDKit 2D structure rendering for the compound table (no Qt)."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from rdkit import Chem
from rdkit.Chem import AllChem
from rdkit.Chem.Draw import rdMolDraw2D
from rdkit.Geometry import Point2D

from .element_colors import rdkit_default_element_rgb
from ..table.structure_depiction_layout import (
    REACTION_DEPICT_PADDING,
    STRUCTURE_DEPICT_BOND_LINE_WIDTH,
    STRUCTURE_DEPICT_PADDING,
    structure_depict_width,
)

# Fraction of bond length to trim the inner stroke at a substituted end (IUPAC GR-1.10).
_OFFSET_DOUBLE_TRIM = 0.14
_OFFSET_DOUBLE_LABEL_TRIM = 0.06
_Z_3D_EPS = 1e-3


@dataclass(frozen=True)
class ReactionDrawSpec:
    """Render-2D payload for a reaction SMARTS / SMIRKS string."""

    smarts: str


def structure_cairo_dimensions(target_w: int, target_h: int) -> tuple[int, int]:
    """Return (width, height) for MolDraw2DCairo (same as the display target)."""
    return int(target_w), int(target_h)


def configure_mol_drawer(drawer: rdMolDraw2D.MolDraw2D, target_w: int) -> None:
    """Thinner bonds at table resolution; scale stroke with zoomed (2×) depictions."""
    opts = drawer.drawOptions()
    base_w = max(1.0, float(structure_depict_width()))
    ratio = max(1.0, float(target_w) / base_w)
    opts.bondLineWidth = float(STRUCTURE_DEPICT_BOND_LINE_WIDTH) * ratio
    opts.padding = float(STRUCTURE_DEPICT_PADDING)


def _apply_table_draw_options(drawer: rdMolDraw2D.MolDraw2DCairo, target_w: int) -> None:
    configure_mol_drawer(drawer, target_w)


def _has_nonzero_z(mol: Chem.Mol, *, z_eps: float = _Z_3D_EPS) -> bool:
    """True when the current conformer is a 3D pose (not a flat depiction)."""
    if mol.GetNumConformers() == 0:
        return False
    conf = mol.GetConformer()
    return any(abs(float(conf.GetAtomPosition(i).z)) > z_eps for i in range(mol.GetNumAtoms()))


def _atom_is_labeled(atom: Chem.Atom) -> bool:
    """RDKit paints a symbol for non-carbon atoms and charged carbons."""
    return int(atom.GetAtomicNum()) != 6 or int(atom.GetFormalCharge()) != 0


def _is_centered_terminal_double(begin: Chem.Atom, end: Chem.Atom) -> bool:
    """
    True for C=O / C=S / terminal hetero doubles that RDKit already draws as
    two parallel strokes straddling the axis.
    """
    if begin.GetDegree() == 1 and end.GetDegree() == 1:
        return True
    for term in (begin, end):
        if term.GetDegree() != 1:
            continue
        # Terminal CH2= is unlabeled carbon → offset alkene, not a carbonyl.
        return term.GetAtomicNum() != 6
    return False


def acyclic_offset_double_bond_indices(mol: Chem.Mol) -> list[int]:
    """
    Acyclic offset-style C=C (and similar) bonds whose RDKit inner stroke is not
    parallel to the main bond.

    Ring doubles and centered terminal hetero doubles (C=O) are left to MolDraw2D.
    """
    rings = mol.GetRingInfo()
    n_rings = 0
    try:
        n_rings = int(rings.NumRings())
    except Exception:
        n_rings = 0
    out: list[int] = []
    for bond in mol.GetBonds():
        if bond.GetBondType() != Chem.BondType.DOUBLE:
            continue
        if bond.GetStereo() == Chem.BondStereo.STEREOANY:
            continue
        try:
            if bond.GetBondDir() == Chem.BondDir.EITHERDOUBLE:
                continue
        except Exception:
            pass
        if n_rings and rings.NumBondRings(bond.GetIdx()):
            continue
        if _is_centered_terminal_double(bond.GetBeginAtom(), bond.GetEndAtom()):
            continue
        out.append(int(bond.GetIdx()))
    return out


def _mol_xy(mol: Chem.Mol) -> dict[int, tuple[float, float]]:
    conf = mol.GetConformer()
    return {
        i: (float(conf.GetAtomPosition(i).x), float(conf.GetAtomPosition(i).y))
        for i in range(mol.GetNumAtoms())
    }


def _mean_bond_length(mol: Chem.Mol, coords: dict[int, tuple[float, float]]) -> float:
    lengths = [
        math.hypot(
            coords[b.GetEndAtomIdx()][0] - coords[b.GetBeginAtomIdx()][0],
            coords[b.GetEndAtomIdx()][1] - coords[b.GetBeginAtomIdx()][1],
        )
        for b in mol.GetBonds()
    ]
    return sum(lengths) / len(lengths) if lengths else 1.5


def _double_bond_side_counts(
    mol: Chem.Mol,
    atom_i: int,
    atom_j: int,
    coords: dict[int, tuple[float, float]],
) -> tuple[int, int, int, int]:
    """Substituent counts on each side of *atom_i*–*atom_j* (cross-product sign)."""
    x1, y1 = coords[atom_i]
    x2, y2 = coords[atom_j]
    dx, dy = x2 - x1, y2 - y1
    length = max(math.hypot(dx, dy), 1e-6)
    ux, uy = dx / length, dy / length
    pos_n = neg_n = 0
    extra_i = extra_j = 0
    for end, is_i in ((atom_i, True), (atom_j, False)):
        ex, ey = coords[end]
        for nbr in mol.GetAtomWithIdx(end).GetNeighbors():
            oid = int(nbr.GetIdx())
            if oid in (atom_i, atom_j) or int(nbr.GetAtomicNum()) == 1:
                continue
            if is_i:
                extra_i += 1
            else:
                extra_j += 1
            ox, oy = coords[oid][0] - ex, coords[oid][1] - ey
            cross = ux * oy - uy * ox
            if cross > 1e-6:
                pos_n += 1
            elif cross < -1e-6:
                neg_n += 1
    return pos_n, neg_n, extra_i, extra_j


def _atom_draw_color(atom: Chem.Atom) -> tuple[float, float, float]:
    r, g, b = rdkit_default_element_rgb(atom.GetSymbol())
    return r / 255.0, g / 255.0, b / 255.0


def _draw_coloured_line(
    drawer: rdMolDraw2D.MolDraw2D,
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    color_a: tuple[float, float, float],
    color_b: tuple[float, float, float],
) -> None:
    if color_a == color_b:
        drawer.SetColour(color_a)
        drawer.DrawLine(Point2D(x1, y1), Point2D(x2, y2))
        return
    mx, my = (x1 + x2) * 0.5, (y1 + y2) * 0.5
    drawer.SetColour(color_a)
    drawer.DrawLine(Point2D(x1, y1), Point2D(mx, my))
    drawer.SetColour(color_b)
    drawer.DrawLine(Point2D(mx, my), Point2D(x2, y2))


def offset_double_inner_strokes(
    mol: Chem.Mol, *, multiple_bond_offset: float
) -> list[
    tuple[tuple[float, float], tuple[float, float], tuple[float, float], tuple[float, float]]
]:
    """
    Inner-stroke endpoints for acyclic offset doubles.

    Each item is ``((x1, y1), (x2, y2), (sx, sy), (ex, ey))``: main-bond ends then
    the shortened parallel inner stroke (molecule-frame coordinates).
    """
    idxs = acyclic_offset_double_bond_indices(mol)
    if not idxs or mol.GetNumConformers() == 0:
        return []
    coords = _mol_xy(mol)
    dist = float(multiple_bond_offset) * _mean_bond_length(mol, coords)
    out: list[
        tuple[tuple[float, float], tuple[float, float], tuple[float, float], tuple[float, float]]
    ] = []
    for bid in idxs:
        bond = mol.GetBondWithIdx(bid)
        ai, aj = int(bond.GetBeginAtomIdx()), int(bond.GetEndAtomIdx())
        x1, y1 = coords[ai]
        x2, y2 = coords[aj]
        dx, dy = x2 - x1, y2 - y1
        length = max(math.hypot(dx, dy), 1e-6)
        ux, uy = dx / length, dy / length
        ox, oy = -uy * dist, ux * dist
        pos_n, neg_n, extra_i, extra_j = _double_bond_side_counts(mol, ai, aj, coords)
        side = 1.0 if pos_n > neg_n else -1.0
        t0 = _OFFSET_DOUBLE_TRIM if extra_i else 0.0
        t1 = _OFFSET_DOUBLE_TRIM if extra_j else 0.0
        if _atom_is_labeled(bond.GetBeginAtom()):
            t0 = max(t0, _OFFSET_DOUBLE_LABEL_TRIM)
        if _atom_is_labeled(bond.GetEndAtom()):
            t1 = max(t1, _OFFSET_DOUBLE_LABEL_TRIM)
        sx = x1 + ux * (length * t0) + ox * side
        sy = y1 + uy * (length * t0) + oy * side
        ex = x2 - ux * (length * t1) + ox * side
        ey = y2 - uy * (length * t1) + oy * side
        out.append(((x1, y1), (x2, y2), (sx, sy), (ex, ey)))
    return out


def _flatten_offset_doubles_for_draw(mol: Chem.Mol, bond_indices: Sequence[int]) -> Chem.Mol:
    """Copy of *mol* with selected doubles drawn as singles (main stroke only)."""
    draw_mol = Chem.Mol(mol)
    for bid in bond_indices:
        bond = draw_mol.GetBondWithIdx(int(bid))
        bond.SetBondType(Chem.BondType.SINGLE)
        bond.SetStereo(Chem.BondStereo.STEREONONE)
        try:
            bond.SetBondDir(Chem.BondDir.NONE)
        except Exception:
            pass
    return draw_mol


def _draw_offset_double_inner_strokes(drawer: rdMolDraw2D.MolDraw2D, mol: Chem.Mol) -> None:
    opts = drawer.drawOptions()
    strokes = offset_double_inner_strokes(mol, multiple_bond_offset=float(opts.multipleBondOffset))
    if not strokes:
        return
    try:
        drawer.SetLineWidth(float(opts.bondLineWidth))
    except Exception:
        pass
    idxs = acyclic_offset_double_bond_indices(mol)
    for bid, (_a, _b, start, finish) in zip(idxs, strokes):
        bond = mol.GetBondWithIdx(bid)
        _draw_coloured_line(
            drawer,
            start[0],
            start[1],
            finish[0],
            finish[1],
            _atom_draw_color(bond.GetBeginAtom()),
            _atom_draw_color(bond.GetEndAtom()),
        )


def _prepare_mol_for_drawing(mol: Chem.Mol) -> Chem.Mol:
    work = Chem.Mol(mol)
    if _has_nonzero_z(work):
        work.RemoveAllConformers()
    try:
        prepared = rdMolDraw2D.PrepareMolForDrawing(work)
    except Exception:
        prepared = rdMolDraw2D.PrepareMolForDrawing(work, kekulize=False)
    if prepared is None:
        raise ValueError("PrepareMolForDrawing returned None.")
    return prepared


def prepare_and_draw_molecule(
    drawer: rdMolDraw2D.MolDraw2D,
    mol: Chem.Mol,
    *,
    highlight_atoms: Sequence[int] | None = None,
    highlight_color: tuple[float, float, float] = (0.95, 0.55, 0.15),
) -> Chem.Mol:
    """
    Draw *mol* like ``PrepareAndDrawMolecule``, with parallel inner strokes on
    acyclic offset double bonds (IUPAC GR-1.6).

    Does not call ``FinishDrawing``.
    """
    prepared = _prepare_mol_for_drawing(mol)
    redraw = acyclic_offset_double_bond_indices(prepared)
    draw_mol = _flatten_offset_doubles_for_draw(prepared, redraw) if redraw else prepared
    highlight_set = {int(i) for i in (highlight_atoms or [])}
    if highlight_set:
        colors = {i: highlight_color for i in highlight_set}
        drawer.DrawMolecule(
            draw_mol,
            highlightAtoms=list(highlight_set),
            highlightAtomColors=colors,
        )
    else:
        drawer.DrawMolecule(draw_mol)
    if redraw:
        _draw_offset_double_inner_strokes(drawer, prepared)
    return prepared


def render_molecule_png(
    mol: Chem.Mol,
    target_w: int,
    target_h: int,
    *,
    highlight_atoms: Sequence[int] | None = None,
    highlight_color: tuple[float, float, float] = (0.95, 0.55, 0.15),
    background_rgba: tuple[float, float, float, float] | None = None,
) -> bytes:
    """Draw *mol* to PNG bytes at the requested table / zoom / browser size."""
    cw, ch = structure_cairo_dimensions(target_w, target_h)
    drawer = rdMolDraw2D.MolDraw2DCairo(int(cw), int(ch))
    configure_mol_drawer(drawer, int(cw))
    if background_rgba is not None:
        drawer.drawOptions().setBackgroundColour(background_rgba)
    prepare_and_draw_molecule(
        drawer,
        mol,
        highlight_atoms=highlight_atoms,
        highlight_color=highlight_color,
    )
    drawer.FinishDrawing()
    return drawer.GetDrawingText()


def render_reaction_png(smarts: str, target_w: int, target_h: int) -> bytes:
    """Draw a reaction SMARTS scheme (reactants → products) to PNG bytes."""
    text = (smarts or "").strip()
    if not text:
        raise ValueError("Reaction SMARTS is empty.")
    rxn = AllChem.ReactionFromSmarts(text)
    if rxn is None:
        raise ValueError("Could not parse reaction SMARTS.")
    try:
        AllChem.SanitizeRxn(rxn)
    except Exception:
        pass
    try:
        AllChem.Compute2DCoordsForReaction(rxn)
    except Exception:
        pass
    cw, ch = structure_cairo_dimensions(target_w, target_h)
    drawer = rdMolDraw2D.MolDraw2DCairo(int(cw), int(ch))
    # Scale bonds like a molecule cell, not the wider reaction canvas.
    configure_mol_drawer(drawer, structure_depict_width())
    drawer.drawOptions().padding = float(REACTION_DEPICT_PADDING)
    drawer.DrawReaction(rxn, highlightByReactant=False)
    drawer.FinishDrawing()
    png = drawer.GetDrawingText()
    if not png:
        raise ValueError("Reaction depiction produced no image.")
    return png


def render_depict_payload_png(
    payload: Chem.Mol | ReactionDrawSpec, target_w: int, target_h: int
) -> bytes:
    """Draw a molecule or reaction payload to PNG bytes."""
    if isinstance(payload, ReactionDrawSpec):
        return render_reaction_png(payload.smarts, target_w, target_h)
    return render_molecule_png(payload, target_w, target_h)
