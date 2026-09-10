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

"""PropertyColumnsPanel used by Browser-style viewers."""

from __future__ import annotations

from rdkit import Chem

from molmanager.ui.main_window import ChemicalTableApp
from molmanager.ui.property_columns_panel import PropertyColumnsPanel


def test_property_columns_panel_defaults_and_oid_values(qapp):  # noqa: ARG001
    w = ChemicalTableApp()
    w.headers = ["ID_HIDDEN", "Structure", "SMILES", "Name", "MW", "TPSA", "cLogP"]
    w._table_model.set_headers(list(w.headers))
    w._table_model.append_row(
        0, {"SMILES": "CCO", "Name": "ethanol", "MW": "46.07", "TPSA": "20.2", "cLogP": "-0.3"}
    )
    w.mols[0] = Chem.MolFromSmiles("CCO")
    w.next_oid = 1

    panel = PropertyColumnsPanel()
    panel.bind_app(w)
    panel.set_source_oid(0)

    assert len(panel._prop_combos) == 5
    assert panel._prop_combo_1.currentText() == "SMILES"
    assert panel._prop_combo_2.currentText() == "Name"
    assert panel._prop_combo_3.currentText() == "MW"
    assert panel._prop_combos[3].currentText() == "TPSA"
    assert panel._prop_combos[4].currentText() == "cLogP"
    assert panel._prop_value_1.text() == "CCO"
    assert panel._prop_value_2.text() == "ethanol"
    assert panel._prop_value_3.text() == "46.07"
    assert panel._prop_values[3].text() == "20.2"
    assert panel._prop_values[4].text() == "-0.3"

    panel.set_source_oid(None)
    assert panel._prop_value_1.text() == "—"


def test_molecule_viewer_has_no_options_toggle(qapp):  # noqa: ARG001
    from molmanager.ui.mol_viewer_3d import Molecule3DViewerWidget, prepare_mol_2d

    m2 = prepare_mol_2d(Chem.MolFromSmiles("CCO"))
    assert m2 is not None
    viewer = Molecule3DViewerWidget(m2, None, window_title="View in 2D", flat=True)
    assert viewer._options_host is not None
    assert not viewer._options_host.isHidden()
    assert not hasattr(viewer, "_toggle_options_btn")
    assert viewer._conf_nav_host is None
    viewer.deleteLater()


def test_view_conformers_omits_property_column_pickers(qapp) -> None:  # noqa: ARG001
    from rdkit.Chem import AllChem

    from molmanager.confs_codec import conformer_mol_blocks_b64_json
    from molmanager.ui.mol_viewer_3d import Molecule3DViewerWidget

    mol = Chem.MolFromSmiles("CCO")
    AllChem.EmbedMultipleConfs(mol, numConfs=2, randomSeed=0xC0FFEE)
    payload = conformer_mol_blocks_b64_json(mol)
    viewer = Molecule3DViewerWidget(
        mol,
        None,
        window_title="View Conformers",
        multi_conf_blocks_json_b64=payload,
    )
    assert viewer._prop_panel is None
    assert viewer._export_host is viewer._conf_nav_host
    assert viewer._btn_export_table is not None
    assert viewer._btn_export_table.parent() is viewer._conf_nav_host
    assert viewer._cb_superpose is not None
    assert viewer._cb_superpose.text() == "Superpose"
    assert viewer._strain_table is None
    assert viewer._conf_nav_host is not None
    assert viewer._cb_only_selected_confs is None
    from PyQt5.QtWidgets import QHBoxLayout

    assert isinstance(viewer._conf_nav_host.layout(), QHBoxLayout)
    assert viewer._btn_conf_back.parent() is viewer._conf_nav_host
    assert viewer._add_to_main_btn.parent() is viewer._conf_nav_host
    assert viewer.embedded_minimum_width() >= 1200
    assert not hasattr(viewer, "_toggle_options_btn")
    viewer.deleteLater()
