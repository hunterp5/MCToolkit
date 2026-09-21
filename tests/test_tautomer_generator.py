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
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with mctoolkit. If not, see <https://www.gnu.org/licenses/>.

"""Likely tautomer enumeration (RDKit MolStandardize)."""

from __future__ import annotations

from rdkit import Chem

from mctoolkit.chem.tautomer_enumeration import (
    enumerate_likely_tautomers,
    likely_score_cutoff,
)
from mctoolkit.ui.dialogs.tautomer import TautomerGeneratorDialog


def _smiles_set(hits) -> set[str]:
    return {h.smiles for h in hits}


def test_likely_score_cutoff_keeps_pyridone_pair_drops_quinoid():
    assert likely_score_cutoff(102) == 99
    assert likely_score_cutoff(5) == 2


def test_ethanol_has_no_alternative_tautomers():
    mol = Chem.MolFromSmiles("CCO")
    hits = enumerate_likely_tautomers(mol)
    assert len(hits) == 1
    assert hits[0].is_input
    assert hits[0].is_canonical
    assert hits[0].smiles == "CCO"


def test_hydroxypyridine_keeps_pyridone_and_hydroxy():
    mol = Chem.MolFromSmiles("Oc1ccccn1")
    hits = enumerate_likely_tautomers(mol)
    smiles = _smiles_set(hits)
    assert "O=c1cccc[nH]1" in smiles
    assert "Oc1ccccn1" in smiles
    assert "O=C1CC=CC=N1" not in smiles
    assert any(h.is_canonical and h.smiles == "O=c1cccc[nH]1" for h in hits)
    assert any(h.is_input and h.smiles == "Oc1ccccn1" for h in hits)


def test_methylimidazole_has_two_nh_tautomers():
    mol = Chem.MolFromSmiles("Cc1c[nH]cn1")
    hits = enumerate_likely_tautomers(mol)
    assert len(hits) == 2
    assert _smiles_set(hits) == {"Cc1cnc[nH]1", "Cc1c[nH]cn1"}


def test_max_tautomers_caps_xanthine_but_keeps_input():
    mol = Chem.MolFromSmiles("O=c1[nH]c(=O)[nH]c2nc[nH]c12")
    hits = enumerate_likely_tautomers(mol, max_tautomers=3)
    assert 1 <= len(hits) <= 4
    input_smi = Chem.MolToSmiles(mol, canonical=True, isomericSmiles=True)
    assert any(h.is_input and h.smiles == input_smi for h in hits)
    assert not any(h.score < likely_score_cutoff(max(x.score for x in hits)) for h in hits)


def test_none_mol_returns_empty():
    assert enumerate_likely_tautomers(None) == ()


def test_tautomer_dialog_input_mode_uses_item_data(qapp):  # noqa: ARG001
    dlg = TautomerGeneratorDialog(None)
    try:
        keys = [dlg.mode_combo.itemData(i) for i in range(dlg.mode_combo.count())]
        assert keys == ["table", "smiles"]
        assert not dlg._table_cfg.isHidden()
        assert dlg._smiles_cfg.isHidden()
        dlg.mode_combo.setCurrentIndex(keys.index("smiles"))
        assert dlg.mode_combo.currentData() == "smiles"
        assert not dlg._smiles_cfg.isHidden()
        assert dlg._table_cfg.isHidden()
        assert dlg.max_spin.value() == 8
    finally:
        dlg.close()
