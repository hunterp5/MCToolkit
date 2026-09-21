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

"""Superpose conformers (RDKit rdMolAlign) and packed-cell decode."""

from __future__ import annotations

import base64
import json

from rdkit import Chem

from mctoolkit.conformers.conformer_column_codec import (
    mol_from_packed_confs_cell,
    pack_confs_cell,
    unpack_confs_blocks_json_b64,
)
from mctoolkit.workers import (
    ConformerGenParams,
    run_conformer_generation,
    run_superpose_conformers,
    SuperposeParams,
)


def test_mol_from_packed_roundtrip():
    m = Chem.MolFromSmiles("CCO")
    out, meta = run_conformer_generation(
        m,
        ConformerGenParams(
            num_confs=4,
            energy_window_kcal=100.0,
            force_field="MMFF",
            random_seed=11,
            prune_rms_threshold=-1.0,
            max_iterations=80,
        ),
    )
    assert out is not None and meta.get("ok") is True
    packed = pack_confs_cell(meta, out)
    assert unpack_confs_blocks_json_b64(packed) is not None
    mol2 = mol_from_packed_confs_cell(packed)
    assert mol2 is not None
    assert mol2.GetNumConformers() == out.GetNumConformers()


def test_run_superpose_conformers_ethanol():
    m = Chem.MolFromSmiles("CCO")
    out, meta = run_conformer_generation(
        m,
        ConformerGenParams(
            num_confs=5,
            energy_window_kcal=100.0,
            force_field="MMFF",
            random_seed=3,
            max_iterations=60,
        ),
    )
    assert out is not None
    sp, smeta = run_superpose_conformers(out, SuperposeParams(reference_conformer_index=0))
    assert sp is not None
    assert smeta.get("ok") is True
    assert smeta.get("n_conf", 0) >= 2
    assert smeta.get("rms_max", 1.0) < 0.01


def test_superpose_substructure_smarts():
    m = Chem.MolFromSmiles("CCC")
    out, meta = run_conformer_generation(
        m,
        ConformerGenParams(
            num_confs=4,
            energy_window_kcal=100.0,
            force_field="MMFF",
            random_seed=2,
            max_iterations=60,
        ),
    )
    assert out is not None
    sp, smeta = run_superpose_conformers(
        out,
        SuperposeParams(
            reference_conformer_index=0,
            align_pattern="[#6]-[#6]",
            align_pattern_is_smarts=True,
            heavy_atoms_only=True,
        ),
    )
    assert sp is not None
    assert smeta.get("ok") is True
    assert smeta.get("n_align_atoms", 0) >= 2


def test_run_superpose_conformers_2d_ethanol():
    m = Chem.MolFromSmiles("CCO")
    out, meta = run_conformer_generation(
        m,
        ConformerGenParams(
            num_confs=4,
            energy_window_kcal=100.0,
            force_field="MMFF",
            random_seed=3,
            max_iterations=60,
        ),
    )
    assert out is not None
    sp, smeta = run_superpose_conformers(
        out, SuperposeParams(reference_conformer_index=0, geometry="2d")
    )
    assert sp is not None
    assert smeta.get("ok") is True
    assert smeta.get("geometry") == "2d"
    assert smeta.get("n_conf", 0) >= 2


def test_superpose_invalid_pattern():
    m = Chem.MolFromSmiles("CCO")
    out, meta = run_conformer_generation(
        m,
        ConformerGenParams(
            num_confs=3,
            energy_window_kcal=100.0,
            force_field="UFF",
            random_seed=1,
            max_iterations=40,
        ),
    )
    assert out is not None
    sp, smeta = run_superpose_conformers(
        out,
        SuperposeParams(align_pattern="[[[notsmarts", align_pattern_is_smarts=True),
    )
    assert sp is None
    assert smeta.get("err") == "invalid_align_pattern"


def test_superpose_packed_cell_meta():
    m = Chem.MolFromSmiles("CC")
    out, meta = run_conformer_generation(
        m,
        ConformerGenParams(
            num_confs=3,
            energy_window_kcal=50.0,
            force_field="UFF",
            random_seed=1,
            max_iterations=40,
        ),
    )
    assert out is not None
    sp, smeta = run_superpose_conformers(out, SuperposeParams(heavy_atoms_only=True, reflect=False))
    cell = pack_confs_cell(smeta, sp)
    d = json.loads(cell)
    assert d.get("v") == 1
    inner_m = d.get("m") or {}
    assert inner_m.get("op") == "superpose"
    b64 = unpack_confs_blocks_json_b64(cell)
    blocks = json.loads(base64.b64decode(b64.encode("ascii")))
    assert len(blocks) >= 2


def test_largest_vs_central_ring_atoms():
    from mctoolkit.workers.superpose import (
        _central_ring_atoms,
        _largest_ring_system_atoms,
    )

    naph = Chem.MolFromSmiles("c1ccc2ccccc2c1")
    largest = _largest_ring_system_atoms(naph, heavy_only=True)
    assert largest is not None
    assert len(largest) == 10

    bip = Chem.MolFromSmiles("c1ccccc1c2ccc(CCCCCCCC)cc2")
    central = _central_ring_atoms(bip, heavy_only=True)
    assert central is not None
    assert len(central) == 6
    ring_set = set(central)
    assert any(
        nbr.GetAtomicNum() == 6 and not nbr.GetIsAromatic() and nbr.GetIdx() not in ring_set
        for i in central
        for nbr in bip.GetAtomWithIdx(i).GetNeighbors()
    )


def test_superpose_largest_ring_naphthalene():
    m = Chem.MolFromSmiles("c1ccc2ccccc2c1")
    out, meta = run_conformer_generation(
        m,
        ConformerGenParams(
            num_confs=4,
            energy_window_kcal=100.0,
            force_field="MMFF",
            random_seed=7,
            max_iterations=80,
        ),
    )
    assert out is not None and meta.get("ok") is True
    sp, smeta = run_superpose_conformers(
        out,
        SuperposeParams(align_mode="largest_ring", heavy_atoms_only=True),
    )
    assert sp is not None
    assert smeta.get("ok") is True
    assert smeta.get("align_mode") == "largest_ring"
    assert smeta.get("n_align_atoms") == 10


def test_superpose_no_ring_for_alignment():
    m = Chem.MolFromSmiles("CCO")
    out, meta = run_conformer_generation(
        m,
        ConformerGenParams(
            num_confs=3,
            energy_window_kcal=100.0,
            force_field="UFF",
            random_seed=1,
            max_iterations=40,
        ),
    )
    assert out is not None
    sp, smeta = run_superpose_conformers(out, SuperposeParams(align_mode="largest_ring"))
    assert sp is None
    assert smeta.get("err") == "no_ring_for_alignment"
