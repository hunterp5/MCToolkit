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

"""Sidecar storage for conformer table cells (lightweight cells + in-memory blocks)."""

from rdkit import Chem
from rdkit.Chem import AllChem

from molmanager.conformers.conformer_column_codec import (
    demote_v1_cell_to_sidecar,
    deserialize_confs_sidecar,
    mol_from_packed_confs_cell,
    pack_confs_cell,
    rehydrate_v1_confs_cell,
    resolve_blocks_b64_for_viewer,
    serialize_confs_sidecar,
    unpack_confs_blocks_json_b64,
)
from molmanager.workers import ConformerGenParams, run_conformer_generation


def _simple_mol():
    m = Chem.MolFromSmiles("CCO")
    AllChem.EmbedMolecule(m, randomSeed=0xF00D)
    return m


def test_demote_then_resolve_and_rehydrate_roundtrip():
    p = ConformerGenParams(
        num_confs=4,
        energy_window_kcal=100.0,
        force_field="UFF",
        random_seed=2,
        max_iterations=40,
    )
    m0 = _simple_mol()
    out, meta = run_conformer_generation(Chem.Mol(m0), p)
    assert out is not None and out.GetNumConformers() >= 2
    packed = pack_confs_cell(meta, out)
    assert unpack_confs_blocks_json_b64(packed) is not None

    light, b64 = demote_v1_cell_to_sidecar(packed, "confs")
    assert b64 is not None and b64 == unpack_confs_blocks_json_b64(packed)
    assert len(light) < len(packed) // 2
    assert unpack_confs_blocks_json_b64(light) is None

    oid = 42
    store = {(oid, "confs"): b64}
    assert resolve_blocks_b64_for_viewer(light, "confs", oid, store) == b64
    assert resolve_blocks_b64_for_viewer(light, "superpose", oid, store) is None

    full = rehydrate_v1_confs_cell(light, "confs", oid, store)
    assert unpack_confs_blocks_json_b64(full) == b64
    mol2 = mol_from_packed_confs_cell(full)
    assert mol2 is not None
    assert mol2.GetNumConformers() == out.GetNumConformers()


def test_serialize_deserialize_sidecar_roundtrip():
    store = {(1, "confs"): "YWFh", (2, "superpose"): "YmJi"}
    raw = serialize_confs_sidecar(store)
    back = deserialize_confs_sidecar(raw)
    assert back == store


def test_serialize_ensemble_store_is_empty_json_map():
    from molmanager.storage import EnsembleStore

    store = EnsembleStore()
    try:
        store[(1, "confs")] = "YWFh"
        assert serialize_confs_sidecar(store) == {}
    finally:
        store.close()


def test_pack_confs_cell_unlimited_when_max_chars_zero():
    from rdkit.Geometry import Point3D

    from molmanager.conformers.conformer_column_codec import (
        CONFS_CELL_PACK_MAX_CHARS,
        format_confs_table_cell,
    )

    mol = Chem.MolFromSmiles("CCO")
    for i in range(6):
        conf = Chem.Conformer(mol.GetNumAtoms())
        conf.SetAtomPosition(0, Point3D(float(i), 0.0, 0.0))
        conf.SetAtomPosition(1, Point3D(float(i) + 1.4, 0.0, 0.0))
        conf.SetAtomPosition(2, Point3D(float(i) + 2.0, 1.1, 0.0))
        mol.AddConformer(conf, assignId=True)
    meta = {"ok": True, "n_kept": 6, "n_packed": 6}
    packed = pack_confs_cell(meta, mol, max_chars=0)
    assert CONFS_CELL_PACK_MAX_CHARS == 0
    assert unpack_confs_blocks_json_b64(packed) is not None
    assert mol_from_packed_confs_cell(packed, min_conformers=6) is not None
    tiny = pack_confs_cell(meta, mol, max_chars=40)
    assert unpack_confs_blocks_json_b64(tiny) is None
    assert tiny == format_confs_table_cell(meta)
