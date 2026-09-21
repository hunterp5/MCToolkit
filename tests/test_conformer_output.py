# This file is part of mctoolkit.
# Copyright (C) 2026 Hunter Picard
#
# mctoolkit is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# mctoolkit is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with mctoolkit.  If not, see <https://www.gnu.org/licenses/>.

"""Conformer export helpers."""

from __future__ import annotations

from pathlib import Path

from rdkit import Chem

from mctoolkit.conformers.conformer_output import (
    iter_single_conformer_mols,
    write_conformer_results_to_sdf,
)
from mctoolkit.workers import ConformerGenParams, pack_confs_cell, run_conformer_generation


def test_iter_single_conformer_mols_splits_ensemble():
    mol = Chem.MolFromSmiles("CCO")
    params = ConformerGenParams(
        num_confs=3,
        energy_window_kcal=100.0,
        force_field="UFF",
        random_seed=11,
        max_iterations=80,
    )
    out, meta = run_conformer_generation(mol, params)
    assert out is not None
    assert meta.get("ok") is True
    singles = iter_single_conformer_mols(out)
    assert len(singles) == out.GetNumConformers()
    assert all(m.GetNumConformers() == 1 for m in singles)


def test_write_conformer_results_to_sdf(tmp_path: Path):
    mol = Chem.MolFromSmiles("C")
    params = ConformerGenParams.single_lowest_energy(
        force_field="UFF", random_seed=5, max_iterations=50
    )
    out, meta = run_conformer_generation(mol, params)
    assert out is not None
    cell = pack_confs_cell(meta, out)
    path = tmp_path / "out.sdf"
    n = write_conformer_results_to_sdf(path, [(1, out, cell)])
    assert n == 1
    suppl = Chem.SDMolSupplier(str(path))
    mols = [m for m in suppl if m is not None]
    assert len(mols) == 1
