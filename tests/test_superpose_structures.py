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

"""Superpose distinct table structures (MCS / pattern / O3A)."""

from __future__ import annotations

from rdkit import Chem
from rdkit.Chem import AllChem

from molmanager.workers import (
    SuperposeStructuresParams,
    align_structure_onto_reference,
    run_superpose_structures,
)


def _embed(smi: str, seed: int) -> Chem.Mol:
    m = Chem.MolFromSmiles(smi)
    mh = Chem.AddHs(m)
    assert AllChem.EmbedMolecule(mh, randomSeed=seed) == 0
    try:
        AllChem.UFFOptimizeMolecule(mh, maxIters=80)
    except Exception:
        pass
    return mh


def test_align_related_structures_mcs():
    ref = _embed("c1ccccc1C", seed=1)
    prb = _embed("c1ccccc1CC", seed=2)
    # Rotate probe so it is not already aligned.
    conf = prb.GetConformer()
    for i in range(prb.GetNumAtoms()):
        p = conf.GetAtomPosition(i)
        conf.SetAtomPosition(i, (p.x + 3.0, p.y - 1.5, p.z + 2.0))
    aligned, meta = align_structure_onto_reference(
        prb,
        ref,
        SuperposeStructuresParams(use_mcs=True, heavy_atoms_only=True),
    )
    assert aligned is not None
    assert meta.get("ok") is True
    assert meta.get("method") in {"mcs", "crippen_o3a", "mmff_o3a", "pattern"}
    assert float(meta.get("rms", 99)) < 2.5


def test_align_pattern_then_fallback():
    ref = _embed("CCO", seed=3)
    prb = _embed("CCO", seed=4)
    aligned, meta = align_structure_onto_reference(
        prb,
        ref,
        SuperposeStructuresParams(
            align_pattern="CCO",
            align_pattern_is_smarts=False,
            use_mcs=True,
        ),
    )
    assert aligned is not None
    assert meta.get("ok") is True
    assert meta.get("method") == "pattern"


def test_run_superpose_structures_batch():
    a = _embed("c1ccccc1", seed=5)
    b = _embed("c1ccccc1O", seed=6)
    c = _embed("c1ccccc1N", seed=7)
    out = run_superpose_structures(
        a,
        [(1, a), (2, b), (3, c)],
        SuperposeStructuresParams(use_mcs=True),
        ref_oid=1,
    )
    assert len(out) == 3
    assert out[0][2].get("method") == "reference"
    assert out[0][1] is not None
    assert sum(1 for _o, m, meta in out if m is not None and meta.get("ok")) >= 2


def test_align_no_map_no_o3a_fails():
    ref = _embed("CCO", seed=1)
    prb = _embed("c1ccccc1", seed=2)
    aligned, meta = align_structure_onto_reference(
        prb,
        ref,
        SuperposeStructuresParams(use_mcs=False, use_o3a=False, align_pattern=""),
    )
    assert aligned is None
    assert meta.get("err") == "no_common_substructure"


def test_align_2d_topological_mcs():
    from rdkit.Chem import rdDepictor

    ref = Chem.MolFromSmiles("c1ccccc1C")
    prb = Chem.MolFromSmiles("c1ccccc1CC")
    rdDepictor.Compute2DCoords(ref)
    rdDepictor.Compute2DCoords(prb)
    aligned, meta = align_structure_onto_reference(
        prb,
        ref,
        SuperposeStructuresParams(geometry="2d", use_mcs=True, use_o3a=False),
    )
    assert aligned is not None
    assert meta.get("ok") is True
    assert meta.get("geometry") == "2d"
    assert meta.get("method") in {"mcs", "pattern", "2d_match"}
    assert float(meta.get("rms", 99)) < 0.5


def test_run_superpose_structures_2d_batch():
    from rdkit.Chem import rdDepictor

    a = Chem.MolFromSmiles("c1ccccc1")
    b = Chem.MolFromSmiles("c1ccccc1O")
    c = Chem.MolFromSmiles("c1ccccc1N")
    for m in (a, b, c):
        rdDepictor.Compute2DCoords(m)
    out = run_superpose_structures(
        a,
        [(1, a), (2, b), (3, c)],
        SuperposeStructuresParams(geometry="2d", use_mcs=True, use_o3a=False),
        ref_oid=1,
    )
    assert len(out) == 3
    assert out[0][2].get("method") == "reference"
    assert out[0][2].get("geometry") == "2d"
    assert sum(1 for _o, m, meta in out if m is not None and meta.get("ok")) >= 2


def test_pack_mols_as_confs_cell_same_and_mixed_atom_counts():
    from molmanager.conformers.conformer_column_codec import (
        mol_from_packed_confs_cell,
        pack_mols_as_confs_cell,
        unpack_confs_blocks_json_b64,
    )

    a = _embed("CCO", seed=8)
    b = _embed("CCO", seed=9)
    same = pack_mols_as_confs_cell({"ok": True, "op": "superpose_structures"}, [a, b])
    assert unpack_confs_blocks_json_b64(same) is not None
    merged = mol_from_packed_confs_cell(same, min_conformers=2)
    assert merged is not None and merged.GetNumConformers() == 2

    c = _embed("c1ccccc1", seed=10)
    mixed = pack_mols_as_confs_cell({"ok": True, "op": "superpose_structures"}, [a, c])
    assert unpack_confs_blocks_json_b64(mixed) is not None
    # Heterogeneous atom counts: viewer blocks present, multi-conf rebuild may fail.
    assert mol_from_packed_confs_cell(mixed, min_conformers=2) is None


def test_align_largest_ring_naphthalene():
    ref = _embed("c1ccc2ccccc2c1", seed=11)
    prb = _embed("Cc1ccc2ccccc2c1", seed=12)
    conf = prb.GetConformer()
    for i in range(prb.GetNumAtoms()):
        p = conf.GetAtomPosition(i)
        conf.SetAtomPosition(i, (p.x + 4.0, p.y - 2.0, p.z + 1.5))
    aligned, meta = align_structure_onto_reference(
        prb,
        ref,
        SuperposeStructuresParams(
            align_mode="largest_ring",
            use_mcs=False,
            use_o3a=False,
            heavy_atoms_only=True,
        ),
    )
    assert aligned is not None
    assert meta.get("ok") is True
    assert meta.get("method") == "largest_ring"
    assert meta.get("align_mode") == "largest_ring"
    assert int(meta.get("n_align_atoms") or 0) == 10
    assert float(meta.get("rms", 99)) < 1.5


def test_align_no_ring_for_alignment():
    ref = _embed("CCO", seed=13)
    prb = _embed("CCO", seed=14)
    aligned, meta = align_structure_onto_reference(
        prb,
        ref,
        SuperposeStructuresParams(
            align_mode="largest_ring",
            use_mcs=False,
            use_o3a=False,
        ),
    )
    assert aligned is None
    assert meta.get("err") == "no_ring_for_alignment"
