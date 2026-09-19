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
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with MolManager. If not, see <https://www.gnu.org/licenses/>.

"""Tests for Data → Table → Join Columns."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from rdkit import Chem

from molmanager.column_join import (
    JoinColumnsParams,
    default_join_output_name,
    join_two_values,
    resolve_join_delimiter,
    unescape_join_delimiter,
)
from molmanager.ui.main_window import ChemistryWorkspaceWindow
from molmanager.ui.strings import TOOL_JOIN_COLUMNS


def test_join_two_values_skips_empty_by_default() -> None:
    assert join_two_values("acid", "base", ", ") == "acid, base"
    assert join_two_values("acid", "", ",") == "acid"
    assert join_two_values("", "base", ",") == "base"
    assert join_two_values("", "", ",") == ""
    assert join_two_values("  ", "base", ",") == "base"


def test_join_two_values_keeps_empty_when_requested() -> None:
    assert join_two_values("acid", "", ",", skip_empty=False) == "acid,"
    assert join_two_values("", "base", ",", skip_empty=False) == ",base"
    assert join_two_values("", "", "|", skip_empty=False) == "|"


def test_resolve_join_delimiter_presets_and_custom() -> None:
    assert resolve_join_delimiter("comma") == ","
    assert resolve_join_delimiter("comma_space") == ", "
    assert resolve_join_delimiter("tab") == "\t"
    assert resolve_join_delimiter("none") == ""
    assert resolve_join_delimiter("custom", custom=" | ") == " | "
    assert unescape_join_delimiter(r"\t") == "\t"
    with pytest.raises(ValueError, match="Unknown delimiter"):
        resolve_join_delimiter("bogus")  # type: ignore[arg-type]


def test_default_join_output_name() -> None:
    assert default_join_output_name("First", "Last") == "First_Last"
    assert default_join_output_name("Name", "Name") == "Name"


def test_join_columns_writes_new_header(qapp) -> None:  # noqa: ARG001
    w = ChemistryWorkspaceWindow()
    w.headers = ["ID_HIDDEN", "Structure", "SMILES", "First", "Last"]
    w._table_model.set_headers(list(w.headers))
    w._table_model.append_row(0, {"SMILES": "CCO", "First": "acid", "Last": "base"})
    w._table_model.append_row(1, {"SMILES": "CCN", "First": "only", "Last": ""})
    w.mols[0] = Chem.MolFromSmiles("CCO")
    w.mols[1] = Chem.MolFromSmiles("CCN")
    w.next_oid = 2

    accepted = SimpleNamespace(
        params=lambda: JoinColumnsParams(
            left_column="First",
            right_column="Last",
            mode="comma_space",
            custom="",
            output_column="Joined",
            skip_empty=True,
        ),
        only_selected_rows=lambda: False,
    )
    w._on_join_columns_dialog_accepted(accepted)
    assert "Joined" in w.headers
    i = w.headers.index("Joined")
    assert w._table_model.cell_text(0, i) == "acid, base"
    assert w._table_model.cell_text(1, i) == "only"
    assert TOOL_JOIN_COLUMNS in (w.status_label.text() or "")
    w.close()


def test_join_dialog_defaults_second_column_and_skip_empty(qapp) -> None:  # noqa: ARG001
    from molmanager.column_join import JOIN_DELIMITER_MODES
    from molmanager.ui.dialogs.join_columns import JoinColumnsDialog

    dlg = JoinColumnsDialog(["First", "Last"], 0)
    assert dlg.left_combo.currentText() == "First"
    assert dlg.right_combo.currentText() == "Last"
    assert dlg.params().skip_empty is True
    assert dlg.params().output_column == "First_Last"
    custom_idx = next(i for i, (_lbl, mode) in enumerate(JOIN_DELIMITER_MODES) if mode == "custom")
    dlg.delim_combo.setCurrentIndex(custom_idx)
    assert dlg.custom_input.isEnabled()
    dlg.close()
