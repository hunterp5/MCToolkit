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

"""Uni-pKa enumerator coverage (no neural-net weights required)."""

from __future__ import annotations

from molmanager.ionization.unipka_enumerator import (
    enumerate_charge_ensemble,
    flatten_charge_ensemble,
)
from rdkit import Chem


def _charges(smi: str) -> set[int]:
    grouped = enumerate_charge_ensemble(smi)
    return {q for q, _smi, _mol in flatten_charge_ensemble(grouped)}


def test_enumerator_acetic_acid_has_acid_and_anion() -> None:
    charges = _charges("CC(=O)O")
    assert 0 in charges
    assert -1 in charges


def test_enumerator_aniline_has_neutral_and_cation() -> None:
    charges = _charges("Nc1ccccc1")
    assert 0 in charges
    assert 1 in charges


def test_enumerator_glycine_covers_zwitterion_window() -> None:
    charges = _charges("NCC(=O)O")
    assert 0 in charges
    assert -1 in charges
    assert 1 in charges


def test_enumerator_templates_parse() -> None:
    mol = Chem.MolFromSmiles("CC(=O)O")
    assert mol is not None
    grouped = enumerate_charge_ensemble("CC(=O)O")
    assert grouped
    assert flatten_charge_ensemble(grouped)


def test_enumerator_charge_ensembles_match_expected_microstates() -> None:
    """Fast path must keep the same (charge, SMILES) sets as the original enumerator."""
    expected = {
        "CC(=O)O": {(-1, "CC(=O)[O-]"), (0, "CC(=O)O")},
        "Nc1ccccc1": {(0, "Nc1ccccc1"), (1, "[NH3+]c1ccccc1")},
        "NCC(=O)O": {
            (-1, "NCC(=O)[O-]"),
            (0, "NCC(=O)O"),
            (0, "[NH3+]CC(=O)[O-]"),
            (1, "[NH3+]CC(=O)O"),
        },
        "NC(CC(=O)O)C(=O)O": {
            (-2, "NC(CC(=O)[O-])C(=O)[O-]"),
            (-1, "NC(CC(=O)O)C(=O)[O-]"),
            (-1, "NC(CC(=O)[O-])C(=O)O"),
            (-1, "[NH3+]C(CC(=O)[O-])C(=O)[O-]"),
            (0, "NC(CC(=O)O)C(=O)O"),
            (0, "[NH3+]C(CC(=O)O)C(=O)[O-]"),
            (0, "[NH3+]C(CC(=O)[O-])C(=O)O"),
            (1, "[NH3+]C(CC(=O)O)C(=O)O"),
        },
        "c1ccccc1O": {(-1, "[O-]c1ccccc1"), (0, "Oc1ccccc1")},
        "CN1CCC[C@H]1c2cccnc2": {
            (0, "CN1CCC[C@H]1c1cccnc1"),
            (1, "CN1CCC[C@H]1c1ccc[nH+]c1"),
            (1, "C[NH+]1CCC[C@H]1c1cccnc1"),
            (2, "C[NH+]1CCC[C@H]1c1ccc[nH+]c1"),
        },
        "CN(C)CCOC(=O)c1ccc(N)cc1": {
            (0, "CN(C)CCOC(=O)c1ccc(N)cc1"),
            (1, "CN(C)CCOC(=O)c1ccc([NH3+])cc1"),
            (1, "C[NH+](C)CCOC(=O)c1ccc(N)cc1"),
            (2, "C[NH+](C)CCOC(=O)c1ccc([NH3+])cc1"),
        },
    }
    for smi, want in expected.items():
        got = {(q, s) for q, s, _mol in flatten_charge_ensemble(enumerate_charge_ensemble(smi))}
        assert got == want, smi
