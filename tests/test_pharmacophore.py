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

"""Pharmacophore JSON, RDKit BaseFeatures, AutoDock maps, and Gnina wiring."""

from __future__ import annotations

from qt_helpers import qt_submenu

from pathlib import Path

import pytest

from molmanager.protein.pharmacophore import (
    FORMAT_ID,
    Pharmacophore,
    PharmacophoreFeature,
    feature_atom_matches,
    features_from_mol,
    gnina_user_grid_paths,
    load_pharmacophore,
    normalize_feature_atom,
    pharmacophore_from_dict,
    save_pharmacophore,
    write_autodock_map,
)


def _ethanol_3d():
    pytest.importorskip("rdkit")
    from rdkit import Chem
    from rdkit.Chem import AllChem

    mol = Chem.AddHs(Chem.MolFromSmiles("CCO"))
    assert mol is not None
    AllChem.EmbedMolecule(mol, randomSeed=1)
    return mol


def test_pharmacophore_json_roundtrip(tmp_path: Path):
    pharma = Pharmacophore()
    pharma.add_feature(feature_type="Donor", x=1.25, y=-2.5, z=3.0, radius=1.1, atom="O")
    pharma.add_feature(feature_type="Aromatic", x=0.0, y=0.0, z=0.0, enabled=False)
    path = tmp_path / "site.json"
    save_pharmacophore(path, pharma)
    loaded = load_pharmacophore(path)
    assert loaded.to_dict()["format"] == FORMAT_ID
    assert len(loaded.features) == 2
    assert loaded.features[0].type == "Donor"
    assert loaded.features[0].atom == "O"
    assert loaded.features[0].x == pytest.approx(1.25)
    assert loaded.features[1].enabled is False
    assert loaded.features[1].atom == ""
    again = pharmacophore_from_dict(loaded.to_dict())
    assert again.features[0].id == loaded.features[0].id
    assert again.features[0].atom == "O"
    aliased = pharmacophore_from_dict(
        {
            "format": FORMAT_ID,
            "version": 1,
            "features": [
                {"id": "f1", "type": "Acceptor", "elem": "n", "x": 0, "y": 0, "z": 0, "radius": 1}
            ],
        }
    )
    assert aliased.features[0].atom == "N"


def test_normalize_feature_atom_and_match():
    assert normalize_feature_atom("") == ""
    assert normalize_feature_atom("any") == ""
    assert normalize_feature_atom("o") == "O"
    assert normalize_feature_atom("cl") == "Cl"
    assert normalize_feature_atom("D") == "H"
    assert feature_atom_matches("", "N") is True
    assert feature_atom_matches("O", "O") is True
    assert feature_atom_matches("O", "N") is False


def test_rdkit_basefeatures_ethanol_has_hbond_sites():
    mol = _ethanol_3d()
    feats = features_from_mol(mol)
    families = {feat.type for feat in feats}
    assert "Donor" in families
    assert "Acceptor" in families
    hbonds = [feat for feat in feats if feat.type in {"Donor", "Acceptor"}]
    assert hbonds
    assert all(feat.atom == "O" for feat in hbonds)


def test_autodock_map_well_is_attractive_at_feature(tmp_path: Path):
    pharma = Pharmacophore(
        features=[
            PharmacophoreFeature(id="f1", type="Acceptor", x=0.0, y=0.0, z=0.0, radius=1.0),
        ]
    )
    path = tmp_path / "well.map"
    write_autodock_map(
        path,
        pharma,
        center=(0.0, 0.0, 0.0),
        size=(6.0, 6.0, 6.0),
        spacing=0.5,
    )
    text = path.read_text(encoding="ascii")
    assert "SPACING 0.500" in text
    assert "NELEMENTS" in text
    values = [float(line) for line in text.splitlines() if line and line[0] in "-0123456789"]
    assert values
    assert min(values) < -0.5
    assert min(values) < values[0]


def test_gnina_argv_omits_user_grid(tmp_path: Path, qapp):  # noqa: ARG001
    pytest.importorskip("PySide6.QtWidgets")
    from rdkit.Geometry import Point3D

    from molmanager.ui.gnina_dock import GninaDockDialog

    pharma = Pharmacophore()
    pharma.add_feature(feature_type="Donor", x=1.0, y=2.0, z=3.0)
    json_path = tmp_path / "pharma.json"
    save_pharmacophore(json_path, pharma)
    dlg = GninaDockDialog(None)
    dlg.edit_receptor.setText("rec.pdbqt")
    dlg.edit_ligand.setText("lig.sdf")
    out = tmp_path / "out.sdf"
    dlg.edit_out.setText(str(out))
    dlg.autobox_cb.setChecked(False)
    dlg.spin_cx.setValue(1.0)
    dlg.spin_cy.setValue(2.0)
    dlg.spin_cz.setValue(3.0)
    dlg.set_pharmacophore_path(str(json_path))
    assert dlg.spin_pharma_slack.value() == pytest.approx(0.50)
    argv = dlg._build_argv()
    assert "--user_grid" not in argv
    assert "--user_grid_lambda" not in argv
    dlg._require_dock_pharmacophore()
    mol = _ethanol_3d()
    donor = next(f for f in features_from_mol(mol) if f.type == "Donor")
    save_pharmacophore(
        json_path,
        Pharmacophore(
            features=[
                PharmacophoreFeature(
                    id="f1", type="Donor", x=donor.x, y=donor.y, z=donor.z, radius=1.0
                )
            ]
        ),
    )
    miss = _ethanol_3d()
    conf = miss.GetConformer()
    for i in range(miss.GetNumAtoms()):
        pos = conf.GetAtomPosition(i)
        conf.SetAtomPosition(i, Point3D(pos.x + 12.0, pos.y, pos.z))
    kept = dlg._apply_pharmacophore_filter([mol, miss], log=False)
    assert kept == [mol]
    assert mol.GetProp("pharmaMatch") == "1"
    assert miss.GetProp("pharmaMatch") == "0"
    dlg.close()


def test_gnina_user_grid_paths_uses_feature_box(tmp_path: Path):
    pharma = Pharmacophore()
    pharma.add_feature(feature_type="Hydrophobe", x=10.0, y=10.0, z=10.0, radius=1.5)
    out = tmp_path / "docked.sdf"
    map_path = gnina_user_grid_paths(pharma, out_path=out, padding=2.0)
    assert map_path.name == "docked_pharma.map"
    assert "CENTER" in map_path.read_text(encoding="ascii")


def test_protein_viewer_pharmacophore_menu(qapp):  # noqa: ARG001
    pytest.importorskip("PySide6.QtWidgets")
    from PySide6.QtWidgets import QMenuBar

    from molmanager.ui.protein_viewer import ProteinViewerDialog

    dlg = ProteinViewerDialog(None)
    mb = dlg.findChild(QMenuBar)
    assert mb is not None
    tools_menu = qt_submenu(mb, "Tools")
    pharma_menu = qt_submenu(tools_menu, "Pharmacophore")
    labels = [a.text().replace("&", "") for a in pharma_menu.actions() if a.text().strip()]
    assert labels == ["Editor", "Screen Table…", "Open…"]
    dlg._on_pharmacophore_atom_picked({"x": 1.5, "y": 2.5, "z": 3.5})
    assert dlg._ensure_pharmacophore().features == []
    dlg.open_pharmacophore_dialog()
    editor = dlg._pharmacophore_dialog
    assert editor is not None
    assert editor.btn_add_xyz.text() == "Add"
    dlg._on_pharmacophore_atom_picked({"x": 1.5, "y": 2.5, "z": 3.5, "elem": "O"})
    assert dlg._ensure_pharmacophore().features == []
    assert editor.spin_x.value() == pytest.approx(1.5)
    assert editor.spin_y.value() == pytest.approx(2.5)
    assert editor.spin_z.value() == pytest.approx(3.5)
    assert editor.next_atom() == "O"
    editor.btn_add_xyz.click()
    feats = dlg._ensure_pharmacophore().features
    assert len(feats) == 1
    assert feats[0].x == pytest.approx(1.5)
    assert feats[0].atom == "O"
    overlay = dlg._pharmacophore_overlay_payload()
    assert overlay["active"] is True
    assert overlay["features"][0]["atom"] == "O"
    editor.close()
    qapp.processEvents()
    assert dlg._pharmacophore_overlay_payload()["active"] is False
    assert len(dlg._ensure_pharmacophore().features) == 1
    dlg.open_pharmacophore_dialog()
    assert dlg._pharmacophore_overlay_payload()["active"] is True
    headers = [
        editor.table.horizontalHeaderItem(i).text() for i in range(editor.table.columnCount())
    ]
    assert headers == ["Type", "Atom", "X", "Y", "Z", "r (Å)", "On"]
    assert editor.table.verticalHeader().isVisible()
    assert editor.table.verticalHeaderItem(0).text() == feats[0].id
    dlg.close()


def test_pharmacophore_editor_row_ids_and_on_column(qapp):  # noqa: ARG001
    from PySide6.QtCore import Qt

    from molmanager.ui.dialogs.protein_pharmacophore import ProteinPharmacophoreDialog

    editor = ProteinPharmacophoreDialog()
    editor.set_features(
        [
            PharmacophoreFeature(id="f3", type="Donor", x=1.0, y=2.0, z=3.0, radius=1.1, atom="N"),
            PharmacophoreFeature(
                id="ex1", type="Exclusion", x=0.0, y=0.0, z=0.0, radius=1.5, enabled=False
            ),
        ]
    )
    assert editor.table.rowCount() == 2
    assert editor.table.verticalHeaderItem(0).text() == "f3"
    assert editor.table.verticalHeaderItem(1).text() == "ex1"
    on_col = editor.table.columnCount() - 1
    assert editor.table.horizontalHeaderItem(on_col).text() == "On"
    assert editor.table.item(0, on_col).checkState() == Qt.Checked
    assert editor.table.item(1, on_col).checkState() == Qt.Unchecked
    feat = editor._feature_at_row(1)
    assert feat is not None
    assert feat.id == "ex1"
    assert feat.enabled is False
    assert feat.type == "Exclusion"
    feat0 = editor._feature_at_row(0)
    assert feat0 is not None
    assert feat0.atom == "N"
    editor.close()


def test_pharmacophore_help_topic():
    from molmanager.ui.user_guides import guide_html

    h = guide_html("protein_pharmacophore")
    assert "Pharmacophore" in h
    assert "Gnina" in h
    assert "Topic unavailable" not in h


def test_screen_mol_matches_ethanol_self_pharmacophore():
    from molmanager.protein.pharmacophore_screen import screen_mol

    mol = _ethanol_3d()
    feats = features_from_mol(mol)
    families = {feat.type for feat in feats}
    assert "Donor" in families and "Acceptor" in families
    query = Pharmacophore(features=list(feats))
    hit = screen_mol(mol, query, slack=0.5)
    assert hit.matched
    assert hit.n_matched == len(feats)
    assert hit.rmsd is not None
    assert hit.rmsd < 0.05
    assert hit.score == pytest.approx(1.0 / (1.0 + hit.rmsd))


def test_screen_mol_rejects_impossible_pair_distance():
    from molmanager.protein.pharmacophore_screen import screen_mol

    mol = _ethanol_3d()
    query = Pharmacophore(
        features=[
            PharmacophoreFeature(id="f1", type="Donor", x=0.0, y=0.0, z=0.0, radius=1.0),
            PharmacophoreFeature(id="f2", type="Acceptor", x=20.0, y=0.0, z=0.0, radius=1.0),
        ]
    )
    hit_all = screen_mol(mol, query, slack=1.2)
    assert not hit_all.matched
    hit_one = screen_mol(mol, query, slack=1.2, min_matched=1)
    assert hit_one.matched
    assert hit_one.n_matched == 1


def test_screen_mol_requires_feature_atom_when_set():
    from molmanager.protein.pharmacophore_screen import screen_mol

    mol = _ethanol_3d()
    donor = next(f for f in features_from_mol(mol) if f.type == "Donor")
    oxygen = Pharmacophore(
        features=[
            PharmacophoreFeature(
                id="f1",
                type="Donor",
                x=donor.x,
                y=donor.y,
                z=donor.z,
                radius=donor.radius,
                atom="O",
            )
        ]
    )
    nitrogen = Pharmacophore(
        features=[
            PharmacophoreFeature(
                id="f1",
                type="Donor",
                x=donor.x,
                y=donor.y,
                z=donor.z,
                radius=donor.radius,
                atom="N",
            )
        ]
    )
    assert screen_mol(mol, oxygen, slack=1.2).matched
    assert not screen_mol(mol, nitrogen, slack=1.2).matched


def test_screen_mol_skips_exclusion_volumes():
    from molmanager.protein.pharmacophore_screen import screening_features, screen_mol

    mol = _ethanol_3d()
    donor = next(f for f in features_from_mol(mol) if f.type == "Donor")
    query = Pharmacophore(
        features=[
            donor,
            PharmacophoreFeature(id="ex", type="Exclusion", x=100.0, y=0.0, z=0.0, radius=1.5),
        ]
    )
    assert [f.type for f in screening_features(query)] == ["Donor"]
    hit = screen_mol(mol, query, slack=1.2)
    assert hit.matched
    assert hit.n_query == 1


def test_screen_packed_ensemble_cell():
    from molmanager.conformers.conformer_column_codec import (
        mol_from_packed_confs_cell,
        pack_confs_cell,
    )
    from molmanager.protein.pharmacophore_screen import screen_mol

    mol = _ethanol_3d()
    packed_text = pack_confs_cell({"n": 1}, mol)
    packed = mol_from_packed_confs_cell(packed_text, min_conformers=1)
    assert packed is not None
    query = Pharmacophore(features=features_from_mol(mol))
    hit = screen_mol(packed, query, slack=1.0)
    assert hit.matched


def test_output_column_names():
    from molmanager.protein.pharmacophore_screen import output_column_names

    assert output_column_names("pharma") == (
        "pharmaMatch",
        "pharmaScore",
        "pharmaRMSD",
        "pharmaConf",
    )


def test_pharmacophore_screen_dialog_constructible(qapp):  # noqa: ARG001
    pytest.importorskip("PySide6.QtWidgets")
    from molmanager.ui.dialogs.pharmacophore_screen import PharmacophoreScreenDialog

    dlg = PharmacophoreScreenDialog(None)
    assert dlg.windowTitle() == "Screen Pharmacophore"
    assert dlg.spin_slack.value() == pytest.approx(1.2)
    assert dlg.chk_select_hits.isChecked() is True
    assert dlg.chk_select_hits.text() == "Select Hits in Table"
    dlg.close()


def test_pharmacophore_screen_dialog_closes_when_run_starts(qapp, tmp_path, monkeypatch):
    pytest.importorskip("PySide6.QtWidgets")
    from molmanager.conformers.conformer_column_codec import pack_confs_cell
    from molmanager.protein.pharmacophore import save_pharmacophore
    from molmanager.ui.dialogs.pharmacophore_screen import PharmacophoreScreenDialog
    from molmanager.ui.main_window import ChemistryWorkspaceWindow

    mol = _ethanol_3d()
    w = ChemistryWorkspaceWindow()
    w.headers = ["ID_HIDDEN", "Structure", "SMILES", "confs"]
    w._table_model.set_headers(list(w.headers))
    w._table_model.append_row(0, {"SMILES": "CCO", "confs": pack_confs_cell({"n": 1}, mol)})
    path = tmp_path / "pharma.json"
    save_pharmacophore(path, Pharmacophore(features=features_from_mol(mol)))
    dlg = PharmacophoreScreenDialog(w, pharmacophore_path=str(path))
    dlg._refresh_ensemble_columns()
    dlg.show()
    qapp.processEvents()
    assert dlg.isVisible()
    monkeypatch.setattr(w.process_queue, "enqueue_fast", lambda *a, **k: None)
    monkeypatch.setattr(w, "_begin_tool_progress", lambda *a, **k: None)
    dlg.run_screen()
    assert dlg.isVisible() is False
    w.close()


def test_pharmacophore_screen_selects_hits_in_table(qapp):  # noqa: ARG001
    pytest.importorskip("PySide6.QtWidgets")
    from molmanager.ui.dialogs.pharmacophore_screen import PharmacophoreScreenDialog
    from molmanager.ui.main_window import ChemistryWorkspaceWindow

    w = ChemistryWorkspaceWindow()
    w.headers = ["ID_HIDDEN", "Structure", "SMILES"]
    w._table_model.set_headers(list(w.headers))
    w._table_model.append_row(0, {"SMILES": "CCO"})
    w._table_model.append_row(1, {"SMILES": "CCN"})
    dlg = PharmacophoreScreenDialog(w)
    dlg._select_hits = True
    dlg._pending_columns = ("pharmaMatch", "pharmaScore", "pharmaRMSD", "pharmaConf")
    dlg._compare_oids = {0, 1}
    dlg._write_columns(
        [
            (0, True, 0.9, 0.1, 0),
            (1, False, 0.1, 2.0, 1),
        ]
    )
    qapp.processEvents()
    assert w._selected_oids_set() == {0}
    dlg._select_hits = False
    dlg._pending_columns = (
        "pharmaMatch (1)",
        "pharmaScore (1)",
        "pharmaRMSD (1)",
        "pharmaConf (1)",
    )
    dlg._write_columns(
        [
            (0, False, 0.1, 2.0, 0),
            (1, True, 0.8, 0.2, 1),
        ]
    )
    qapp.processEvents()
    assert w._selected_oids_set() == {0}
    dlg.close()
    w.close()


def test_pharmacophore_screen_help_topic():
    from molmanager.ui.user_guides import guide_html

    h = guide_html("tools_pharmacophore_screen")
    assert "Screen Pharmacophore" in h
    assert "confs" in h
    assert "Select Hits in Table" in h
    assert "Topic unavailable" not in h


def test_screen_one_worker_helper():
    from molmanager.workers.pharmacophore_screen import _screen_one

    mol = _ethanol_3d()
    query = Pharmacophore(features=features_from_mol(mol)).to_dict()
    oid, matched, score, rmsd, conf_id = _screen_one(7, mol, query, 1.2, None)
    assert oid == 7
    assert matched is True
    assert score > 0.5
    assert rmsd is not None
    assert conf_id is not None


def test_docked_pose_match_is_protein_frame():
    from rdkit.Geometry import Point3D

    from molmanager.protein.pharmacophore_screen import match_docked_pose, screen_mol

    mol = _ethanol_3d()
    feats = features_from_mol(mol)
    query = Pharmacophore(features=list(feats))
    hit = match_docked_pose(mol, query, slack=0.5)
    assert hit.matched
    assert hit.rmsd is not None
    assert hit.rmsd < 0.05
    conf = mol.GetConformer()
    for i in range(mol.GetNumAtoms()):
        pos = conf.GetAtomPosition(i)
        conf.SetAtomPosition(i, Point3D(pos.x + 20.0, pos.y, pos.z))
    moved = match_docked_pose(mol, query, slack=0.5)
    assert not moved.matched
    ensemble = screen_mol(mol, query, slack=1.2)
    assert ensemble.matched


def test_docked_pose_exclusion_rejects_heavy_atom():
    from molmanager.protein.pharmacophore_screen import match_docked_pose

    mol = _ethanol_3d()
    conf = mol.GetConformer()
    heavy = next(a.GetIdx() for a in mol.GetAtoms() if a.GetAtomicNum() > 1)
    pos = conf.GetAtomPosition(heavy)
    query = Pharmacophore(
        features=[
            PharmacophoreFeature(
                id="ex",
                type="Exclusion",
                x=float(pos.x),
                y=float(pos.y),
                z=float(pos.z),
                radius=1.0,
            )
        ]
    )
    hit = match_docked_pose(mol, query, slack=0.5)
    assert not hit.matched


def test_docked_pose_exclusion_respects_atom():
    from molmanager.protein.pharmacophore_screen import match_docked_pose

    mol = _ethanol_3d()
    conf = mol.GetConformer()
    oxygen = next(a for a in mol.GetAtoms() if a.GetSymbol() == "O")
    pos = conf.GetAtomPosition(oxygen.GetIdx())
    nitrogen_ex = Pharmacophore(
        features=[
            PharmacophoreFeature(
                id="ex",
                type="Exclusion",
                x=float(pos.x),
                y=float(pos.y),
                z=float(pos.z),
                radius=1.0,
                atom="N",
            )
        ]
    )
    oxygen_ex = Pharmacophore(
        features=[
            PharmacophoreFeature(
                id="ex",
                type="Exclusion",
                x=float(pos.x),
                y=float(pos.y),
                z=float(pos.z),
                radius=1.0,
                atom="O",
            )
        ]
    )
    assert match_docked_pose(mol, nitrogen_ex, slack=0.5).matched
    assert not match_docked_pose(mol, oxygen_ex, slack=0.5).matched


def test_filter_docked_poses_keeps_only_matches():
    from rdkit.Geometry import Point3D

    from molmanager.protein.pharmacophore_screen import (
        POSE_PHARMA_MATCH_PROP,
        filter_docked_poses,
        match_docked_pose,
    )

    mol = _ethanol_3d()
    feats = [f for f in features_from_mol(mol) if f.type in {"Donor", "Acceptor"}]
    query = Pharmacophore(features=list(feats))
    other = _ethanol_3d()
    conf = other.GetConformer()
    for i in range(other.GetNumAtoms()):
        pos = conf.GetAtomPosition(i)
        conf.SetAtomPosition(i, Point3D(pos.x + 15.0, pos.y + 15.0, pos.z))
    assert match_docked_pose(mol, query, slack=0.5).matched
    assert not match_docked_pose(other, query, slack=0.5).matched
    kept, dropped = filter_docked_poses([mol, other], query, slack=0.5)
    assert kept == [mol]
    assert dropped == [other]
    assert mol.GetProp(POSE_PHARMA_MATCH_PROP) == "1"
    assert other.GetProp(POSE_PHARMA_MATCH_PROP) == "0"
