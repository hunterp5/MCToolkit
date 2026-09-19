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

"""Ligand hydrogen preparation before Meeko PDBQT conversion."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("rdkit")
pytest.importorskip("PyQt5.QtWidgets")

from rdkit import Chem
from rdkit.Chem import AllChem

from molmanager.ui.dialogs.pdbqt_generator import PdbqtGeneratorDialog
from molmanager.workers.pdbqt_generator import (
    PdbqtGenRequest,
    _ligand_mols_from_request,
    _meeko_failed_residue_key,
    _meeko_residue_keys,
    _pdb_without_hydrogens,
    _read_pdb_molecules,
    _strip_pdb_residue,
    _write_receptor_pdbqt_file,
    meeko_import_error,
    prepare_ligand_with_hydrogens,
)


def test_prepare_ligand_with_hydrogens_adds_explicit_h_to_smiles():
    mol = Chem.MolFromSmiles("c1ccccc1")
    assert mol is not None
    assert mol.GetNumAtoms() == 6

    prepared = prepare_ligand_with_hydrogens(mol)
    assert prepared is not None
    assert prepared.GetNumAtoms() > mol.GetNumAtoms()
    assert prepared.GetNumConformers() >= 1
    assert any(atom.GetAtomicNum() == 1 for atom in prepared.GetAtoms())


def test_prepare_ligand_with_hydrogens_keeps_existing_3d_coords():
    mol = Chem.MolFromSmiles("CCO")
    assert mol is not None
    mol = Chem.AddHs(mol)

    assert AllChem.EmbedMolecule(mol, AllChem.ETKDG()) == 0
    n_heavy = mol.GetNumHeavyAtoms()

    prepared = prepare_ligand_with_hydrogens(mol)
    assert prepared is not None
    assert prepared.GetNumHeavyAtoms() == n_heavy
    assert prepared.GetNumAtoms() > n_heavy
    assert prepared.GetNumConformers() >= 1


def test_meeko_rdkit_compat_adds_mol_has_query():
    from molmanager.workers.pdbqt_generator import _apply_meeko_rdkit_compat

    _apply_meeko_rdkit_compat()
    mol = Chem.MolFromSmiles("c1ccccc1")
    assert mol is not None
    assert hasattr(mol, "HasQuery")
    assert mol.HasQuery() is False


def test_write_ligand_pdbqt_file(tmp_path):
    pytest.importorskip("meeko")
    from molmanager.workers.pdbqt_generator import (
        _write_ligand_pdbqt_file,
        prepare_ligand_with_hydrogens,
    )

    mol = Chem.MolFromSmiles("CCO")
    prepared = prepare_ligand_with_hydrogens(mol)
    assert prepared is not None
    out = tmp_path / "ligand.pdbqt"
    err = _write_ligand_pdbqt_file([prepared], out)
    assert err is None
    assert out.stat().st_size > 0


_ETHANOL_PDB = """\
HETATM    1  C1  UNL     1       1.187  -0.343   0.019  1.00  0.00           C
HETATM    2  C2  UNL     1       0.000   0.597   0.000  1.00  0.00           C
HETATM    3  O1  UNL     1      -1.186  -0.247   0.000  1.00  0.00           O
END
"""


def test_read_pdb_molecules(tmp_path):
    path = tmp_path / "lig.pdb"
    path.write_text(_ETHANOL_PDB, encoding="utf-8")
    mols = _read_pdb_molecules(path)
    assert len(mols) == 1
    assert mols[0].GetNumAtoms() >= 3


def test_ligand_mols_from_pdb_request(tmp_path):
    path = tmp_path / "lig.pdb"
    path.write_text(_ETHANOL_PDB, encoding="utf-8")
    req = PdbqtGenRequest(
        receptor_pdb_path=None,
        receptor_pdbqt_out=None,
        ligand_mode="pdb",
        ligand_sdf_path=None,
        ligand_smiles=None,
        ligand_rows=None,
        ligand_pdbqt_out=str(tmp_path / "out.pdbqt"),
        ligand_pdb_path=str(path),
    )
    mols, err = _ligand_mols_from_request(req)
    assert err == ""
    assert mols is not None
    assert mols[0].GetNumAtoms() >= 3


def test_pdbqt_dialog_pdb_mode_is_compact(qapp):  # noqa: ARG001
    dlg = PdbqtGeneratorDialog()
    assert dlg.lig_mode.count() == 4
    pdb_idx = dlg.lig_mode.findData("pdb")
    assert pdb_idx >= 0
    dlg.lig_mode.setCurrentIndex(pdb_idx)
    assert dlg.ligand_mode_key() == "pdb"
    assert dlg._lig_stack.currentIndex() == 0
    assert "pdb" in (dlg.edit_lig_file.placeholderText() or "").lower()
    smiles_idx = dlg.lig_mode.findData("smiles")
    dlg.lig_mode.setCurrentIndex(smiles_idx)
    assert dlg._lig_stack.currentIndex() == 1
    assert dlg.btn_rec_run.text() == "Generate PDBQT"
    assert dlg.btn_lig_run.text() == "Generate PDBQT"
    dlg.close()


# Two complete residues plus a truncated C-terminus like PDBFixer leaves on 4AGC.
_RECEPTOR_PDB = """\
ATOM      1  N   TYR A 801     -26.824 -13.866  -9.244  1.00 70.28           N
ATOM      2  CA  TYR A 801     -26.010 -13.311  -8.124  1.00 69.77           C
ATOM      3  C   TYR A 801     -26.386 -11.863  -7.822  1.00 68.54           C
ATOM      4  O   TYR A 801     -25.967 -10.940  -8.520  1.00 68.27           O
ATOM      5  CB  TYR A 801     -24.521 -13.380  -8.463  1.00 72.00           C
ATOM      6  CG  TYR A 801     -23.633 -12.870  -7.352  1.00 74.89           C
ATOM      7  CD1 TYR A 801     -23.343 -11.515  -7.232  1.00 75.97           C
ATOM      8  CD2 TYR A 801     -23.102 -13.740  -6.406  1.00 76.32           C
ATOM      9  CE1 TYR A 801     -22.552 -11.040  -6.201  1.00 77.75           C
ATOM     10  CE2 TYR A 801     -22.310 -13.277  -5.371  1.00 77.75           C
ATOM     11  CZ  TYR A 801     -22.038 -11.926  -5.274  1.00 78.54           C
ATOM     12  OH  TYR A 801     -21.250 -11.462  -4.246  1.00 80.29           O
ATOM     13  HA  TYR A 801     -26.192 -13.911  -7.232  1.00  0.00           H
ATOM     14  HB2 TYR A 801     -24.341 -12.779  -9.354  1.00  0.00           H
ATOM     15  HB3 TYR A 801     -24.257 -14.415  -8.678  1.00  0.00           H
ATOM     16  HD1 TYR A 801     -23.743 -10.821  -7.957  1.00  0.00           H
ATOM     17  HD2 TYR A 801     -23.312 -14.797  -6.481  1.00  0.00           H
ATOM     18  HE1 TYR A 801     -22.338  -9.984  -6.121  1.00  0.00           H
ATOM     19  HE2 TYR A 801     -21.907 -13.967  -4.644  1.00  0.00           H
ATOM     20  HH  TYR A 801     -20.384 -11.873  -4.296  1.00  0.00           H
ATOM     21  H   TYR A 801     -26.934 -13.338 -10.098  1.00  0.00           H
ATOM     22  N   LEU A 802     -27.175 -11.672  -6.774  1.00 66.27           N
ATOM     23  CA  LEU A 802     -27.555 -10.337  -6.344  1.00 64.77           C
ATOM     24  C   LEU A 802     -27.353 -10.197  -4.841  1.00 62.03           C
ATOM     25  O   LEU A 802     -27.815 -11.028  -4.064  1.00 61.70           O
ATOM     26  CB  LEU A 802     -29.016 -10.060  -6.707  1.00 66.82           C
ATOM     27  CG  LEU A 802     -29.995 -11.238  -6.810  1.00 69.10           C
ATOM     28  CD1 LEU A 802     -29.748 -11.990  -8.108  1.00 70.00           C
ATOM     29  CD2 LEU A 802     -29.852 -12.163  -5.606  1.00 69.43           C
ATOM     30  H   LEU A 802     -27.520 -12.472  -6.263  1.00  0.00           H
ATOM     31  HA  LEU A 802     -26.922  -9.610  -6.853  1.00  0.00           H
ATOM     32  HB2 LEU A 802     -29.015  -9.561  -7.676  1.00  0.00           H
ATOM     33  HB3 LEU A 802     -29.414  -9.360  -5.972  1.00  0.00           H
ATOM     34  HG  LEU A 802     -31.011 -10.844  -6.826  1.00  0.00           H
ATOM     35 HD11 LEU A 802     -30.693 -12.127  -8.635  1.00  0.00           H
ATOM     36 HD12 LEU A 802     -29.063 -11.418  -8.734  1.00  0.00           H
ATOM     37 HD13 LEU A 802     -29.311 -12.964  -7.886  1.00  0.00           H
ATOM     38 HD21 LEU A 802     -30.567 -12.982  -5.689  1.00  0.00           H
ATOM     39 HD22 LEU A 802     -28.840 -12.567  -5.576  1.00  0.00           H
ATOM     40 HD23 LEU A 802     -30.046 -11.602  -4.692  1.00  0.00           H
ATOM     41  N   GLN A1169     -15.761  23.268   9.328  1.00 72.96           N
ATOM     42  H1  GLN A1169     -16.435  22.616   8.952  1.00  0.00           H
ATOM     43  H2  GLN A1169     -16.067  24.021   9.928  1.00  0.00           H
TER      44      GLN A1169
END
"""


def test_write_receptor_pdbqt_skips_incomplete_residue(tmp_path):
    pytest.importorskip("meeko")
    src = tmp_path / "rec.pdb"
    src.write_text(_RECEPTOR_PDB, encoding="utf-8")
    out = tmp_path / "rec.pdbqt"
    err, ignored = _write_receptor_pdbqt_file(src, out)
    assert err is None
    assert any("1169" in item for item in ignored)
    text = out.read_text(encoding="utf-8")
    assert "ATOM" in text
    assert "TYR" in text or "TYR A" in text


def test_meeko_import_error_points_at_gemmi():
    err = meeko_import_error(ModuleNotFoundError("No module named 'gemmi'", name="gemmi"))
    assert "gemmi" in err.lower()
    assert "pip install gemmi" in err
    err = meeko_import_error(ModuleNotFoundError("No module named 'meeko'", name="meeko"))
    assert "pip install meeko" in err


def test_write_receptor_pdbqt_missing_file(tmp_path):
    pytest.importorskip("meeko")
    missing = tmp_path / "nope.pdb"
    out = tmp_path / "rec.pdbqt"
    err, ignored = _write_receptor_pdbqt_file(missing, out)
    assert err is not None
    assert "not found" in err.lower()
    assert ignored == []


def test_write_receptor_pdbqt_4agc_sample(tmp_path):
    pytest.importorskip("meeko")
    src = Path(__file__).resolve().parents[1] / "samples" / "4AGC_prepared_noligand.pdb"
    if not src.is_file():
        pytest.skip("4AGC_prepared_noligand.pdb sample missing")
    out = tmp_path / "4AGC_prepared_noligand.pdbqt"
    err, ignored = _write_receptor_pdbqt_file(src, out)
    assert err is None
    assert any("1169" in item for item in ignored)
    assert out.stat().st_size > 1000


def test_pdb_without_hydrogens_drops_h_records():
    pdb = (
        "ATOM      1  N   GLU A 913      -3.578  23.811 -24.665  1.00  0.00           N\n"
        "ATOM      2  CA  GLU A 913      -4.175  22.755 -25.605  1.00  0.00           C\n"
        "ATOM      3  HA  GLU A 913      -3.906  23.245 -26.671  1.00  0.00           H\n"
        "ATOM      4  H   GLU A 913      -3.189  24.664 -24.974  1.00  0.00           H\n"
        "TER\n"
    )
    out = _pdb_without_hydrogens(pdb)
    kept = [ln for ln in out.splitlines() if ln.startswith("ATOM")]
    assert len(kept) == 2
    assert all((ln[76:78].strip() if len(ln) >= 78 else "") not in {"H", "D", "T"} for ln in kept)
    assert "N   GLU" in out
    assert "CA  GLU" in out


def test_meeko_failed_residue_key_and_strip():
    msg = "unable to build rdkit mol for residue GLU corresponding to key A:913"
    assert _meeko_failed_residue_key(msg) == "A:913"
    assert _meeko_residue_keys(
        "adjacent_mol doesn't contain the mapped atoms",
        "matched with excess inter-residue bond(s): A:914\n"
        "matched with excess inter-residue bond(s): A:946",
    ) == ["A:914", "A:946"]
    pdb = (
        "ATOM      1  N   TYR A 912      -1.000   0.000   0.000  1.00  0.00           N\n"
        "ATOM      2  N   GLU A 913      -3.578  23.811 -24.665  1.00  0.00           N\n"
        "ATOM      3  CA  GLU A 913      -4.175  22.755 -25.605  1.00  0.00           C\n"
        "ATOM      4  N   LEU A 913A     -5.000   0.000   0.000  1.00  0.00           N\n"
        "TER\n"
    )
    stripped, n_drop = _strip_pdb_residue(pdb, "A:913")
    assert n_drop == 2
    assert "GLU A 913" not in stripped
    assert "TYR A 912" in stripped
    assert "LEU A 913A" in stripped


def test_write_receptor_pdbqt_protonated_glu_slice(tmp_path):
    pytest.importorskip("meeko")
    from molmanager.protein.structure_atoms import _pdb_from_atoms, parse_structure_atoms

    src = Path(__file__).resolve().parents[1] / "samples" / "6bbu_fixed_protonated.cif"
    if not src.is_file():
        pytest.skip("6bbu_fixed_protonated.cif sample missing")
    text = src.read_text(encoding="utf-8")
    atoms = [
        a
        for a in parse_structure_atoms(text, "cif")
        if a.chain == "A" and a.resi in {"912", "913", "914"}
    ]
    assert any(a.resn == "GLU" and a.resi == "913" for a in atoms)
    pdb_path = tmp_path / "glu913.pdb"
    pdb_path.write_text(_pdb_from_atoms(atoms), encoding="utf-8")
    out = tmp_path / "glu913.pdbqt"
    err, _ignored = _write_receptor_pdbqt_file(pdb_path, out)
    assert err is None
    assert out.is_file()
    assert out.stat().st_size > 100
