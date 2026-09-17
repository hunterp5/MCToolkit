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

import pytest
from rdkit import Chem

from molmanager.som_prediction import (
    SOM_CANCELLED_ERROR,
    SOM_ENTROPY_COLUMN,
    SOM_FAME_COLUMN,
    SOM_MAP_COLUMN,
    SOM_P1_SITES_COLUMN,
    SOM_P2_SITES_COLUMN,
    SOM_PHASE_COLUMN,
    SOM_PROB_COLUMN,
    SOM_SITES_COLUMN,
    SomAtomHit,
    SomMoleculePrediction,
    _group_atom_rows,
    format_som_columns,
    merge_phase_predictions,
    predict_soms_batch,
    render_som_map_png,
    shannon_binary_entropy,
    som_atom_label,
    som_output_columns,
    som_phase_label,
)


def test_som_atom_label_includes_probability() -> None:
    assert som_atom_label(3, 0.812) == "3; 0.81"
    assert som_atom_label(0, 1) == "0; 1.00"


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
    assert SOM_P1_SITES_COLUMN not in som_output_columns(include_fame=False)
    phased = som_output_columns(include_fame=False, include_phases=True)
    assert phased[:5] == [
        SOM_MAP_COLUMN,
        SOM_SITES_COLUMN,
        SOM_P1_SITES_COLUMN,
        SOM_P2_SITES_COLUMN,
        SOM_PHASE_COLUMN,
    ]
    with_fame = som_output_columns(include_fame=True, include_phases=True)
    assert with_fame.index(SOM_FAME_COLUMN) == with_fame.index(SOM_ENTROPY_COLUMN) - 1


def test_merge_phase_predictions_union_and_labels() -> None:
    p1 = SomMoleculePrediction(
        smiles="CCO",
        preprocessed_smiles="CCO",
        atoms=(
            SomAtomHit(0, 0.81, True),
            SomAtomHit(1, 0.10, False),
            SomAtomHit(2, 0.40, True),
        ),
    )
    p2 = SomMoleculePrediction(
        smiles="CCO",
        preprocessed_smiles="CCO",
        atoms=(
            SomAtomHit(0, 0.20, False),
            SomAtomHit(1, 0.90, True),
            SomAtomHit(2, 0.70, True),
        ),
    )
    merged = merge_phase_predictions(p1, p2)
    by_id = {a.atom_id: a for a in merged.atoms}
    assert by_id[0].is_som and by_id[0].is_phase1_som and not by_id[0].is_phase2_som
    assert by_id[0].probability == 0.81
    assert by_id[1].is_som and by_id[1].is_phase2_som and not by_id[1].is_phase1_som
    assert by_id[2].is_phase1_som and by_id[2].is_phase2_som
    assert som_phase_label(by_id[2]) == "P1+P2"
    row = format_som_columns(merged, include_phases=True)
    assert row[SOM_SITES_COLUMN] == "1, 0, 2"
    assert row[SOM_P1_SITES_COLUMN] == "0, 2"
    assert row[SOM_P2_SITES_COLUMN] == "1, 2"
    assert row[SOM_PHASE_COLUMN] == "1:P2; 0:P1; 2:P1+P2"


def test_merge_phase_predictions_keeps_other_side_on_cancel() -> None:
    p1 = SomMoleculePrediction(
        smiles="CCO",
        preprocessed_smiles="CCO",
        atoms=(SomAtomHit(0, 0.9, True),),
    )
    p2 = SomMoleculePrediction("CCO", "", (), error=SOM_CANCELLED_ERROR)
    merged = merge_phase_predictions(p1, p2)
    assert merged.error is None
    assert merged.atoms[0].is_phase1_som
    assert not merged.atoms[0].is_phase2_som


def test_merge_phase_predictions_both_cancelled() -> None:
    p1 = SomMoleculePrediction("CCO", "", (), error=SOM_CANCELLED_ERROR)
    p2 = SomMoleculePrediction("CCO", "", (), error=SOM_CANCELLED_ERROR)
    merged = merge_phase_predictions(p1, p2)
    assert merged.error == SOM_CANCELLED_ERROR


def test_predict_soms_batch_rejects_unknown_subset() -> None:
    with pytest.raises(ValueError, match="Unknown metabolism subset"):
        predict_soms_batch(["CCO"], metabolism_subset="compare")  # type: ignore[arg-type]


def test_metabolism_options_have_no_compare() -> None:
    from molmanager.som_prediction import (
        METABOLISM_SUBSET_OPTIONS,
        NERDD_METABOLISM_SUBSETS,
        uses_split_phase_jobs,
    )

    nerd_keys = {k for k, _ in NERDD_METABOLISM_SUBSETS}
    ui_keys = {k for k, _ in METABOLISM_SUBSET_OPTIONS}
    assert nerd_keys == ui_keys
    assert "compare" not in ui_keys
    assert uses_split_phase_jobs("all")
    assert not uses_split_phase_jobs("phase1")


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
    p1_atoms = (SomAtomHit(1, 0.9, True, is_phase1_som=True, is_phase2_som=False),)
    p2_atoms = (SomAtomHit(1, 0.9, True, is_phase1_som=False, is_phase2_som=True),)
    p1_png = render_som_map_png("CCO", p1_atoms, width=120, height=100)
    p2_png = render_som_map_png("CCO", p2_atoms, width=120, height=100)
    assert p1_png is not None and p2_png is not None
    assert p1_png == p2_png
    blank = render_som_map_png("not-a-molecule", atoms, width=120, height=100)
    assert blank is None


def _dark_ink_span(png: bytes) -> tuple[int, int]:
    from PyQt5.QtGui import QImage

    img = QImage.fromData(png)
    min_x, min_y = img.width(), img.height()
    max_x, max_y = -1, -1
    for y in range(img.height()):
        for x in range(img.width()):
            c = img.pixelColor(x, y)
            if c.red() < 50 and c.green() < 50 and c.blue() < 50:
                min_x = min(min_x, x)
                min_y = min(min_y, y)
                max_x = max(max_x, x)
                max_y = max(max_y, y)
    return max(0, max_x - min_x), max(0, max_y - min_y)


def test_som_map_matches_structure_molecule_scale(qapp) -> None:  # noqa: ARG001
    from molmanager.structure_draw import render_molecule_png

    mol = Chem.MolFromSmiles("c1ccccc1O")
    assert mol is not None
    struct = render_molecule_png(mol, 180, 140)
    som = render_som_map_png("c1ccccc1O", (), width=180, height=140, reference_mol=mol)
    assert struct and som
    w1, h1 = _dark_ink_span(struct)
    w2, h2 = _dark_ink_span(som)
    assert w1 > 20 and h1 > 20
    assert abs(w1 - w2) <= 8
    assert abs(h1 - h2) <= 8


def test_emphasize_does_not_resize_molecule(qapp) -> None:  # noqa: ARG001
    atoms = (
        SomAtomHit(0, 0.2, False),
        SomAtomHit(1, 0.9, True),
        SomAtomHit(2, 0.1, False),
    )
    plain = render_som_map_png("CCO", atoms, width=180, height=140)
    emphasized = render_som_map_png("CCO", atoms, width=180, height=140, emphasize_atom=1)
    assert plain is not None and emphasized is not None
    w1, h1 = _dark_ink_span(plain)
    w2, h2 = _dark_ink_span(emphasized)
    assert w1 > 8 and h1 > 8
    assert abs(w1 - w2) <= 2
    assert abs(h1 - h2) <= 2


def test_render_som_map_png_matches_reference_orientation() -> None:
    from rdkit.Chem import rdDepictor
    from rdkit.Geometry import Point3D

    ref = Chem.MolFromSmiles("c1ccccc1O")
    assert ref is not None
    rdDepictor.Compute2DCoords(ref)
    conf = ref.GetConformer()
    for i in range(ref.GetNumAtoms()):
        p = conf.GetAtomPosition(i)
        conf.SetAtomPosition(i, Point3D(-float(p.x), float(p.y), 0.0))
    atoms = (SomAtomHit(0, 0.9, True),)
    plain = render_som_map_png("c1ccccc1O", atoms, width=140, height=120)
    matched = render_som_map_png("c1ccccc1O", atoms, width=140, height=120, reference_mol=ref)
    assert plain is not None and matched is not None
    assert matched != plain


def test_emphasize_keeps_atom_color() -> None:
    mol = Chem.MolFromSmiles("CCO")
    assert mol is not None
    from molmanager.som_prediction import _apply_emphasized_atom, som_probability_rgb

    keep = som_probability_rgb(0.9)
    colors = {1: keep}
    radii = {1: 0.55}
    highlight = [1]
    _apply_emphasized_atom(
        mol,
        atom_id=1,
        highlight=highlight,
        colors=colors,
        radii=radii,
        atom_color=keep,
    )
    assert colors[1] == keep
    assert radii[1] == pytest.approx(0.65)
    assert radii[1] < 0.8


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


def test_som_worker_phase1_and_2_calls_predict_twice(monkeypatch, qapp) -> None:  # noqa: ARG001
    from molmanager.som_prediction import SOM_P1_SITES_COLUMN, SOM_P2_SITES_COLUMN
    from molmanager.workers.signals import WorkerSignals
    from molmanager.workers.som_worker import SomPredictorSignals, SomPredictorWorker

    finished: list = []
    failed: list = []
    sig = SomPredictorSignals()
    sig.finished.connect(lambda rows: finished.append(rows))
    sig.failed.connect(lambda msg: failed.append(msg))
    subsets: list[str] = []

    def fake_predict(smiles, **kwargs):
        subset = str(kwargs.get("metabolism_subset"))
        subsets.append(subset)
        if subset == "phase1":
            atoms = (SomAtomHit(0, 0.9, True), SomAtomHit(1, 0.1, False))
        else:
            atoms = (SomAtomHit(0, 0.1, False), SomAtomHit(1, 0.8, True))
        return [
            SomMoleculePrediction(
                smiles=smiles[0],
                preprocessed_smiles=smiles[0],
                atoms=atoms,
            )
        ]

    monkeypatch.setattr("molmanager.workers.som_worker.predict_soms_batch", fake_predict)
    mol = Chem.MolFromSmiles("CCO")
    assert mol is not None
    SomPredictorWorker(
        [(1, mol)],
        WorkerSignals(),
        sig,
        metabolism_subset="all",
    ).run()
    assert failed == []
    assert subsets == ["phase1", "phase2"]
    oid, cols, png, atoms, headers = finished[0][0]
    assert oid == 1
    assert cols[SOM_SITES_COLUMN] == "0, 1"
    assert cols[SOM_P1_SITES_COLUMN] == "0"
    assert cols[SOM_P2_SITES_COLUMN] == "1"
    assert png is not None
    by_id = {a.atom_id: a for a in atoms}
    assert by_id[0].is_phase1_som and not by_id[0].is_phase2_som
    assert by_id[1].is_phase2_som and not by_id[1].is_phase1_som
    assert SOM_P1_SITES_COLUMN in headers
    assert "compare" not in subsets


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


def test_job_entry_progress_uses_fallback_when_total_missing() -> None:
    from molmanager.som_prediction import _job_entry_progress

    processed, total = _job_entry_progress(
        {"status": "created", "num_entries_total": None, "num_entries_processed": 0},
        fallback_total=12,
    )
    assert processed == 0
    assert total == 12


def test_job_entry_progress_counts_compressed_ranges() -> None:
    from molmanager.som_prediction import _job_entry_progress

    processed, total = _job_entry_progress(
        {
            "status": "processing",
            "num_entries_total": 20,
            "entries_processed": [[0, 5], [10, 12]],
        },
        fallback_total=10,
    )
    assert processed == 7
    assert total == 20


def test_job_entry_progress_completed_snaps_to_total() -> None:
    from molmanager.som_prediction import _job_entry_progress

    processed, total = _job_entry_progress(
        {"status": "completed", "num_entries_total": 8, "num_entries_processed": 8},
        fallback_total=8,
    )
    assert processed == 8
    assert total == 8


def test_som_worker_reports_waiting_progress_before_nerdd(monkeypatch, qapp) -> None:  # noqa: ARG001
    from molmanager.tool_progress import ToolProgressState
    from molmanager.workers.signals import WorkerSignals
    from molmanager.workers.som_worker import SomPredictorSignals, SomPredictorWorker

    state = ToolProgressState()
    state.begin("Predict SOM", 1)
    snapshots: list[tuple[str, int, int]] = []

    def fake_predict(smiles, progress=None, **_kwargs):
        if progress is not None:
            progress(0, max(len(smiles), 1))
        msg, done, total, _active = state.snapshot()
        snapshots.append((msg, done, total))
        return [
            SomMoleculePrediction(smi, smi, atoms=(SomAtomHit(0, 0.9, True),)) for smi in smiles
        ]

    monkeypatch.setattr("molmanager.workers.som_worker.predict_soms_batch", fake_predict)
    mol = Chem.MolFromSmiles("CCO")
    assert mol is not None
    sig = SomPredictorSignals()
    SomPredictorWorker(
        [(1, mol)],
        WorkerSignals(),
        sig,
        progress_state=state,
    ).run()
    assert snapshots
    assert snapshots[0][2] == -1
    assert "waiting" in snapshots[0][0].lower() or "submitting" in snapshots[0][0].lower()
    _msg, done, total, active = state.snapshot()
    assert active
    assert done >= 1
    assert total == 1
    state.end()
