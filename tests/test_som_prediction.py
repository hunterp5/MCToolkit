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

"""Tests for FAME3R site-of-metabolism helpers (no NERDD network required)."""

from __future__ import annotations

from rdkit import Chem

from molmanager.som_prediction import (
    SOM_FAME_COLUMN,
    SOM_MAP_COLUMN,
    SOM_PROB_COLUMN,
    SOM_SITES_COLUMN,
    SomAtomHit,
    SomMoleculePrediction,
    _group_atom_rows,
    format_som_columns,
    render_som_map_png,
    shannon_binary_entropy,
    som_output_columns,
)


def test_shannon_binary_entropy_bounds() -> None:
    assert shannon_binary_entropy(0.5) == 1.0
    assert shannon_binary_entropy(0.0) < 0.01
    assert shannon_binary_entropy(1.0) < 0.01
    assert 0.0 < shannon_binary_entropy(0.3) < 1.0


def test_format_som_columns_sites_and_probs() -> None:
    pred = SomMoleculePrediction(
        smiles="CCO",
        preprocessed_smiles="CCO",
        atoms=(
            SomAtomHit(0, 0.12, False, shannon_entropy=0.5),
            SomAtomHit(1, 0.81, True, fame_score=0.7, shannon_entropy=0.4),
            SomAtomHit(2, 0.44, True, fame_score=0.6, shannon_entropy=0.9),
        ),
    )
    row = format_som_columns(pred, include_fame=True)
    assert row[SOM_MAP_COLUMN] == "CCO"
    assert row[SOM_SITES_COLUMN] == "1, 2"
    assert row[SOM_PROB_COLUMN].startswith("1:0.81; 2:0.44")
    assert row[SOM_FAME_COLUMN] == "0.65"


def test_format_som_columns_error() -> None:
    pred = SomMoleculePrediction("", "", (), error="Empty SMILES.")
    row = format_som_columns(pred, include_fame=False)
    assert row[SOM_MAP_COLUMN] == "Empty SMILES."
    assert row[SOM_SITES_COLUMN] == "N/A"
    assert SOM_FAME_COLUMN not in row


def test_som_output_columns_order() -> None:
    assert som_output_columns(include_fame=False)[0] == SOM_MAP_COLUMN
    assert SOM_FAME_COLUMN in som_output_columns(include_fame=True)
    assert SOM_FAME_COLUMN not in som_output_columns(include_fame=False)


def test_group_atom_rows_by_mol_id() -> None:
    rows = [
        {
            "mol_id": 0,
            "atom_id": 0,
            "prediction": 0.8,
            "prediction_binary": True,
            "preprocessed_smiles": "CCO",
            "problems": [],
        },
        {
            "mol_id": 0,
            "atom_id": 1,
            "prediction": 0.1,
            "prediction_binary": False,
            "preprocessed_smiles": "CCO",
            "problems": [],
        },
        {
            "mol_id": 1,
            "atom_id": 0,
            "prediction": 0.2,
            "prediction_binary": False,
            "preprocessed_smiles": "c1ccccc1",
            "problems": [],
        },
    ]
    out = _group_atom_rows(rows, ["CCO", "c1ccccc1"], threshold=0.3)
    assert len(out) == 2
    assert out[0].atoms[0].is_som
    assert out[0].preprocessed_smiles == "CCO"
    assert not out[1].atoms[0].is_som


def test_render_som_map_png_highlights() -> None:
    mol = Chem.MolFromSmiles("CCO")
    assert mol is not None
    atoms = (
        SomAtomHit(0, 0.2, False),
        SomAtomHit(1, 0.9, True),
        SomAtomHit(2, 0.1, False),
    )
    png = render_som_map_png("CCO", atoms, width=120, height=100)
    assert png is not None
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    emphasized = render_som_map_png("CCO", atoms, width=120, height=100, emphasize_atom=2)
    assert emphasized is not None
    assert emphasized != png
    blank = render_som_map_png("not-a-molecule", atoms, width=120, height=100)
    assert blank is None


def test_som_worker_emits_map(monkeypatch, qapp) -> None:  # noqa: ARG001
    from molmanager.som_prediction import SOM_SITES_COLUMN
    from molmanager.workers.signals import WorkerSignals
    from molmanager.workers.som_worker import SomPredictorSignals, SomPredictorWorker

    finished: list = []
    failed: list = []
    sig = SomPredictorSignals()
    sig.finished.connect(lambda rows: finished.append(rows))
    sig.failed.connect(lambda msg: failed.append(msg))

    def fake_predict(smiles, **_kwargs):
        return [
            SomMoleculePrediction(
                smiles=smiles[0],
                preprocessed_smiles=smiles[0],
                atoms=(
                    SomAtomHit(0, 0.9, True),
                    SomAtomHit(1, 0.1, False),
                    SomAtomHit(2, 0.2, False),
                ),
            )
        ]

    monkeypatch.setattr("molmanager.workers.som_worker.predict_soms_batch", fake_predict)
    mol = Chem.MolFromSmiles("CCO")
    assert mol is not None
    SomPredictorWorker([(1, mol)], WorkerSignals(), sig).run()
    assert failed == []
    assert finished
    oid, cols, png, atoms, headers = finished[0][0]
    assert oid == 1
    assert cols[SOM_SITES_COLUMN] == "0"
    assert png is not None and png[:8] == b"\x89PNG\r\n\x1a\n"
    assert any(a.is_som for a in atoms)
    assert SOM_MAP_COLUMN in headers


def test_predict_soms_batch_skips_delete_when_cancelled(monkeypatch) -> None:
    from molmanager.som_prediction import SOM_CANCELLED_ERROR, predict_soms_batch

    calls: list[str] = []

    def fake_json(url, *, method="GET", **_kwargs):
        calls.append(f"{method} {url}")
        if method == "POST":
            return {"id": "job-1"}
        if method == "DELETE":
            raise AssertionError("NERDD job delete must be skipped after cancel")
        return {"status": "running"}

    monkeypatch.setattr("molmanager.som_prediction._json_request", fake_json)
    monkeypatch.setattr("molmanager.som_prediction._app_is_shutting_down", lambda: False)

    def cancel() -> bool:
        return any(c.startswith("POST ") for c in calls)

    out = predict_soms_batch(["CCO"], cancel=cancel, poll_interval_s=0.5)
    assert len(out) == 1
    assert out[0].error == SOM_CANCELLED_ERROR
    assert not any("DELETE" in c for c in calls)


def test_predict_soms_batch_keeps_completed_chunk_on_cancel(monkeypatch) -> None:
    from molmanager.som_prediction import SOM_CANCELLED_ERROR, predict_soms_batch

    finished_jobs = {"n": 0}

    def fake_json(url, *, method="GET", **_kwargs):
        if method == "POST":
            return {"id": f"job-{finished_jobs['n'] + 1}"}
        if method == "DELETE":
            finished_jobs["n"] += 1
            return {}
        if "/results" in url:
            return {
                "data": [
                    {
                        "mol_id": 0,
                        "atom_id": 0,
                        "prediction": 0.91,
                        "prediction_binary": True,
                        "preprocessed_smiles": "CCO",
                        "problems": [],
                    }
                ]
            }
        return {"status": "completed", "num_pages_total": 1}

    monkeypatch.setattr("molmanager.som_prediction._json_request", fake_json)
    monkeypatch.setattr("molmanager.som_prediction._app_is_shutting_down", lambda: False)

    def cancel() -> bool:
        return finished_jobs["n"] >= 1

    out = predict_soms_batch(["CCO", "c1ccccc1"], batch_size=1, cancel=cancel)
    assert out[0].atoms and out[0].atoms[0].is_som
    assert out[1].error == SOM_CANCELLED_ERROR


def test_som_worker_emits_partial_results_on_cancel(monkeypatch, qapp) -> None:  # noqa: ARG001
    import threading

    from molmanager.som_prediction import SOM_CANCELLED_ERROR, SOM_SITES_COLUMN
    from molmanager.workers.signals import WorkerSignals
    from molmanager.workers.som_worker import SomPredictorSignals, SomPredictorWorker

    finished: list = []
    failed: list = []
    partial: list = []
    sig = SomPredictorSignals()
    sig.finished.connect(lambda rows: finished.append(rows))
    sig.failed.connect(lambda msg: failed.append(msg))
    ws = WorkerSignals()
    ws.partial_results.connect(lambda tool, done, total: partial.append((tool, done, total)))
    cancel_ev = threading.Event()

    def fake_predict(smiles, cancel=None, **_kwargs):
        out = []
        for i, smi in enumerate(smiles):
            if i > 0 and cancel is not None and cancel():
                out.append(SomMoleculePrediction(smi, "", (), error=SOM_CANCELLED_ERROR))
                continue
            out.append(
                SomMoleculePrediction(
                    smi,
                    smi,
                    atoms=(SomAtomHit(0, 0.9, True),),
                )
            )
            cancel_ev.set()
        return out

    monkeypatch.setattr("molmanager.workers.som_worker.predict_soms_batch", fake_predict)
    mol_a = Chem.MolFromSmiles("CCO")
    mol_b = Chem.MolFromSmiles("c1ccccc1")
    assert mol_a is not None and mol_b is not None
    SomPredictorWorker(
        [(1, mol_a), (2, mol_b)],
        ws,
        sig,
        cancel_event=cancel_ev,
    ).run()
    assert failed == []
    assert finished
    rows = finished[0]
    assert rows[0][1][SOM_SITES_COLUMN] == "0"
    assert rows[1][1][SOM_MAP_COLUMN] == SOM_CANCELLED_ERROR
    assert partial
    assert partial[0][0] == "Predict SOM"
    assert partial[0][1] == 1
    assert partial[0][2] == 2
