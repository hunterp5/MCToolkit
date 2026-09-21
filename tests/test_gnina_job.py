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

"""Gnina dock job policy without Qt."""

from __future__ import annotations

from pathlib import Path

import pytest

from mctoolkit.docking.gnina_job import (
    GninaJobSettings,
    build_cnn_argv,
    build_flex_argv,
    build_gnina_argv,
    build_minimize_argv,
    effective_out_path,
    flex_out_path,
    ligand_cli_args,
    ligand_mol_from_ensemble,
    normalize_flexres,
)


def test_ligand_cli_args_repeats_flag():
    args, first = ligand_cli_args(["a.pdbqt", "b.pdbqt"])
    assert args == ["--ligand", "a.pdbqt", "--ligand", "b.pdbqt"]
    assert first == "a.pdbqt"
    one, only = ligand_cli_args("lig.pdbqt")
    assert one == ["--ligand", "lig.pdbqt"]
    assert only == "lig.pdbqt"


def test_normalize_flexres_and_flex_out_path():
    assert normalize_flexres(" A:123 ; B:4A ") == "A:123,B:4A"
    assert flex_out_path("C:/tmp/rec_docked.sdf") == str(Path("C:/tmp/rec_docked_flex.pdb"))
    with pytest.raises(ValueError, match="CHAIN:RESNUM"):
        normalize_flexres("")


def test_build_gnina_argv_manual_box():
    settings = GninaJobSettings(
        receptor="rec.pdbqt",
        size_x=22.0,
        center_x=1.5,
        cnn_scoring="rescore",
        pose_sort="CNNscore",
        no_gpu=True,
    )
    argv = build_gnina_argv(settings, ligand="lig.sdf", out="out.sdf")
    assert "--autobox_ligand" not in argv
    assert argv[argv.index("--center_x") + 1] == "1.500"
    assert argv[argv.index("--size_x") + 1] == "22.00"
    assert argv[argv.index("--cnn_scoring") + 1] == "rescore"
    assert argv[argv.index("--pose_sort_order") + 1] == "CNNscore"
    assert "--no_gpu" in argv
    assert "--energy_range" not in argv


def test_build_cnn_argv_empirical_when_none():
    settings = GninaJobSettings(cnn_scoring="none", emp_scoring="vinardo")
    argv = build_cnn_argv(settings)
    assert argv[argv.index("--cnn_scoring") + 1] == "none"
    assert argv[argv.index("--scoring") + 1] == "vinardo"
    assert "--pose_sort_order" not in argv


def test_build_flex_argv_named_residues():
    settings = GninaJobSettings(flex_mode="res", flexres="A:123,A:145")
    argv = build_flex_argv(settings, dock_ligand="lig.sdf", out_path="out.sdf")
    assert argv[argv.index("--flexres") + 1] == "A:123,A:145"
    assert argv[argv.index("--out_flex") + 1] == flex_out_path("out.sdf")


def test_build_minimize_argv_omits_search_box():
    settings = GninaJobSettings(receptor="rec.pdbqt", no_gpu=True)
    argv = build_minimize_argv(settings, "pose.pdbqt", "min.pdbqt")
    assert "--minimize" in argv
    assert "--num_modes" not in argv
    assert "--exhaustiveness" not in argv
    assert argv[argv.index("--ligand") + 1] == "pose.pdbqt"


def test_effective_out_path_sdf_sibling():
    assert effective_out_path("out.pdbqt", save_sdf=True).endswith("out.sdf")
    assert effective_out_path("out.pdbqt", save_sdf=False).endswith("out.pdbqt")


def test_ligand_mol_from_ensemble_keeps_one_start():
    from rdkit import Chem
    from rdkit.Chem import AllChem

    mol = Chem.AddHs(Chem.MolFromSmiles("CCO"))
    AllChem.EmbedMultipleConfs(mol, 2, randomSeed=1)
    ligand = ligand_mol_from_ensemble(mol, 9)
    assert ligand is not None
    assert ligand.GetProp("_Name") == "9"
    assert ligand.GetProp("Parent OID") == "9"
    assert ligand.GetNumConformers() == 1
