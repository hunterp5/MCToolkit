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

"""Legacy session CSV load (background SMILES parse)."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest
from rdkit import Chem

from mctoolkit.ui.main_window import ChemistryWorkspaceWindow
from mctoolkit.workers.session_rows_parse import CsvSessionParseResult, CsvSessionParseWorker
from mctoolkit.workers.session_rows_parse import SessionRowsParseSignals


@pytest.fixture(autouse=True)
def _skip_session_auto_render(monkeypatch) -> None:
    monkeypatch.setattr(
        ChemistryWorkspaceWindow,
        "_try_auto_render_all_structures_after_ingest",
        lambda self: False,
    )


def test_csv_session_parse_worker_parses_smiles(tmp_path: Path) -> None:
    path = tmp_path / "session.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["SMILES", "Note"])
        writer.writeheader()
        writer.writerow({"SMILES": "CCO", "Note": "ethanol"})
        writer.writerow({"SMILES": "not-a-smiles", "Note": "bad"})
        writer.writerow({"SMILES": "CCN", "Note": "ethylamine"})

    signals = SessionRowsParseSignals()
    caught: list[object] = []
    signals.finished.connect(caught.append)
    CsvSessionParseWorker(str(path), signals, generation=1).run()

    assert len(caught) == 1
    result = caught[0]
    assert isinstance(result, CsvSessionParseResult)
    assert result.columns == ["SMILES", "Note"]
    assert result.next_oid == 3
    assert len(result.prepared_rows) == 3
    assert set(result.mols) == {0, 2}
    assert Chem.MolToSmiles(result.mols[0]) == "CCO"


def test_load_session_csv_builds_table(qapp, tmp_path: Path) -> None:  # noqa: ARG001
    path = tmp_path / "legacy.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["SMILES", "MW", "Note"])
        writer.writeheader()
        writer.writerow({"SMILES": "CCO", "MW": "46.07", "Note": "a"})
        writer.writerow({"SMILES": "c1ccccc1", "MW": "78.11", "Note": "b"})

    win = ChemistryWorkspaceWindow()
    win.load_session_csv(str(path))

    assert win.headers[:5] == ["ID_HIDDEN", "Structure", "SMILES", "MW", "Note"]
    assert win._table_model.rowCount() == 2
    assert win.next_oid == 2
    assert set(win.mols) == {0, 1}
    assert win._table_cell_text(win.logical_row_for_oid(0), win.headers.index("Note")) == "a"
    assert win._table_cell_text(win.logical_row_for_oid(1), win.headers.index("SMILES")) == (
        "c1ccccc1"
    )
