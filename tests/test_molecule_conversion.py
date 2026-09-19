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

"""Tests for molmanager.chem.molecule_conversion helpers."""

from __future__ import annotations

from rdkit import Chem

from molmanager.chem.molecule_conversion import (
    copy_mol,
    is_rdkit_mol,
    looks_like_structure_cell_text,
    mol_from_ligand_path,
    mol_from_molblock,
    mol_from_smarts,
    mol_from_smiles,
    mol_structure_copy_texts,
    mol_to_molblock,
    mol_to_pdbblock,
    parse_molecule_from_cell_text,
    redact_sqlalchemy_url,
    safe_float,
    safe_mol_prop_string,
)


def test_safe_float_none():
    assert safe_float(None) is None


def test_safe_float_valid():
    assert safe_float(" 3.14 ") == 3.14
    assert safe_float(42) == 42.0


def test_safe_float_invalid():
    assert safe_float("not a number") is None
    assert safe_float("") is None


def test_safe_mol_prop_string_missing():
    mol = Chem.MolFromSmiles("CC")
    assert safe_mol_prop_string(mol, "nonexistent_prop") == ""


def test_redact_sqlalchemy_url_masks_password():
    u = "postgresql+psycopg://alice:secret@localhost:5432/mydb"
    r = redact_sqlalchemy_url(u)
    assert "secret" not in r
    assert "***" in r
    assert "alice" in r


def test_redact_sqlalchemy_url_no_password_unchanged():
    assert redact_sqlalchemy_url("sqlite:///C:/data/app.db") == "sqlite:///C:/data/app.db"


def test_safe_mol_prop_string_present():
    mol = Chem.MolFromSmiles("CC")
    mol.SetProp("CustomTag", "hello")
    assert safe_mol_prop_string(mol, "CustomTag") == "hello"


def test_looks_like_structure_cell_text_rejects_urls_and_json():
    assert looks_like_structure_cell_text("CCO")
    assert not looks_like_structure_cell_text("http://selleckchem.com/products/Carmofur.html")
    assert not looks_like_structure_cell_text(
        '{"v":2,"h":"confs","m":{"ok":true,"n_requested":50}}'
    )


def test_parse_molecule_from_cell_text_skips_urls_and_json_quietly(capsys):
    assert parse_molecule_from_cell_text("http://selleckchem.com/products/Carmofur.html") is None
    assert (
        parse_molecule_from_cell_text(
            '{"v":2,"h":"superpose","m":{"ok":true,"align_pattern":"Cc1n[nH]c2cc(S)ccc12"}}'
        )
        is None
    )
    err = capsys.readouterr().err
    assert "SMILES Parse Error" not in err
    assert "SMARTS Parse Error" not in err


def test_mol_structure_copy_texts_ethanol():
    mol = Chem.MolFromSmiles("CCO")
    texts = mol_structure_copy_texts(mol)
    assert texts["smiles"] == "CCO"
    assert texts["inchi"] == "InChI=1S/C2H6O/c1-2-3/h3H,2H2,1H3"
    assert texts["inchikey"] == "LFQSCWFLJHTTHZ-UHFFFAOYSA-N"
    assert "V2000" in texts["molfile"]
    parsed = Chem.MolFromMolBlock(texts["molfile"])
    assert parsed is not None
    assert Chem.MolToSmiles(parsed, canonical=True) == "CCO"
    assert texts["smarts"]


def test_mol_structure_copy_texts_none():
    texts = mol_structure_copy_texts(None)
    assert texts == {
        "smiles": "",
        "inchi": "",
        "inchikey": "",
        "molfile": "",
        "smarts": "",
    }


def test_is_rdkit_mol_accepts_molecules_only():
    mol = Chem.MolFromSmiles("CCO")
    assert is_rdkit_mol(mol)
    assert not is_rdkit_mol(None)
    assert not is_rdkit_mol("CCO")


def test_copy_mol_is_independent():
    mol = Chem.MolFromSmiles("CCO")
    mol.SetProp("tag", "orig")
    clone = copy_mol(mol)
    assert clone is not None
    assert clone is not mol
    clone.SetProp("tag", "copy")
    assert mol.GetProp("tag") == "orig"
    assert copy_mol(None) is None


def test_mol_from_smiles_and_smarts():
    assert Chem.MolToSmiles(mol_from_smiles("CCO"), canonical=True) == "CCO"
    assert mol_from_smiles("") is None
    assert mol_from_smiles("not-smiles") is None
    q = mol_from_smarts("[OH]")
    assert q is not None
    assert q.GetNumAtoms() == 1
    assert mol_from_smarts("") is None


def test_mol_from_molblock_roundtrip():
    src = Chem.MolFromSmiles("CCO")
    block = Chem.MolToMolBlock(src)
    parsed = mol_from_molblock(block)
    assert parsed is not None
    assert Chem.MolToSmiles(parsed, canonical=True) == "CCO"
    assert mol_from_molblock("") is None
    assert mol_to_molblock(src).strip()


def test_mol_to_pdbblock_has_atoms():
    mol = Chem.MolFromSmiles("CCO")
    from rdkit.Chem import rdDepictor

    rdDepictor.Compute2DCoords(mol)
    block = mol_to_pdbblock(mol)
    assert "ATOM" in block or "HETATM" in block


def test_mol_from_ligand_path_sdf(tmp_path):
    mol = Chem.MolFromSmiles("CCO")
    sdf = tmp_path / "lig.sdf"
    writer = Chem.SDWriter(str(sdf))
    writer.write(mol)
    writer.close()
    loaded = mol_from_ligand_path(sdf)
    assert loaded is not None
    assert Chem.MolToSmiles(loaded, canonical=True) == "CCO"
    assert mol_from_ligand_path(tmp_path / "missing.sdf") is None
