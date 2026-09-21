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
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with MCToolkit. If not, see <https://www.gnu.org/licenses/>.

"""Vacuum GAFF/GAFF2 helpers for stochastic conformer generation."""

from __future__ import annotations

import pytest
from rdkit import Chem

from mctoolkit.workers.chemistry_worker_common import (
    is_gaff_force_field,
    normalize_force_field,
)
from mctoolkit.workers.conformer_gaff import map_coords_by_element
from mctoolkit.workers.protein_prepare_amber import ligand_only_leap_input


def test_normalize_force_field_gaff_aliases() -> None:
    assert normalize_force_field("GAFF2") == "GAFF2"
    assert normalize_force_field("gaff-2.11") == "GAFF2"
    assert normalize_force_field("gaff") == "GAFF"
    assert normalize_force_field("GAFF1") == "GAFF"
    assert normalize_force_field("MMFF") == "MMFF"
    assert is_gaff_force_field("GAFF2")
    assert is_gaff_force_field("gaff")
    assert not is_gaff_force_field("UFF")
    assert not is_gaff_force_field("MMFF94s")


def test_ligand_only_leap_input_gaff2() -> None:
    text = ligand_only_leap_input(
        mol2="lig0_gaff.mol2",
        frcmod="lig0.frcmod",
        ligand_ff="gaff2",
        prmtop="lig.prmtop",
        inpcrd="lig.inpcrd",
    )
    assert "source leaprc.gaff2" in text
    assert "loadamberparams lig0.frcmod" in text
    assert "LIG = loadMol2 lig0_gaff.mol2" in text
    assert "saveAmberParm LIG lig.prmtop lig.inpcrd" in text
    assert "loadPdb" not in text
    assert "combine" not in text


def test_ligand_only_leap_input_gaff() -> None:
    text = ligand_only_leap_input(
        mol2="a_gaff.mol2",
        frcmod="a.frcmod",
        ligand_ff="gaff",
        prmtop="p.prmtop",
        inpcrd="p.inpcrd",
    )
    assert "source leaprc.gaff\n" in text


def test_map_coords_by_element_identity() -> None:
    zs = [6, 8, 1, 1]
    xyz = [(0.0, 0.0, 0.0), (1.4, 0.0, 0.0), (-0.9, 0.0, 0.0), (0.4, 0.9, 0.0)]
    assert map_coords_by_element(zs, xyz, zs, xyz) == [0, 1, 2, 3]


def test_map_coords_by_element_reordered() -> None:
    src_z = [6, 8, 1]
    src_xyz = [(0.0, 0.0, 0.0), (1.4, 0.0, 0.0), (-0.9, 0.0, 0.0)]
    dest_z = [1, 6, 8]
    dest_xyz = [(-0.9, 0.0, 0.0), (0.0, 0.0, 0.0), (1.4, 0.0, 0.0)]
    assert map_coords_by_element(src_z, src_xyz, dest_z, dest_xyz) == [1, 2, 0]


def test_map_coords_by_element_count_mismatch() -> None:
    with pytest.raises(ValueError, match="atom count"):
        map_coords_by_element([6], [(0.0, 0.0, 0.0)], [6, 8], [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)])


def test_run_conformer_generation_gaff2_uses_gaff_minimizer(monkeypatch) -> None:
    from mctoolkit.workers import ConformerGenParams, run_conformer_generation

    def fake_opt(mol, force_field, max_iterations, cancel_event=None):
        assert normalize_force_field(force_field) == "GAFF2"
        assert mol.GetNumConformers() >= 1
        assert max_iterations >= 1
        n = mol.GetNumConformers()
        return [float(i) * 0.1 for i in range(n)], "GAFF2"

    monkeypatch.setattr(
        "mctoolkit.workers.conformer_gaff.optimize_conformer_energies_gaff", fake_opt
    )
    m = Chem.MolFromSmiles("CCO")
    p = ConformerGenParams(
        num_confs=3,
        energy_window_kcal=100.0,
        force_field="GAFF2",
        random_seed=7,
        max_iterations=50,
    )
    out, meta = run_conformer_generation(m, p)
    assert out is not None
    assert meta.get("ok") is True
    assert meta.get("ff") == "GAFF2"
    assert out.GetNumConformers() >= 1


def test_run_conformer_generation_gaff_requires_ambertools(monkeypatch) -> None:
    from mctoolkit.workers import ConformerGenParams, run_conformer_generation

    monkeypatch.setattr(
        "mctoolkit.workers.protein_prepare_amber.ambertools_available",
        lambda **_k: False,
    )
    m = Chem.MolFromSmiles("CCO")
    p = ConformerGenParams(
        num_confs=2,
        energy_window_kcal=100.0,
        force_field="GAFF",
        random_seed=1,
        max_iterations=20,
    )
    out, meta = run_conformer_generation(m, p)
    assert out is None
    assert meta.get("ok") is False
    err = meta.get("err") or ""
    assert "AmberTools" in err
