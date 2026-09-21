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

from __future__ import annotations

from rdkit import Chem

from mctoolkit.workers.signals import SubstructureFilterSignals
from mctoolkit.workers.substructure_filter import SubstructureFilterWorker


def test_substructure_worker_uses_prebuilt_mol_targets():
    signals = SubstructureFilterSignals()
    out: dict[str, object] = {}
    signals.finished.connect(
        lambda job_gen, matched: out.update({"gen": job_gen, "matched": matched})
    )
    worker = SubstructureFilterWorker(
        job_gen=7,
        smarts="CO",
        targets=[(1, Chem.MolFromSmiles("CCO")), (2, Chem.MolFromSmiles("CCN"))],
        signals=signals,
    )
    worker.run()
    assert out["gen"] == 7
    assert out["matched"] == [("CO", "Structure", frozenset({1}))]


def test_substructure_worker_group_queries_support_negation():
    from mctoolkit.workers.substructure_filter import mol_matches_pattern_groups

    q = Chem.MolFromSmarts("O")
    ethanol = Chem.MolFromSmiles("CCO")
    ethane = Chem.MolFromSmiles("CC")
    assert mol_matches_pattern_groups(ethanol, [[(q, False)]])
    assert not mol_matches_pattern_groups(ethane, [[(q, False)]])
    assert mol_matches_pattern_groups(ethane, [[(q, True)]])

    signals = SubstructureFilterSignals()
    out: dict[str, object] = {}
    signals.finished.connect(
        lambda job_gen, matched: out.update({"gen": job_gen, "matched": matched})
    )
    worker = SubstructureFilterWorker(
        job_gen=2,
        signals=signals,
        group_queries=[
            (
                "0",
                "Structure",
                [(1, ethanol), (2, ethane)],
                [[(q, True)]],
            )
        ],
    )
    worker.run()
    assert out["gen"] == 2
    assert out["matched"] == [("0", "Structure", frozenset({2}))]
