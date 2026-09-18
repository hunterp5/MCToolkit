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

from pathlib import Path

import pytest

from molmanager.pharmacophore import (
    FORMAT_ID,
    Pharmacophore,
    PharmacophoreFeature,
    features_from_mol,
    gnina_user_grid_paths,
    load_pharmacophore,
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
    pharma.add_feature(feature_type="Donor", x=1.25, y=-2.5, z=3.0, radius=1.1)
    pharma.add_feature(feature_type="Aromatic", x=0.0, y=0.0, z=0.0, enabled=False)
    path = tmp_path / "site.json"
    save_pharmacophore(path, pharma)
    loaded = load_pharmacophore(path)
    assert loaded.to_dict()["format"] == FORMAT_ID
    assert len(loaded.features) == 2
    assert loaded.features[0].type == "Donor"
    assert loaded.features[0].x == pytest.approx(1.25)
    assert loaded.features[1].enabled is False
    again = pharmacophore_from_dict(loaded.to_dict())
    assert again.features[0].id == loaded.features[0].id


def test_rdkit_basefeatures_ethanol_has_hbond_sites():
    mol = _ethanol_3d()
    feats = features_from_mol(mol)
    families = {feat.type for feat in feats}
    assert "Donor" in families
    assert "Acceptor" in families


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


def test_gnina_argv_includes_user_grid(tmp_path: Path, qapp):  # noqa: ARG001
    pytest.importorskip("PyQt5.QtWidgets")
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
    argv = dlg._build_argv()
    assert argv[argv.index("--user_grid") + 1].endswith("_pharma.map")
    assert argv[argv.index("--user_grid_lambda") + 1] == "1.000"
    map_path = Path(argv[argv.index("--user_grid") + 1])
    assert map_path.is_file()
    dlg.close()


def test_gnina_user_grid_paths_uses_feature_box(tmp_path: Path):
    pharma = Pharmacophore()
    pharma.add_feature(feature_type="Hydrophobe", x=10.0, y=10.0, z=10.0, radius=1.5)
    out = tmp_path / "docked.sdf"
    map_path = gnina_user_grid_paths(pharma, out_path=out, padding=2.0)
    assert map_path.name == "docked_pharma.map"
    assert "CENTER" in map_path.read_text(encoding="ascii")


def test_protein_viewer_pharmacophore_menu(qapp):  # noqa: ARG001
    pytest.importorskip("PyQt5.QtWidgets")
    from PyQt5.QtWidgets import QAction

    from molmanager.ui.protein_viewer import ProteinViewerDialog

    dlg = ProteinViewerDialog(None)
    texts = [act.text().replace("&", "") for act in dlg.findChildren(QAction)]
    assert "Pharmacophore" in texts or "Edit Pharmacophore…" in texts
    assert "Place on Atom Click" in texts
    dlg.set_pharmacophore_place_mode(True)
    dlg._on_pharmacophore_atom_picked({"x": 1.5, "y": 2.5, "z": 3.5})
    feats = dlg._ensure_pharmacophore().features
    assert len(feats) == 1
    assert feats[0].x == pytest.approx(1.5)
    overlay = dlg._pharmacophore_overlay_payload()
    assert overlay["active"] is True
    dlg.close()


def test_pharmacophore_help_topic():
    from molmanager.ui.user_guides import guide_html

    h = guide_html("protein_pharmacophore")
    assert "Pharmacophore" in h
    assert "Gnina" in h
    assert "Topic unavailable" not in h
