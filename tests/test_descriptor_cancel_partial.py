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

"""Calculate Descriptors must emit partial results when cancelled mid-ionization."""

from __future__ import annotations

from unittest.mock import patch

from molmanager.workers.chemistry_tools import CalcDescriptorsRequest, CalcWorker
from molmanager.workers.signals import WorkerSignals


class _AlwaysCancelled:
    def is_set(self) -> bool:
        return True


def test_calc_worker_emits_partial_results_when_cancelled_during_ionization():
    """
    Regression: cancelling while Uni-pKa (ClogD / LogS 7.4) ensembles are still computing
    must still emit the rows already finished instead of crashing with a NameError.
    """
    sigs = WorkerSignals()
    out: dict[str, object] = {}
    sigs.calculated.connect(lambda rows, headers: out.update({"rows": rows, "headers": headers}))
    sigs.partial_results.connect(
        lambda label, done, total: out.update({"partial": (label, done, total)})
    )

    data = [(1, "CCO"), (2, "CCN"), (3, "CCC")]
    disp_headers = ["LogD 7.4"]

    # Only rows 1 and 3 finished microstates before the cancel; row 2 is incomplete (None).
    partial_cache = {1: ["state1"], 2: None, 3: ["state3"]}

    with (
        patch(
            "molmanager.workers.chemistry_descriptors.int_fns_need_ionization",
            return_value=True,
        ),
        patch(
            "molmanager.workers.chemistry_descriptors.build_microstates_cache_for_rows",
            return_value=partial_cache,
        ),
        patch(
            "molmanager.workers.chemistry_descriptors._calc_descriptor_row_task",
            side_effect=lambda task: (task[0], {"LogD 7.4": f"val{task[0]}"}),
        ),
    ):
        worker = CalcWorker(
            CalcDescriptorsRequest(
                data=data,
                disp_headers=disp_headers,
                int_fns=["LogD 7.4"],
                is_smiles=True,
            ),
            sigs,
            cancel_event=_AlwaysCancelled(),
        )
        worker.run()

    rows = out.get("rows")
    assert isinstance(rows, list)
    # Only the two structures with completed microstates should be returned.
    assert {oid for oid, _ in rows} == {1, 3}
    assert out.get("headers") == ["LogD 7.4", "pKa"]
    label, done, total = out["partial"]
    assert label == "Calculate descriptors"
    assert done == 2
    assert total == 3
