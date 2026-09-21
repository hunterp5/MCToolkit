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

"""3D viewer helper (RDKit only; no Qt WebEngine required)."""

from __future__ import annotations

from rdkit import Chem

from mctoolkit.ui.mol_viewer_3d import (
    _mol_block_b64,
    _offline_index_html,
    _offline_index_html_multiconf,
    build_3dmol_html,
    bundled_3dmol_available,
    prepare_mol_2d,
    prepare_mol_3d,
)


def test_prepare_mol_3d_ethanol():
    m = Chem.MolFromSmiles("CCO")
    m3 = prepare_mol_3d(m)
    assert m3 is not None
    assert m3.GetNumConformers() >= 1


def test_build_3dmol_html_contains_script_and_model():
    m = Chem.MolFromSmiles("C")
    m3 = prepare_mol_3d(m)
    assert m3 is not None
    html = build_3dmol_html(_mol_block_b64(m3))
    assert "atob(" in html
    if bundled_3dmol_available():
        assert "3Dmol-min.js" in html
    else:
        assert "3dmol.org" in html
    # View-in-3D chrome: no mouse-controls help or atom info boxes.
    assert "chem3d-help" not in html
    assert "Mouse controls" not in html
    assert "chem-atom-panel" not in html
    assert "chem-atom-detail" not in html
    assert "Reset Structure" in html
    assert "mctoolkitResetStructure" in html
    assert "chem-reset-menu" in html
    assert "mctoolkitHomeView" in html
    assert "__RESET_JS__" not in html


def test_multiconf_html_has_no_on_canvas_chrome():
    import base64

    payload = base64.b64encode(b'["QQ=="]').decode("ascii")
    html = _offline_index_html_multiconf(payload)
    assert "chem-strain-overlay" not in html
    assert "chem-conf-bar" not in html
    assert "chem-conf-prev" not in html
    assert "mctoolkitLoadConf" in html
    assert "mctoolkitShowSuperpose" in html
    assert "mctoolkitSetConfLegend" in html
    assert "chem-conf-legend" in html
    assert "mctoolkitRefit" in html
    assert "Reset Structure" in html
    assert "mctoolkitResetStructure" in html
    assert "chem-reset-menu" in html
    assert "__RESET_JS__" not in html
    assert "ensureViewer" in html
    assert "bootView" in html
    assert "distinctOverlayColors" in html
    assert "opts && opts.colors" in html
    assert "list[mi] % palette.length" not in html
    assert "#c0392b" in html
    assert "width:100%" in html
    assert "height:100%" in html
    assert "inset:0" not in html
    assert "inset: 0" not in html


def test_bundled_3dmol_present_in_repo():
    assert bundled_3dmol_available()


def test_prepare_mol_2d_benzene():
    m = Chem.MolFromSmiles("c1ccccc1")
    m2 = prepare_mol_2d(m)
    assert m2 is not None
    assert m2.GetNumConformers() >= 1


def test_prepare_mol_3d_keeps_heteroarene_planar_from_kekule_sketch():
    """Sketch mols are Kekulé + 2D; embed must aromatize so pyridine stays planar."""
    import math

    from rdkit.Chem.rdchem import BondType, Conformer
    from rdkit.Geometry import Point3D

    rw = Chem.RWMol()
    for z in (6, 6, 6, 7, 6, 6):  # C-C-C-N-C-C ring (pyridine kekule order)
        rw.AddAtom(Chem.Atom(z))
    # C1=CC=NC=C1
    bts = (
        BondType.DOUBLE,
        BondType.SINGLE,
        BondType.DOUBLE,
        BondType.SINGLE,
        BondType.DOUBLE,
        BondType.SINGLE,
    )
    for i, bt in enumerate(bts):
        rw.AddBond(i, (i + 1) % 6, bt)
    mol = rw.GetMol()
    conf = Conformer(6)
    for i in range(6):
        ang = 2.0 * math.pi * i / 6.0
        conf.SetAtomPosition(i, Point3D(math.cos(ang), math.sin(ang), 0.0))
    mol.AddConformer(conf, assignId=True)
    assert not any(b.GetIsAromatic() for b in mol.GetBonds())

    m3 = prepare_mol_3d(mol)
    assert m3 is not None
    assert any(b.GetIsAromatic() for b in m3.GetBonds())
    c0 = m3.GetConformer()
    xs = [c0.GetAtomPosition(i).x for i in range(6)]
    ys = [c0.GetAtomPosition(i).y for i in range(6)]
    zs = [c0.GetAtomPosition(i).z for i in range(6)]
    # Plane fit: max |z'| after aligning to best-fit plane should be small.
    import numpy as np

    pts = np.column_stack([xs, ys, zs])
    centered = pts - pts.mean(axis=0)
    _, _, vh = np.linalg.svd(centered)
    dist = centered @ vh[-1]
    assert float(np.max(np.abs(dist))) < 0.05


def _sf5_ligand_distances(mol: Chem.Mol) -> list[tuple[str, float]]:
    import math

    s_idx = next(a.GetIdx() for a in mol.GetAtoms() if a.GetSymbol() == "S")
    conf = mol.GetConformer()
    sp = conf.GetAtomPosition(s_idx)
    out: list[tuple[str, float]] = []
    for a in mol.GetAtoms():
        if mol.GetBondBetweenAtoms(s_idx, a.GetIdx()) is None:
            continue
        p = conf.GetAtomPosition(a.GetIdx())
        d = math.sqrt((sp.x - p.x) ** 2 + (sp.y - p.y) ** 2 + (sp.z - p.z) ** 2)
        out.append((a.GetSymbol(), d))
    return out


def test_prepare_mol_3d_sf5_octahedral_not_uff_destroyed():
    """–SF5 must keep ~1.56 Å S–F (UFF S_6+6 otherwise stretches to ~4 Å)."""
    import numpy as np

    m = Chem.MolFromSmiles("Fc1ccc(S(F)(F)(F)(F)F)cc1")
    m3 = prepare_mol_3d(m)
    assert m3 is not None
    dists = _sf5_ligand_distances(m3)
    f_dists = [d for sym, d in dists if sym == "F"]
    c_dists = [d for sym, d in dists if sym == "C"]
    assert len(f_dists) == 5
    assert all(1.45 <= d <= 1.70 for d in f_dists)
    assert c_dists and all(1.65 <= d <= 1.95 for d in c_dists)

    s_idx = next(a.GetIdx() for a in m3.GetAtoms() if a.GetSymbol() == "S")
    f_idxs = [
        a.GetIdx()
        for a in m3.GetAtoms()
        if a.GetSymbol() == "F" and m3.GetBondBetweenAtoms(s_idx, a.GetIdx())
    ]
    conf = m3.GetConformer()
    sp = conf.GetAtomPosition(s_idx)

    def unit(i: int):
        p = conf.GetAtomPosition(i)
        v = np.array([p.x - sp.x, p.y - sp.y, p.z - sp.z], dtype=float)
        return v / np.linalg.norm(v)

    angles = []
    for i in range(len(f_idxs)):
        for j in range(i + 1, len(f_idxs)):
            ang = float(
                np.degrees(np.arccos(np.clip(np.dot(unit(f_idxs[i]), unit(f_idxs[j])), -1, 1)))
            )
            angles.append(ang)
    # Octahedral F–S–F: four ~90° and one ~180° among the five fluorines.
    assert any(abs(a - 180.0) < 8.0 for a in angles)
    near_90 = sum(1 for a in angles if abs(a - 90.0) < 8.0)
    assert near_90 >= 4


def test_prepare_mol_3d_methyl_sf5_embeds():
    m = Chem.MolFromSmiles("CS(F)(F)(F)(F)F")
    m3 = prepare_mol_3d(m)
    assert m3 is not None
    f_dists = [d for sym, d in _sf5_ligand_distances(m3) if sym == "F"]
    assert len(f_dists) == 5
    assert all(1.45 <= d <= 1.70 for d in f_dists)


def test_flat_viewer_html_sets_orthographic():
    m = Chem.MolFromSmiles("C")
    m2 = prepare_mol_2d(m)
    assert m2 is not None
    html = _offline_index_html(_mol_block_b64(m2), flat=True)
    assert "orthographic: true" in html
    assert "const flat = true" in html
