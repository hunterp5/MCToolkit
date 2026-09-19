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

"""Ingest of 3D file structures: 2D Structure + packed confs for the viewer."""

from __future__ import annotations

from rdkit import Chem
from rdkit.Chem import AllChem

from molmanager.confs_codec import (
    mol_has_3d_coordinates,
    mol_from_packed_confs_cell,
    rehydrate_v1_confs_cell,
    resolve_blocks_b64_for_viewer,
)
from molmanager.ui.main_window import ChemistryWorkspaceWindow
from molmanager.ui.mol_viewer_3d import prepare_mol_2d


def _flat_ethanol():
    m = Chem.MolFromSmiles("CCO")
    AllChem.Compute2DCoords(m)
    return m


def _ethanol_3d():
    m = Chem.MolFromSmiles("CCO")
    AllChem.EmbedMolecule(m, randomSeed=0xBEEF)
    return m


def test_mol_has_3d_coordinates_detects_z():
    assert not mol_has_3d_coordinates(_flat_ethanol())
    assert mol_has_3d_coordinates(_ethanol_3d())
    assert not mol_has_3d_coordinates(Chem.MolFromSmiles("CCO"))  # no conformer


def test_ingest_store_mol_demotes_3d_to_confs(qapp):  # noqa: ARG001
    w = ChemistryWorkspaceWindow()
    w.headers = ["ID_HIDDEN", "Structure", "SMILES"]
    w._table_model.set_headers(list(w.headers))
    w.table.setColumnHidden(0, True)

    mol3d = _ethanol_3d()
    oid = w.next_oid
    w.next_oid += 1
    cells = w._ingest_store_mol(oid, mol3d)
    w._table_model.append_row(oid, cells)

    assert "confs" in w.headers
    assert "confs" in cells and cells["confs"]
    depict = w.mols[oid]
    assert depict is not None
    assert depict.GetNumConformers() == 1
    # Structure mol should be 2D (negligible Z), while packed confs keep 3D.
    assert not mol_has_3d_coordinates(depict)
    assert prepare_mol_2d(mol3d) is not None

    light = w._table_model.backing_value_for_row_header(0, "confs")
    sc = getattr(w, "_confs_blocks_sidecar", {})
    b64 = resolve_blocks_b64_for_viewer(light, "confs", oid, sc)
    assert b64 is not None
    packed = mol_from_packed_confs_cell(rehydrate_v1_confs_cell(light, "confs", oid, sc), min_conformers=1)
    assert packed is not None
    assert mol_has_3d_coordinates(packed)

    # Flat / no-coords mols do not create confs content.
    oid2 = w.next_oid
    w.next_oid += 1
    cells2 = w._ingest_store_mol(oid2, _flat_ethanol())
    assert not (cells2.get("confs") or "").strip()
    w.close()
