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

"""Export conformers from the multi-conf 3D viewer into table rows."""

from __future__ import annotations

from rdkit import Chem
from rdkit.Chem import AllChem

from molmanager.conformers.conformer_column_codec import (
    conformer_mol_blocks_b64_json,
    mol_from_packed_confs_cell,
    rehydrate_v1_confs_cell,
    resolve_blocks_b64_for_viewer,
)
from molmanager.ui.main_window import ChemistryWorkspaceWindow


def _two_conf_ethanol():
    m = Chem.MolFromSmiles("CCO")
    AllChem.EmbedMultipleConfs(m, numConfs=2, randomSeed=0xC0FFEE)
    return m


def test_export_conformer_viewer_to_table_writes_2d_structure_and_confs(qapp):  # noqa: ARG001
    w = ChemistryWorkspaceWindow()
    mol = _two_conf_ethanol()
    blocks = conformer_mol_blocks_b64_json(mol)
    overlay = {
        "energies": [12.5, 14.0],
        "deltas": [0.0, 1.5],
        "rmsds": [0.0, 0.42],
        "e_ref": 12.5,
        "ref_idx": 0,
    }

    n = w.export_conformer_viewer_to_table(
        blocks_json_b64=blocks,
        conf_indices=[1],
        strain_overlay=overlay,
        parent_oid=99,
        confs_column="confs",
    )
    assert n == 1
    assert "confs" in w.headers
    assert "E_kcal" in w.headers
    assert "(delta)E_kcal" in w.headers
    assert "RMSD" in w.headers

    oid = int(w._table_model.cell_text(0, 0))
    assert oid in w.mols
    assert w.mols[oid].GetNumConformers() == 1
    # 2D depiction should not carry the original 3D Z variance of conf 1 alone as a failure —
    # just ensure render mol exists and SMILES is set.
    assert "SMILES" in w.headers
    smi = w._table_model.backing_value_for_row_header(0, "SMILES")
    assert smi.startswith("C")

    assert w._table_model.backing_value_for_row_header(0, "Parent OID") == "99"
    assert w._table_model.backing_value_for_row_header(0, "Conformer") == "2"
    assert w._table_model.backing_value_for_row_header(0, "E_kcal") == "14"
    assert w._table_model.backing_value_for_row_header(0, "(delta)E_kcal") == "1.5"
    assert float(w._table_model.backing_value_for_row_header(0, "RMSD")) == 0.42

    light = w._table_model.backing_value_for_row_header(0, "confs")
    sc = getattr(w, "_confs_blocks_sidecar", {})
    b64 = resolve_blocks_b64_for_viewer(light, "confs", oid, sc)
    assert b64 is not None
    full = rehydrate_v1_confs_cell(light, "confs", oid, sc)
    packed_mol = mol_from_packed_confs_cell(full, min_conformers=1)
    assert packed_mol is not None
    assert packed_mol.GetNumConformers() == 1

    n_all = w.export_conformer_viewer_to_table(
        blocks_json_b64=blocks,
        conf_indices=None,
        strain_overlay=overlay,
        parent_oid=99,
        confs_column="confs",
    )
    assert n_all == 2
    w.close()
