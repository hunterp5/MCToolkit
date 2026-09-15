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

"""Dock menu, Smina results viewer, and dock-results chrome."""

from __future__ import annotations

import pytest

pytest.importorskip("PyQt5.QtWidgets")


def test_dock_menu_includes_smina(qapp):  # noqa: ARG001
    from molmanager.ui.main_window import ChemicalTableApp

    w = ChemicalTableApp()
    assert hasattr(w, "open_smina_dock")
    assert not hasattr(w, "open_easydock")
    tools = None
    for act in w.menuBar().actions():
        menu = act.menu()
        if menu is not None and act.text().replace("&", "") == "Tools":
            tools = menu
            break
    assert tools is not None
    dock = None
    for act in tools.actions():
        menu = act.menu()
        if menu is not None and act.text().replace("&", "") == "Dock":
            dock = menu
            break
    assert dock is not None
    dock_actions = list(dock.actions())
    assert dock_actions[0].menu() is not None
    assert dock_actions[0].text().replace("&", "") == "Prepare"
    assert dock_actions[1].isSeparator()
    labels = [a.text() for a in dock_actions if a.text()]
    assert not any(t.startswith("EasyDock") for t in labels)
    assert any(t.startswith("Smina") for t in labels)
    assert any(t.replace("&", "") == "Viewer" for t in labels)
    assert not any("Smina CLI" in t for t in labels)
    viewer_act = next(a for a in dock_actions if a.text().replace("&", "") == "Viewer")
    assert viewer_act.isEnabled() is False
    predict = None
    for act in tools.actions():
        menu = act.menu()
        if menu is not None and act.text().replace("&", "") == "Predict":
            predict = menu
            break
    assert predict is not None
    pred_labels = [a.text() for a in predict.actions() if a.text()]
    assert any("pKa" in t for t in pred_labels)
    assert any("Permeability" in t for t in pred_labels)
    som = None
    mets = None
    for act in predict.actions():
        menu = act.menu()
        label = act.text().replace("&", "")
        if menu is not None and label == "SOM":
            som = menu
        if menu is not None and label == "Metabolites":
            mets = menu
    assert som is not None
    assert mets is not None
    som_labels = [a.text().replace("&", "") for a in som.actions() if a.text()]
    met_labels = [a.text().replace("&", "") for a in mets.actions() if a.text()]
    assert som_labels[0].startswith("Predict")
    assert "Viewer" in som_labels
    assert met_labels[0].startswith("Predict")
    assert "Viewer" in met_labels
    som_viewer = next(a for a in som.actions() if a.text().replace("&", "") == "Viewer")
    met_viewer = next(a for a in mets.actions() if a.text().replace("&", "") == "Viewer")
    assert som_viewer.isEnabled() is False
    assert met_viewer.isEnabled() is False
    prepare = None
    for act in dock.actions():
        menu = act.menu()
        if menu is not None and act.text().replace("&", "") == "Prepare":
            prepare = menu
            break
    assert prepare is not None
    prep_labels = [a.text() for a in prepare.actions() if a.text()]
    assert any("PDBQT" in t for t in prep_labels)
    assert any("PDB" in t for t in prep_labels)
    w.close()


def test_predict_viewers_enable_when_table_has_results(qapp):  # noqa: ARG001
    from molmanager.biotransformer import METABOLITE_SMILES_COLUMN
    from molmanager.som_prediction import SOM_MAP_COLUMN
    from molmanager.ui.main_window import ChemicalTableApp

    w = ChemicalTableApp()
    w._sync_predict_viewer_actions()
    assert w._act_som_viewer.isEnabled() is False
    assert w._act_metabolite_viewer.isEnabled() is False
    w.headers = ["ID_HIDDEN", "Structure", SOM_MAP_COLUMN]
    w._table_model.set_headers(list(w.headers))
    w._sync_predict_viewer_actions()
    assert w._act_som_viewer.isEnabled() is True
    assert w._act_metabolite_viewer.isEnabled() is False
    w.headers.append(METABOLITE_SMILES_COLUMN)
    w._table_model.set_headers(list(w.headers))
    w._sync_predict_viewer_actions()
    assert w._act_metabolite_viewer.isEnabled() is True
    w.close()


def test_open_dock_results_window_lists_smina_fields(qapp, tmp_path, monkeypatch):  # noqa: ARG001
    from rdkit import Chem
    from rdkit.Geometry import Point3D

    from molmanager.ui.dock_complex_viewer import DockComplexEmbedView
    from molmanager.ui.main_window import ChemicalTableApp

    monkeypatch.setattr(DockComplexEmbedView, "_ensure_web", lambda self: None)

    mol = Chem.MolFromSmiles("CCO")
    assert mol is not None
    conf = Chem.Conformer(mol.GetNumAtoms())
    conf.SetAtomPosition(0, Point3D(1.0, 0.0, 0.0))
    conf.SetAtomPosition(1, Point3D(2.4, 0.0, 0.0))
    conf.SetAtomPosition(2, Point3D(3.0, 1.1, 0.0))
    mol.AddConformer(conf, assignId=True)
    mol.SetProp("minimizedAffinity", "-7.250")
    mol.SetProp("rmsd_lb", "0.000")
    mol.SetProp("rmsd_ub", "0.000")
    mol.SetProp("mode", "1")
    mol.SetProp("poseStage", "minimized")
    rec = tmp_path / "rec.pdbqt"
    rec.write_text(
        "ATOM      1  CA  ALA A   1       0.000   0.000   0.000  1.00  0.00     0.000 C \n",
        encoding="utf-8",
    )
    parent = ChemicalTableApp()
    win = parent.open_dock_results_window([mol], title="Dock results", receptor_path=str(rec))
    assert win is not None
    assert "minimizedAffinity" in win.headers
    assert "rmsd_lb" in win.headers
    assert "mode" in win.headers
    assert "poseStage" in win.headers
    assert win._table_model.rowCount() == 1
    aff_col = win.headers.index("minimizedAffinity")
    assert win._table_model.cell_text(0, aff_col) == "-7.250"
    assert getattr(win, "_dock_complex_viewer", None) is not None
    assert getattr(win, "_dock_pose_mols", None)
    viewer = win._dock_complex_viewer
    assert viewer._rec_b64
    assert viewer._lig_b64
    mb = win.menuBar()
    top = [a.text().replace("&", "") for a in mb.actions() if a.text()]
    assert top == ["File", "View"]
    file_menu = mb.actions()[0].menu()
    assert file_menu is not None
    file_labels = [a.text().replace("&", "") for a in file_menu.actions() if a.text()]
    assert file_labels[0].startswith("Save File")
    assert any(t.startswith("Save Selected") for t in file_labels)
    assert not any(t.startswith("Browser") for t in file_labels)
    assert not any("Open File" in t or t.startswith("Tools") for t in file_labels)
    view_menu = mb.actions()[1].menu()
    assert view_menu is not None
    view_labels = [a.text().replace("&", "") for a in view_menu.actions() if a.text()]
    assert view_labels == ["Render", "Pocket View"]
    render_menu = view_menu.actions()[0].menu()
    assert render_menu is not None
    render_labels = [a.text() for a in render_menu.actions() if a.text()]
    assert render_labels == ["Receptor", "Ligand", "Pocket residues"]
    rec_menu = render_menu.actions()[0].menu()
    assert rec_menu is not None
    rec_styles = [a.text() for a in rec_menu.actions() if a.text()]
    assert rec_styles == ["Cartoon", "Surface", "Sticks", "Wireframe", "Hidden"]
    viewer.set_render_style("ligand", "sphere")
    assert viewer.render_styles()["ligand"] == "sphere"
    hdr_menu = win._create_header_context_menu(aff_col)
    assert hdr_menu is not None
    hdr_titles = [a.text() for a in hdr_menu.actions() if a.text()]
    assert any(t.startswith("Select column") for t in hdr_titles)
    assert "Select" in hdr_titles
    assert "Sort" in hdr_titles
    assert "Search" not in hdr_titles
    assert "Color" not in hdr_titles
    assert "Logarithmic" not in hdr_titles
    assert not any(t.startswith("Rename") for t in hdr_titles)
    parent.headers = ["ID_HIDDEN", "Structure", "MW"]
    parent._table_model.set_headers(list(parent.headers))
    main_hdr = parent._create_header_context_menu(2)
    assert main_hdr is not None
    main_titles = [a.text() for a in main_hdr.actions() if a.text()]
    assert "Search" in main_titles
    assert "Color" in main_titles
    win.close()
    parent.close()


def test_dock_viewer_reopens_closed_results_window(qapp, tmp_path, monkeypatch):  # noqa: ARG001
    from PyQt5.QtWidgets import QApplication
    from rdkit import Chem
    from rdkit.Geometry import Point3D

    from molmanager.ui.dock_complex_viewer import DockComplexEmbedView
    from molmanager.ui.main_window import ChemicalTableApp

    monkeypatch.setattr(DockComplexEmbedView, "_ensure_web", lambda self: None)

    mol = Chem.MolFromSmiles("CCO")
    assert mol is not None
    conf = Chem.Conformer(mol.GetNumAtoms())
    conf.SetAtomPosition(0, Point3D(1.0, 0.0, 0.0))
    conf.SetAtomPosition(1, Point3D(2.4, 0.0, 0.0))
    conf.SetAtomPosition(2, Point3D(3.0, 1.1, 0.0))
    mol.AddConformer(conf, assignId=True)
    mol.SetProp("minimizedAffinity", "-7.250")
    rec = tmp_path / "rec.pdbqt"
    rec.write_text(
        "ATOM      1  CA  ALA A   1       0.000   0.000   0.000  1.00  0.00     0.000 C \n",
        encoding="utf-8",
    )
    parent = ChemicalTableApp()
    try:
        assert parent._act_dock_viewer.isEnabled() is False
        win = parent.open_dock_results_window([mol], title="Dock results", receptor_path=str(rec))
        assert win is not None
        assert parent._act_dock_viewer.isEnabled() is True
        raised = parent.open_dock_results_viewer()
        assert raised is win
        win.close()
        QApplication.processEvents()
        assert win.isVisible() is False
        again = parent.open_dock_results_viewer()
        assert again is win
        assert again.isVisible() is True
        assert again._table_model.rowCount() == 1
        assert "minimizedAffinity" in again.headers
        aff_col = again.headers.index("minimizedAffinity")
        assert again._table_model.cell_text(0, aff_col) == "-7.250"
    finally:
        parent.close()
