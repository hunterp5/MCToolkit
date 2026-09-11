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

"""Tests for Data → Split Column."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from rdkit import Chem

from molmanager.column_split import (
    SplitColumnParams,
    apply_keep_mode,
    detect_delimiter,
    extreme_split_field,
    output_column_names,
    pad_split_rows,
    split_cell_text,
    split_column_values,
    unescape_custom_delimiter,
)
from molmanager.ui.main_window import ChemicalTableApp
from molmanager.ui.strings import TOOL_SPLIT_COLUMN


def test_split_cell_comma_and_quotes() -> None:
    assert split_cell_text("a, b, c", ",") == ["a", "b", "c"]
    assert split_cell_text('"a, b", c', ",") == ["a, b", "c"]
    assert split_cell_text("a,,c", ",") == ["a", "", "c"]


def test_split_cell_tab_semicolon_pipe_space() -> None:
    assert split_cell_text("a\tb\tc", "\t") == ["a", "b", "c"]
    assert split_cell_text("a; b;c", ";") == ["a", "b", "c"]
    assert split_cell_text("a|b|c", "|") == ["a", "b", "c"]
    assert split_cell_text("  a   b  c ", " ") == ["a", "b", "c"]


def test_detect_delimiter_prefers_punctuation_over_space() -> None:
    assert detect_delimiter(["a, b, c", "d, e"]) == ","
    assert detect_delimiter(["a;b", "c;d;e"]) == ";"
    assert detect_delimiter(["one two", "three four five"]) == " "


def test_split_column_auto_and_custom() -> None:
    delim, parts = split_column_values(["x, y", "z"], "auto")
    assert delim == ","
    assert parts == [["x", "y"], ["z"]]
    delim, parts = split_column_values(["a:b:c"], "custom", custom=":")
    assert delim == ":"
    assert parts == [["a", "b", "c"]]
    assert unescape_custom_delimiter(r"\t") == "\t"
    with pytest.raises(ValueError, match="custom delimiter"):
        split_column_values(["a"], "custom", custom="")


def test_output_names_and_padding() -> None:
    assert output_column_names("Tags", 3) == ["Tags_1", "Tags_2", "Tags_3"]
    padded = pad_split_rows([["a", "b"], ["c"]], 3)
    assert padded == [["a", "b", ""], ["c", "", ""]]


def test_split_column_writes_new_headers(qapp) -> None:  # noqa: ARG001
    w = ChemicalTableApp()
    w.headers = ["ID_HIDDEN", "Structure", "SMILES", "Tags"]
    w._table_model.set_headers(list(w.headers))
    w._table_model.append_row(0, {"SMILES": "CCO", "Tags": "acid, base"})
    w._table_model.append_row(1, {"SMILES": "CCN", "Tags": "base; extra, note"})
    w.mols[0] = Chem.MolFromSmiles("CCO")
    w.mols[1] = Chem.MolFromSmiles("CCN")
    w.next_oid = 2

    accepted = SimpleNamespace(
        params=lambda: SplitColumnParams(
            source_column="Tags",
            mode="comma",
            custom="",
            prefix="Tags",
        ),
        only_selected_rows=lambda: False,
    )
    w._on_split_column_dialog_accepted(accepted)
    assert "Tags_1" in w.headers
    assert "Tags_2" in w.headers
    i1 = w.headers.index("Tags_1")
    i2 = w.headers.index("Tags_2")
    assert w._table_model.cell_text(0, i1) == "acid"
    assert w._table_model.cell_text(0, i2) == "base"
    assert w._table_model.cell_text(1, i1) == "base; extra"
    assert w._table_model.cell_text(1, i2) == "note"
    assert TOOL_SPLIT_COLUMN in (w.status_label.text() or "")


def test_extreme_split_field_numeric_and_text() -> None:
    assert extreme_split_field(["1", "10", "3"], largest=True) == "10"
    assert extreme_split_field(["1", "10", "3"], largest=False) == "1"
    assert extreme_split_field(["acid", "12", "3.5"], largest=True) == "12"
    assert extreme_split_field(["acid", "12", "3.5"], largest=False) == "3.5"
    assert extreme_split_field(["zebra", "apple"], largest=True) == "zebra"
    assert extreme_split_field(["zebra", "apple"], largest=False) == "apple"


def test_apply_keep_mode_largest_smallest() -> None:
    parts = [["1", "4", "2"], ["9", "0"], []]
    assert apply_keep_mode(parts, "largest") == [["4"], ["9"], [""]]
    assert apply_keep_mode(parts, "smallest") == [["1"], ["0"], [""]]
    assert apply_keep_mode(parts, "all") == parts


def test_split_column_writes_largest_value(qapp):  # noqa: ARG001
    w = ChemicalTableApp()
    w.headers = ["ID_HIDDEN", "Structure", "SMILES", "Scores"]
    w._table_model.set_headers(list(w.headers))
    w._table_model.append_row(0, {"SMILES": "CCO", "Scores": "1.2, 8.5, 3"})
    w._table_model.append_row(1, {"SMILES": "CCN", "Scores": "0.4, 2.1, 2.0"})
    w.mols[0] = Chem.MolFromSmiles("CCO")
    w.mols[1] = Chem.MolFromSmiles("CCN")
    w.next_oid = 2

    accepted = SimpleNamespace(
        params=lambda: SplitColumnParams(
            source_column="Scores",
            mode="comma",
            custom="",
            prefix="Best",
            keep="largest",
        ),
        only_selected_rows=lambda: False,
    )
    w._on_split_column_dialog_accepted(accepted)
    assert "Best" in w.headers
    i = w.headers.index("Best")
    assert w._table_model.cell_text(0, i) == "8.5"
    assert w._table_model.cell_text(1, i) == "2.1"
    w.close()


def test_split_dialog_extreme_checkboxes_exclusive(qapp):  # noqa: ARG001
    from molmanager.ui.dialogs.split_column import SplitColumnDialog

    dlg = SplitColumnDialog(["Tags"], 0)
    dlg.largest_cb.setChecked(True)
    assert dlg.params().keep == "largest"
    dlg.smallest_cb.setChecked(True)
    assert dlg.largest_cb.isChecked() is False
    assert dlg.params().keep == "smallest"
    dlg.close()
