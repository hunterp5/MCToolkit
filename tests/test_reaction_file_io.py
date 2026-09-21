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

"""MDL RXN / RDF load helpers."""

from __future__ import annotations

from pathlib import Path

import pytest
from rdkit.Chem import AllChem

from mctoolkit.chem.reaction_file_io import (
    RXN_SMARTS_HEADER,
    is_reaction_smarts_header,
    load_reaction_smarts_from_rxn_path,
    load_rxn_file,
    looks_like_reaction_smarts,
    parse_reaction_smarts,
    reaction_smarts_from_app_selection,
    split_rxn_blocks,
)

_AMIDE = "[C:1](=[O:2])-[OH;D1].[N;H2,H1]>>[C:1](=[O:2])-[N]"


def _amide_rxn_text() -> str:
    rxn = AllChem.ReactionFromSmarts(_AMIDE)
    return AllChem.ReactionToRxnBlock(rxn)


def test_is_reaction_smarts_header() -> None:
    assert is_reaction_smarts_header("Reaction SMARTS")
    assert is_reaction_smarts_header("SMIRKS")
    assert not is_reaction_smarts_header("SMILES")
    assert not is_reaction_smarts_header("Reaction Name")


def test_looks_like_and_parse_reaction_smarts() -> None:
    assert looks_like_reaction_smarts(_AMIDE)
    assert parse_reaction_smarts(_AMIDE) is not None
    assert not looks_like_reaction_smarts("CCO")
    assert parse_reaction_smarts("CCO") is None
    assert parse_reaction_smarts("not a reaction >> still not") is None


def test_load_rxn_file_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "amide.rxn"
    path.write_text(_amide_rxn_text(), encoding="utf-8")
    records = load_rxn_file(path)
    assert len(records) == 1
    rec = records[0]
    assert ">>" in rec.smarts
    assert rec.mol is not None
    assert rec.mol.HasProp(RXN_SMARTS_HEADER)
    parsed = AllChem.ReactionFromSmarts(rec.smarts)
    assert parsed is not None
    assert int(parsed.GetNumReactantTemplates()) == 2


def test_load_concatenated_rxn_blocks(tmp_path: Path) -> None:
    block = _amide_rxn_text()
    path = tmp_path / "two.rxn"
    path.write_text(block.rstrip() + "\n" + block, encoding="utf-8")
    assert len(split_rxn_blocks(path.read_text(encoding="utf-8"))) == 2
    records = load_rxn_file(path)
    assert len(records) == 2
    smarts, n_rxn = load_reaction_smarts_from_rxn_path(path)
    assert n_rxn == 2
    assert ">>" in smarts


def test_empty_rxn_file_errors(tmp_path: Path) -> None:
    path = tmp_path / "empty.rxn"
    path.write_text("not a reaction\n", encoding="utf-8")
    assert load_rxn_file(path) == []
    with pytest.raises(ValueError, match="No reactions"):
        load_reaction_smarts_from_rxn_path(path)


def test_reaction_smarts_from_app_selection() -> None:
    class _Model:
        def value_for_header(self, row: int, header: str) -> str:
            assert row == 0
            assert header == "Reaction SMARTS"
            return _AMIDE

    class _App:
        headers = ["ID_HIDDEN", "Structure", "Reaction SMARTS"]
        _table_model = _Model()

        def _selected_logical_rows(self) -> list[int]:
            return [0]

    assert reaction_smarts_from_app_selection(_App()) == _AMIDE
    empty = _App()
    empty._selected_logical_rows = lambda: []  # type: ignore[method-assign]
    assert reaction_smarts_from_app_selection(empty) == ""
