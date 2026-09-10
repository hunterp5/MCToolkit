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

"""3Dmol dock-complex viewer helpers (no Qt WebEngine required)."""

from __future__ import annotations

from rdkit import Chem
from rdkit.Geometry import Point3D

from molmanager.ui.dock_complex_viewer import (
    build_dock_complex_html,
    ligand_display_payload,
    load_receptor_display_text,
    pdbqt_to_pdb_text,
    pdbqt_type_to_element,
)


def test_pdbqt_type_to_element():
    assert pdbqt_type_to_element("OA") == "O"
    assert pdbqt_type_to_element("HD") == "H"
    assert pdbqt_type_to_element("A") == "C"
    assert pdbqt_type_to_element("SA") == "S"
    assert pdbqt_type_to_element("Cl") == "Cl"


def test_pdbqt_to_pdb_text_keeps_backbone():
    pdbqt = (
        "ATOM      1  N   MET A   1      27.340  24.430   2.614  1.00  0.00    -0.302 N \n"
        "ATOM      2  CA  MET A   1      26.010  13.311  -8.124  1.00  0.00     0.175 C \n"
        "ATOM      3  OA  TYR A   1      25.967  10.940  -8.520  1.00  0.00    -0.272 OA\n"
        "TORSDOF 0\n"
        "ROOT\n"
    )
    pdb = pdbqt_to_pdb_text(pdbqt)
    assert "ATOM" in pdb
    assert " CA " in pdb
    assert "OA\n" not in pdb
    lines = [ln for ln in pdb.splitlines() if ln.startswith("ATOM")]
    assert lines[-1].rstrip().endswith(" O") or lines[-1].rstrip().endswith("O")
    assert "TORSDOF" not in pdb
    assert pdb.strip().endswith("END")


def test_load_receptor_display_text(tmp_path):
    rec = tmp_path / "rec.pdbqt"
    rec.write_text(
        "ATOM      1  CA  ALA A   1       1.000   2.000   3.000  1.00  0.00     0.000 C \n",
        encoding="utf-8",
    )
    text = load_receptor_display_text(rec)
    assert "ATOM" in text
    assert "1.000" in text
    assert load_receptor_display_text(tmp_path / "missing.pdbqt") == ""


def test_ligand_display_payload_keeps_docked_coords():
    mol = Chem.MolFromSmiles("CCO")
    assert mol is not None
    conf = Chem.Conformer(mol.GetNumAtoms())
    conf.SetAtomPosition(0, Point3D(11.5, 0.0, 0.0))
    conf.SetAtomPosition(1, Point3D(12.9, 0.0, 0.0))
    conf.SetAtomPosition(2, Point3D(13.5, 1.1, 0.0))
    mol.AddConformer(conf, assignId=True)
    b64, fmt = ligand_display_payload(mol)
    assert b64
    assert fmt == "sdf"
    import base64

    block = base64.b64decode(b64.encode("ascii")).decode("utf-8")
    assert "11.5000" in block or "11.5" in block
    empty, _fmt = ligand_display_payload(Chem.MolFromSmiles("CCO"))
    assert empty == ""


def test_build_dock_complex_html_has_setters():
    html = build_dock_complex_html()
    assert "molmanagerSetDockComplexPayload" in html
    assert "molmanagerResizeKeepView" in html
    assert "molmanagerApplyRenderStyles" in html
    assert "molmanagerApplyPocketView" in html
    assert "addResLabels" in html
    assert "getView" in html
    assert "setView" in html
    assert "molmanagerRefit" not in html
    assert "addModel" in html
    assert "cartoon" in html
    assert "Reset Structure" in html
    assert "__RESET_JS__" not in html


def test_set_render_style_updates_state(qapp):  # noqa: ARG001
    from molmanager.ui.dock_complex_viewer import DEFAULT_RENDER_STYLES, DockComplexEmbedView

    view = DockComplexEmbedView()
    assert view.render_styles() == DEFAULT_RENDER_STYLES
    view.set_render_style("receptor", "surface")
    view.set_render_style("ligand", "line")
    view.set_render_style("pocket", "hidden")
    assert view.render_styles()["receptor"] == "surface"
    assert view.render_styles()["ligand"] == "line"
    assert view.render_styles()["pocket"] == "hidden"
    view.set_render_style("receptor", "not-a-style")
    assert view.render_styles()["receptor"] == "surface"
    view.apply_pocket_view()
    assert view.render_styles() == {
        "receptor": "cartoon",
        "ligand": "ballstick",
        "pocket": "ballstick",
    }
    assert view._pocket_labels is True
    view.close()
