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

"""RMSD of conformers relative to a reference."""

from __future__ import annotations

from rdkit import Chem

from mctoolkit.workers import (
    ConformerGenParams,
    RmsdParams,
    run_conformer_generation,
    run_conformer_rmsd,
)


def test_run_conformer_rmsd_relative_to_reference():
    m = Chem.MolFromSmiles("CCO")
    out, meta = run_conformer_generation(
        m,
        ConformerGenParams(
            num_confs=5,
            energy_window_kcal=100.0,
            force_field="MMFF",
            random_seed=31,
            prune_rms_threshold=-1.0,
            max_iterations=80,
        ),
    )
    assert out is not None and meta.get("ok") is True
    assert out.GetNumConformers() >= 2

    row, rmeta = run_conformer_rmsd(out, RmsdParams(reference_conformer_index=0))
    assert row is not None and rmeta.get("ok") is True
    vals = [float(x) for x in row["RMSD_values"].split(";")]
    assert len(vals) == out.GetNumConformers()
    assert abs(vals[0]) < 1e-6
    assert float(row["RMSD_max"]) == max(vals)
    assert abs(float(row["RMSD_mean"]) - sum(vals) / len(vals)) < 1e-6


def test_run_conformer_rmsd_clamps_reference():
    m = Chem.MolFromSmiles("CCO")
    out, meta = run_conformer_generation(
        m,
        ConformerGenParams(
            num_confs=3,
            energy_window_kcal=100.0,
            force_field="UFF",
            random_seed=9,
            prune_rms_threshold=-1.0,
            max_iterations=60,
        ),
    )
    assert out is not None and meta.get("ok") is True
    row, rmeta = run_conformer_rmsd(
        out, RmsdParams(reference_conformer_index=999, heavy_atoms_only=True)
    )
    assert row is not None and rmeta.get("ok") is True
    assert rmeta.get("ref_clamped") is True
    vals = [float(x) for x in row["RMSD_values"].split(";")]
    assert abs(vals[-1]) < 1e-6
