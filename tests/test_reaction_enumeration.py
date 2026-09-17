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

"""Tests for reaction-based enumeration."""

from __future__ import annotations

from pathlib import Path

import pytest
from rdkit import Chem

from molmanager.reaction_enumeration import (
    enumerate_reaction,
    load_reactant_molecules,
    load_reactant_molecules_from_smiles_text,
    load_reaction_presets,
    validate_reaction_smarts,
    write_product_smiles_to_sdf,
)


def test_load_reaction_presets_includes_named_templates() -> None:
    presets = load_reaction_presets()
    names = {p.name for p in presets}
    assert "Suzuki coupling" in names
    assert "Heck coupling" in names
    assert "Williamson ether synthesis" in names
    assert len([p for p in presets if p.id != "custom"]) >= 14


def test_validate_reaction_smarts_requires_two_reactants() -> None:
    rxn = validate_reaction_smarts("[C:1](=[O:2])-[OH;D1].[N;H2,H1]>>[C:1](=[O:2])-[N]")
    assert int(rxn.GetNumReactantTemplates()) == 2
    with pytest.raises(ValueError, match="two reactants"):
        validate_reaction_smarts("[C:1][OH:2]>>[C:1][O-:2]")


def test_enumerate_amide_coupling() -> None:
    acid = Chem.MolFromSmiles("CC(=O)O")
    amine = Chem.MolFromSmiles("CN")
    smarts = "[C:1](=[O:2])-[OH;D1].[N;H2,H1]>>[C:1](=[O:2])-[N]"
    products, skipped, cancelled = enumerate_reaction(
        smarts,
        [[acid], [amine]],
        max_products=10,
    )
    assert not cancelled
    assert products
    assert (
        "CC(N)=O" in products[0] or Chem.MolToSmiles(Chem.MolFromSmiles(products[0])) == "CC(N)=O"
    )


def test_suzuki_template_matches_acid_and_pinacol() -> None:
    from rdkit.Chem import AllChem

    presets = {p.id: p for p in load_reaction_presets()}
    smarts = presets["suzuki"].smarts
    rxn = AllChem.ReactionFromSmarts(smarts)
    halide = Chem.MolFromSmiles("c1ccc(Br)cc1")
    boronic_acid = Chem.MolFromSmiles("c1ccc(B(O)O)cc1")
    pinacol = Chem.MolFromSmiles("c1ccc(B2OC(C)(C)C(C)(C)O2)cc1")
    assert rxn.RunReactants((halide, boronic_acid))
    assert rxn.RunReactants((halide, pinacol))


def test_all_bundled_presets_parse() -> None:
    for preset in load_reaction_presets():
        if preset.id == "custom" or not preset.smarts.strip():
            continue
        validate_reaction_smarts(preset.smarts)


def test_load_reactant_molecules_from_smiles_text() -> None:
    mols = load_reactant_molecules_from_smiles_text("CCO\nCC(=O)O\n# skipped\n")
    assert len(mols) == 2


def test_load_reactant_pool_smiles_mode() -> None:
    from molmanager.reaction_enumeration import load_reactant_pool

    mols = load_reactant_pool(source="smiles", smiles_text="CCO\nCN")
    assert len(mols) == 2


def test_load_reactant_molecules_from_smiles_file(tmp_path: Path) -> None:
    path = tmp_path / "reactants.smi"
    path.write_text("CCO\nCC(=O)O\n# comment\n", encoding="utf-8")
    mols = load_reactant_molecules(path)
    assert len(mols) == 2


def test_write_product_smiles_to_sdf(tmp_path: Path) -> None:
    out = tmp_path / "products.sdf"
    n = write_product_smiles_to_sdf(out, ["CCO", "CCN"], "Amide")
    assert n == 2
    suppl = Chem.SDMolSupplier(str(out))
    assert len([m for m in suppl if m is not None]) == 2


def test_reaction_enumeration_dialog_accepts_initial_smarts(qapp):  # noqa: ARG001
    from molmanager.ui.dialogs.reaction_enumeration import ReactionEnumerationDialog

    smarts = "[C:1](=[O:2])-[OH;D1].[N;H2,H1]>>[C:1](=[O:2])-[N]"
    dlg = ReactionEnumerationDialog(initial_smarts=smarts)
    assert dlg.smarts_edit.text() == smarts
    assert dlg.load_rxn_btn.text().startswith("Load RXN")
    dlg.close()
