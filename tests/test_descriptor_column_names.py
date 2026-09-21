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
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with MCToolkit.  If not, see <https://www.gnu.org/licenses/>.

"""Unique column names for descriptor calculation."""

from __future__ import annotations

from mctoolkit.ui.table_write_service import TableWriteService


class _Host:
    def __init__(self, headers: list[str]) -> None:
        self.headers = list(headers)


def test_unique_table_column_names_skips_existing() -> None:
    names = TableWriteService(
        _Host(["ID_HIDDEN", "Structure", "LogP", "LogP (1)"])
    )._unique_table_column_names(["LogP", "TPSA"])
    assert names == ["LogP (2)", "TPSA"]


def test_unique_table_column_names_dedupes_batch() -> None:
    names = TableWriteService(_Host(["ID_HIDDEN", "Structure"]))._unique_table_column_names(
        ["Score", "Score", "Other"]
    )
    assert names == ["Score", "Score (1)", "Other"]


def test_on_calc_finished_does_not_replace_existing_column(qapp):  # noqa: ARG001
    from mctoolkit.ui.main_window import ChemistryWorkspaceWindow

    w = ChemistryWorkspaceWindow()
    w.headers = ["ID_HIDDEN", "Structure", "LogP"]
    w._table_model.set_headers(list(w.headers))
    w._table_model.append_row(0, {"LogP": "1.23"})
    w.mols = {}
    w.next_oid = 1

    written = w.on_calc_finished(
        [(0, {"LogP": "9.99"})],
        ["LogP"],
        finish_progress=False,
    )
    assert written == ["LogP (1)"]
    assert "LogP" in w.headers
    assert "LogP (1)" in w.headers
    assert w._table_model.value_for_header(0, "LogP") == "1.23"
    assert w._table_model.value_for_header(0, "LogP (1)") == "9.99"
    w.close()


def test_on_calc_finished_colors_qed_score(qapp):  # noqa: ARG001
    from mctoolkit.ui.main_window import ChemistryWorkspaceWindow

    w = ChemistryWorkspaceWindow()
    w.headers = ["ID_HIDDEN", "Structure"]
    w._table_model.set_headers(list(w.headers))
    w._table_model.append_row(0, {})
    w.mols = {}
    w.next_oid = 1
    written = w.on_calc_finished(
        [(0, {"QED Score": "0.80"})],
        ["QED Score"],
        finish_progress=False,
    )
    assert written == ["QED Score"]
    spec = w._table_model.column_color_rule_spec("QED Score")
    assert spec is not None
    assert spec["mode"] == "numeric3"
    w.close()


def test_on_calc_finished_updates_pka_and_pi_in_place(qapp):  # noqa: ARG001
    from mctoolkit.ui.main_window import ChemistryWorkspaceWindow

    w = ChemistryWorkspaceWindow()
    w.headers = ["ID_HIDDEN", "Structure", "pKa", "pI"]
    w._table_model.set_headers(list(w.headers))
    w._table_model.append_row(0, {"pKa": "4.76", "pI": "N/A"})
    w.mols = {}
    w.next_oid = 1

    written = w.on_calc_finished(
        [(0, {"pKa": "9.50", "pI": "5.97"})],
        ["pKa", "pI"],
        finish_progress=False,
    )
    assert written == ["pKa", "pI"]
    assert w.headers.count("pKa") == 1
    assert "pKa (1)" not in w.headers
    assert w._table_model.value_for_header(0, "pKa") == "9.50"
    assert w._table_model.value_for_header(0, "pI") == "5.97"
    w.close()


def test_on_calc_finished_chunks_large_write(qapp, monkeypatch):  # noqa: ARG001
    from mctoolkit.ui.main_window import ChemistryWorkspaceWindow

    w = ChemistryWorkspaceWindow()
    w.headers = ["ID_HIDDEN", "Structure"]
    w._table_model.set_headers(list(w.headers))
    w._table_model.append_rows_batch([(i, {}) for i in range(4)])
    w.mols = {}
    w.next_oid = 4
    monkeypatch.setattr(w.table_write, "_calc_writeback_async_min_rows", lambda: 2)
    monkeypatch.setattr(w.table_write, "_calc_writeback_chunk_rows", lambda: 2)
    completed: list[list[str]] = []
    written = w.on_calc_finished(
        [(i, {"LogP": str(i)}) for i in range(4)],
        ["LogP"],
        finish_progress=False,
        on_complete=completed.append,
    )
    assert written == ["LogP"]
    for _ in range(40):
        qapp.processEvents()
        if completed:
            break
    assert completed == [["LogP"]]
    assert [w._table_model.value_for_header(i, "LogP") for i in range(4)] == [
        "0",
        "1",
        "2",
        "3",
    ]
    w.close()


def test_on_calc_finished_immediate_skips_chunking(qapp, monkeypatch):  # noqa: ARG001
    from mctoolkit.ui.main_window import ChemistryWorkspaceWindow

    w = ChemistryWorkspaceWindow()
    w.headers = ["ID_HIDDEN", "Structure"]
    w._table_model.set_headers(list(w.headers))
    w._table_model.append_rows_batch([(i, {}) for i in range(4)])
    w.mols = {}
    w.next_oid = 4
    monkeypatch.setattr(w.table_write, "_calc_writeback_async_min_rows", lambda: 2)
    started: list[int] = []
    monkeypatch.setattr(
        w.table_write,
        "_start_calc_writeback",
        lambda *a, **k: started.append(1),
    )
    completed: list[list[str]] = []
    written = w.on_calc_finished(
        [(i, {"LogP": str(i)}) for i in range(4)],
        ["LogP"],
        finish_progress=False,
        immediate=True,
        on_complete=completed.append,
    )
    assert written == ["LogP"]
    assert started == []
    assert completed == [["LogP"]]
    assert [w._table_model.value_for_header(i, "LogP") for i in range(4)] == [
        "0",
        "1",
        "2",
        "3",
    ]
    w.close()
