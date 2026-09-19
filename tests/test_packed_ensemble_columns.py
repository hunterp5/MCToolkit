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

"""Packed confs / superpose / poses columns are never overwritten in place."""

from __future__ import annotations

import base64
import json

from molmanager.confs_codec import is_packed_ensemble_header


def test_is_packed_ensemble_header_matches_confs_superpose_poses():
    assert is_packed_ensemble_header("confs")
    assert is_packed_ensemble_header("confs (1)")
    assert is_packed_ensemble_header("confs_2")
    assert is_packed_ensemble_header("superpose")
    assert is_packed_ensemble_header("poses")
    assert is_packed_ensemble_header("poses (1)")
    assert not is_packed_ensemble_header("confidence")
    assert not is_packed_ensemble_header("SMILES")
    assert not is_packed_ensemble_header("")


def _packed_cell(tag: str) -> str:
    blocks = base64.b64encode(json.dumps([tag]).encode("utf-8")).decode("ascii")
    return json.dumps(
        {"v": 1, "m": {"ok": True, "n_kept": 1, "n_packed": 1}, "b": blocks},
        separators=(",", ":"),
    )


def _app_with_row(headers: list[str], cells: dict[str, str]):
    from molmanager.ui.main_window import ChemistryWorkspaceWindow

    w = ChemistryWorkspaceWindow()
    w.headers = list(headers)
    w._table_model.set_headers(list(w.headers))
    w._table_model.append_row(0, dict(cells))
    w.mols = {}
    w.next_oid = 1
    w._auto_open_first_conformer_results = lambda *a, **k: 0
    w._open_conformer_results_viewer = lambda *a, **k: None
    return w


def test_on_conformers_finished_creates_confs_when_missing(qapp):  # noqa: ARG001
    packed = _packed_cell("new")
    w = _app_with_row(["ID_HIDDEN", "Structure"], {})
    try:
        w._begin_tool_progress("Generate conformations", 50)
        w._on_tool_progress("Generate conformations…", 49, 50)
        w.on_conformers_finished([(0, None, packed)])
        assert w._tool_progress_state.snapshot()[3] is False
        assert "confs" in w.headers
        cell = w._table_model.value_for_header(0, "confs")
        assert '"h":"confs"' in cell
        assert (0, "confs") in (w._confs_blocks_sidecar or {})
    finally:
        w.close()


def test_on_conformers_finished_does_not_replace_existing_column(qapp):  # noqa: ARG001
    packed = _packed_cell("new")
    w = _app_with_row(["ID_HIDDEN", "Structure", "confs"], {"confs": "old"})
    try:
        w.on_conformers_finished([(0, None, packed)])
        assert "confs" in w.headers
        assert "confs (1)" in w.headers
        assert w._table_model.value_for_header(0, "confs") == "old"
        new_cell = w._table_model.value_for_header(0, "confs (1)")
        assert '"h":"confs (1)"' in new_cell
        sc = w._confs_blocks_sidecar or {}
        assert (0, "confs (1)") in sc
        assert (0, "confs") not in sc
    finally:
        w.close()


def test_on_superpose_finished_creates_superpose_when_missing(qapp):  # noqa: ARG001
    packed = _packed_cell("overlay")
    w = _app_with_row(["ID_HIDDEN", "Structure"], {})
    try:
        w.on_superpose_finished([(0, None, packed)])
        assert "superpose" in w.headers
        cell = w._table_model.value_for_header(0, "superpose")
        assert '"h":"superpose"' in cell
        assert (0, "superpose") in (w._confs_blocks_sidecar or {})
    finally:
        w.close()


def test_on_superpose_finished_does_not_replace_existing_column(qapp):  # noqa: ARG001
    packed = _packed_cell("overlay")
    w = _app_with_row(["ID_HIDDEN", "Structure", "superpose"], {"superpose": "old"})
    try:
        w.on_superpose_finished([(0, None, packed)])
        assert "superpose" in w.headers
        assert "superpose (1)" in w.headers
        assert w._table_model.value_for_header(0, "superpose") == "old"
        new_cell = w._table_model.value_for_header(0, "superpose (1)")
        assert '"h":"superpose (1)"' in new_cell
        sc = w._confs_blocks_sidecar or {}
        assert (0, "superpose (1)") in sc
        assert (0, "superpose") not in sc
    finally:
        w.close()
