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

"""Batched 2D render: child-process task shape, worker sizing, and the batched GUI handler."""

from __future__ import annotations

import pytest
from rdkit import Chem

from molmanager.platform_support.config import load_config
from molmanager.workers.load_render import (
    Render2DBatchProcessWorker,
    _mp_render_structure_batch,
    render2d_process_worker_count,
)

SMILES = ["CCO", "c1ccccc1", "CC(=O)Oc1ccccc1C(=O)O"]


def test_batch_render_returns_png_per_row() -> None:
    items = [(i, Chem.MolFromSmiles(s).ToBinary()) for i, s in enumerate(SMILES)]
    rows = _mp_render_structure_batch((items, 242, 202))
    assert len(rows) == len(items)
    for (oid, png, ok, w, h), (exp_oid, _blob) in zip(rows, items):
        assert oid == exp_oid
        assert ok is True
        assert png.startswith(b"\x89PNG")
        assert (w, h) == (242, 202)


def test_batch_render_marks_bad_rows_without_dropping_them() -> None:
    items = [(1, b""), (2, Chem.MolFromSmiles("CCO").ToBinary()), (3, b"not a mol")]
    rows = _mp_render_structure_batch((items, 100, 80))
    # Row order and count must be preserved so progress accounting stays correct.
    assert [r[0] for r in rows] == [1, 2, 3]
    assert [r[2] for r in rows] == [False, True, False]
    assert all(r[3:] == (100, 80) for r in rows)


def test_batch_render_honors_requested_size() -> None:
    items = [(0, Chem.MolFromSmiles("CCO").ToBinary())]
    small = _mp_render_structure_batch((items, 120, 100))[0]
    large = _mp_render_structure_batch((items, 484, 404))[0]
    assert small[3:] == (120, 100)
    assert large[3:] == (484, 404)
    assert len(large[1]) > len(small[1])


def test_worker_count_respects_env_override(monkeypatch) -> None:
    monkeypatch.setenv("MOLMANAGER_RENDER2D_PROCESS_WORKERS", "3")
    assert render2d_process_worker_count() == 3
    monkeypatch.delenv("MOLMANAGER_RENDER2D_PROCESS_WORKERS")
    assert render2d_process_worker_count() >= 2


def test_batch_size_default_is_greater_than_one() -> None:
    # One molecule per task made the parent process the throughput ceiling.
    assert load_config().render2d_batch_size > 1


def _worker(items):
    return Render2DBatchProcessWorker(items, signals=None, cancel_event=None, batch_session=1)


def test_build_tasks_batches_rows_and_covers_every_oid(monkeypatch) -> None:
    monkeypatch.setenv("MOLMANAGER_RENDER2D_BATCH_SIZE", "4")
    mol = Chem.MolFromSmiles("CCO")
    items = [(oid, mol, 242, 202) for oid in range(10)]
    tasks = _worker(items).build_tasks()
    assert [len(rows) for rows, _w, _h in tasks] == [4, 4, 2]
    assert sorted(oid for rows, _w, _h in tasks for oid, _b in rows) == list(range(10))
    assert all((w, h) == (242, 202) for _rows, w, h in tasks)


def test_build_tasks_keeps_zoomed_rows_in_their_own_size_group(monkeypatch) -> None:
    monkeypatch.setenv("MOLMANAGER_RENDER2D_BATCH_SIZE", "64")
    mol = Chem.MolFromSmiles("CCO")
    items = [(1, mol, 242, 202), (2, mol, 484, 404), (3, mol, 242, 202)]
    sizes = {(w, h): [oid for oid, _b in rows] for rows, w, h in _worker(items).build_tasks()}
    assert sizes == {(242, 202): [1, 3], (484, 404): [2]}


def test_build_tasks_emits_empty_blob_for_missing_mol() -> None:
    tasks = _worker([(1, None, 242, 202)]).build_tasks()
    assert tasks == [([(1, b"")], 242, 202)]


def test_build_tasks_tags_reaction_smarts() -> None:
    from molmanager.chem.structure_2d_depiction import ReactionDrawSpec

    spec = ReactionDrawSpec("[C:1]>>[C:1]")
    tasks = _worker([(7, spec, 630, 170)]).build_tasks()
    assert len(tasks) == 1
    rows, w, h = tasks[0]
    assert (w, h) == (630, 170)
    assert rows == [(7, ("rxn", b"[C:1]>>[C:1]"))]


def test_batch_render_reaction_smarts() -> None:
    items = [(1, ("rxn", b"[C:1](=[O:2])-[OH].[N]>>[C:1](=[O:2])-[N]"))]
    rows = _mp_render_structure_batch((items, 630, 170))
    assert len(rows) == 1
    oid, png, ok, w, h = rows[0]
    assert oid == 1
    assert ok is True
    assert png.startswith(b"\x89PNG")
    assert (w, h) == (630, 170)
    assert int.from_bytes(png[16:20], "big") == 630
    assert int.from_bytes(png[20:24], "big") == 170


def test_build_tasks_stops_when_cancelled() -> None:
    import threading

    ev = threading.Event()
    ev.set()
    worker = Render2DBatchProcessWorker(
        [(1, Chem.MolFromSmiles("CCO"), 242, 202)],
        signals=None,
        cancel_event=ev,
        batch_session=1,
    )
    assert worker.build_tasks() == []


class _App:
    """Minimal stand-in exposing only what the batched render handler touches."""

    def __init__(self, rows_in_table: set[int], goal: int):
        from molmanager.ui.main_window.render2d_results_mixin import Render2DResultsMixin

        self._rows = rows_in_table
        self._render2d_pending: dict = {}
        self._render2d_accept_session = 7
        self._render2d_batch_active = True
        self._import_progress_active = True
        self._import_render_goal = goal
        self._import_render_done = 0
        self.progress: list[tuple[str, int, int]] = []
        self.flushed = False
        self.restored = False
        self.status_label = type("L", (), {"setText": lambda _s, _t: None})()
        self._cls = Render2DResultsMixin

    # Bound mixin methods under test.
    def _render2d_batch_session_accepted(self, s):
        return self._cls._render2d_batch_session_accepted(self, s)

    def on_render2d_rows_ready(self, rows, s):
        return self._cls.on_render2d_rows_ready(self, rows, s)

    def _advance_render2d_batch_progress(self, n):
        return self._cls._advance_render2d_batch_progress(self, n)

    def _resolve_structure_row_for_oid(self, oid):
        return 0 if oid in self._rows else -1

    def _on_tool_progress(self, msg, done, total):
        self.progress.append((msg, done, total))

    def _clear_tool_progress(self):
        pass

    def _flush_render2d_batch_results(self):
        self.flushed = True

    def _restore_render2d_batch_environment(self):
        self.restored = True


def _png_rows(oids):
    blob = Chem.MolFromSmiles("CCO").ToBinary()
    return _mp_render_structure_batch(([(o, blob) for o in oids], 242, 202))


def test_batched_handler_stores_results_and_finishes_batch() -> None:
    app = _App(rows_in_table={1, 2, 3, 4}, goal=4)
    app.on_render2d_rows_ready(_png_rows([1, 2]), 7)
    assert set(app._render2d_pending) == {1, 2}
    assert app._render2d_pending[1][1] is True
    assert not app.flushed

    app.on_render2d_rows_ready(_png_rows([3, 4]), 7)
    assert app._import_render_done == 4
    assert app.flushed and app.restored
    assert app.progress[-1] == ("Render 2D", 4, 4)


def test_batched_handler_ignores_superseded_session() -> None:
    app = _App(rows_in_table={1}, goal=1)
    app.on_render2d_rows_ready(_png_rows([1]), 999)
    assert app._render2d_pending == {}
    assert app._import_render_done == 0
    assert not app.flushed


def test_batched_handler_marks_rows_missing_from_table_as_failed() -> None:
    app = _App(rows_in_table=set(), goal=2)
    app.on_render2d_rows_ready(_png_rows([1, 2]), 7)
    assert app._render2d_pending[1] == (b"", False, 242, 202)
    assert app._import_render_done == 2


@pytest.mark.parametrize("rows", [[], None])
def test_batched_handler_tolerates_empty_payload(rows) -> None:
    app = _App(rows_in_table={1}, goal=1)
    app.on_render2d_rows_ready(rows, 7)
    assert app._render2d_pending == {}
    assert app._import_render_done == 0
