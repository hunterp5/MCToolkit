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

"""Crystal-ligand extraction and in-place RMSD for docking validation."""

from __future__ import annotations

from pathlib import Path

import pytest
from rdkit import Chem
from rdkit.Chem import AllChem
from rdkit.Geometry import Point3D

from mctoolkit.docking.redock_validation import (
    CRYSTAL_REF_PROP,
    CRYSTAL_RMSD_PROP,
    crystal_pose_rmsd,
    crystal_ref_label,
    prepare_crystal_ligand,
    split_holo_receptor,
    split_pdbqt_holo,
    stamp_crystal_ref,
    stamp_crystal_rmsd,
)

_HOLO_PDB = """\
ATOM      1  N   ALA A   1      11.104   6.134  10.000  1.00  0.00           N
ATOM      2  CA  ALA A   1      12.260   6.859  10.000  1.00  0.00           C
HETATM  100  O81 AXI A2000     -26.050  -1.540  -9.129  1.00 32.47           O
HETATM  101  C80 AXI A2000     -26.813  -2.112  -9.925  1.00 30.83           C
HETATM  201  O   HOH A2002     -11.000   1.000   0.000  1.00 30.00           O
END
"""

_HOLO_PDBQT = """\
ATOM      1  N   ALA A   1      11.104   6.134  10.000  1.00  0.00     0.000 N
ATOM      2  CA  ALA A   1      12.260   6.859  10.000  1.00  0.00     0.000 C
ROOT
ATOM      3  C   UNL     1     -26.813  -2.112  -9.925  1.00  0.00     0.000 C
ATOM      4  O   UNL     1     -26.050  -1.540  -9.129  1.00  0.00     0.000 OA
ENDROOT
TORSDOF 0
"""

_APO_PDBQT = """\
ATOM      1  N   ALA A   1      11.104   6.134  10.000  1.00  0.00     0.000 N
ATOM      2  CA  ALA A   1      12.260   6.859  10.000  1.00  0.00     0.000 C
"""


def _translated_ethanol(delta_x: float) -> tuple[Chem.Mol, Chem.Mol]:
    mol = Chem.AddHs(Chem.MolFromSmiles("CCO"))
    assert mol is not None
    AllChem.EmbedMolecule(mol, randomSeed=1)
    crystal = Chem.Mol(mol)
    pose = Chem.Mol(mol)
    conf = pose.GetConformer()
    for i in range(conf.GetNumAtoms()):
        point = conf.GetAtomPosition(i)
        conf.SetAtomPosition(i, Point3D(point.x + delta_x, point.y, point.z))
    return crystal, pose


def test_crystal_pose_rmsd_is_in_place_not_superposed():
    crystal, pose = _translated_ethanol(1.0)
    rmsd = crystal_pose_rmsd(crystal, pose)
    assert rmsd == pytest.approx(1.0, abs=1e-3)


def test_stamp_crystal_rmsd_on_top_pose():
    crystal, pose = _translated_ethanol(0.5)
    top = stamp_crystal_rmsd([pose], crystal)
    assert top == pytest.approx(0.5, abs=1e-3)
    assert pose.GetProp(CRYSTAL_RMSD_PROP) == "0.500"


def test_crystal_ref_label_prefers_pdb_residue():
    pdb = (
        "HETATM  100  C1  AXI A2000     -26.050  -1.540  -9.129  1.00 32.47           C\n"
        "HETATM  101  C2  AXI A2000     -25.050  -1.540  -9.129  1.00 32.47           C\n"
        "END\n"
    )
    mol = Chem.MolFromPDBBlock(pdb, removeHs=False, sanitize=False)
    assert mol is not None
    mol.SetProp("_Name", "ligand")
    assert crystal_ref_label(mol, "rec_ligand.sdf") == "AXI A 2000"


def test_crystal_ref_label_falls_back_to_name_then_file():
    mol = Chem.MolFromSmiles("CCO")
    assert mol is not None
    mol.SetProp("_Name", "ethanol")
    assert crystal_ref_label(mol, "rec_ligand.sdf") == "ethanol"
    bare = Chem.MolFromSmiles("CCO")
    assert crystal_ref_label(bare, "C:/tmp/rec_ligand.sdf") == "rec_ligand.sdf"
    assert crystal_ref_label(None, "") == ""


def test_stamp_crystal_ref_on_poses():
    mol = Chem.MolFromSmiles("CCO")
    assert mol is not None
    stamp_crystal_ref([mol], "AXI A 2000")
    assert mol.GetProp(CRYSTAL_REF_PROP) == "AXI A 2000"


def test_split_pdbqt_holo_keeps_protein_and_ligand():
    split = split_pdbqt_holo(_HOLO_PDBQT)
    assert split is not None
    apo, ligand = split
    assert "ROOT" not in apo
    assert "ALA" in apo
    assert "ROOT" in ligand
    assert "UNL" in ligand
    assert split_pdbqt_holo(_APO_PDBQT) is None


def test_split_holo_pdb_drops_water():
    split = split_holo_receptor(_HOLO_PDB, suffix=".pdb")
    assert split is not None
    apo, ligand, lig_suf = split
    assert lig_suf == ".pdb"
    assert "ALA" in apo
    assert "AXI" not in apo
    assert "HOH" not in ligand
    assert "AXI" in ligand


def test_prepare_crystal_ligand_from_holo_pdbqt(tmp_path):
    rec = tmp_path / "complex.pdbqt"
    rec.write_text(_HOLO_PDBQT, encoding="utf-8")
    dest = tmp_path / "split"
    prep = prepare_crystal_ligand(rec, dest)
    assert prep is not None
    assert prep.stripped_from_receptor is True
    apo = Path(prep.apo_receptor_path).read_text(encoding="utf-8")
    assert "ROOT" not in apo
    assert "ALA" in apo
    assert Path(prep.crystal_ligand_path).is_file()


def test_prepare_crystal_ligand_uses_sidecar_when_receptor_is_apo(tmp_path):
    rec = tmp_path / "rec.pdbqt"
    rec.write_text(_APO_PDBQT, encoding="utf-8")
    lig = tmp_path / "rec_ligand.sdf"
    mol = Chem.MolFromSmiles("CCO")
    assert mol is not None
    AllChem.EmbedMolecule(mol, randomSeed=1)
    from rdkit.Chem import SDWriter

    writer = SDWriter(str(lig))
    writer.write(mol)
    writer.close()
    dest = tmp_path / "split"
    prep = prepare_crystal_ligand(rec, dest, crystal_ligand_path=str(lig))
    assert prep is not None
    assert prep.stripped_from_receptor is False
    assert Path(prep.crystal_ligand_path).resolve() == lig.resolve()
    assert Path(prep.apo_receptor_path).resolve() == rec.resolve()


def test_prepare_crystal_ligand_skips_apo_without_sidecar(tmp_path):
    rec = tmp_path / "rec.pdbqt"
    rec.write_text(_APO_PDBQT, encoding="utf-8")
    assert prepare_crystal_ligand(rec, tmp_path / "split") is None
