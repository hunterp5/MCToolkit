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

"""SubstructureFilterWorker (background substructure match)."""

from __future__ import annotations

from PySide6.QtCore import QThreadPool

from molmanager.workers import SubstructureFilterSignals, SubstructureFilterWorker


def test_substructure_worker_ethane_matches_c(qapp):  # noqa: ARG001
    sig = SubstructureFilterSignals()
    results: list[tuple[int, frozenset]] = []

    def _on_finished(gen, matched):
        results.append((gen, matched))

    sig.finished.connect(_on_finished)
    pool = QThreadPool()
    targets = [(0, "CC"), (1, "c1ccccc1")]
    pool.start(SubstructureFilterWorker(7, "C", targets, sig))
    assert pool.waitForDone(60000)
    qapp.processEvents()
    assert len(results) == 1
    gen, matched = results[0]
    assert gen == 7
    assert matched == [("C", "Structure", frozenset({0}))]


def test_substructure_worker_invalid_smarts_empty_set(qapp):  # noqa: ARG001
    sig = SubstructureFilterSignals()
    results: list[object] = []
    sig.finished.connect(lambda _g, m: results.append(m))
    pool = QThreadPool()
    pool.start(SubstructureFilterWorker(1, "not_valid_smarts_{{{", [(0, "CC")], sig))
    assert pool.waitForDone(60000)
    qapp.processEvents()
    assert results and results[0] == [("not_valid_smarts_{{{", "Structure", frozenset())]
