# This file is part of mctoolkit.
# Copyright (C) 2026 Hunter Picard
#
# mctoolkit is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# mctoolkit is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with mctoolkit.  If not, see <https://www.gnu.org/licenses/>.

"""Tests for GNN-MTL permeability prediction (optional Chemprop + model file)."""

from __future__ import annotations

import pytest

from mctoolkit.predictions.permeability_prediction import (
    PERMEABILITY_OUTPUT_COLUMNS,
    _linear_from_log10,
    _linear_values_from_log_predictions,
    format_permeability_row,
    permeability_model_available,
    permeability_stack_import_error,
    predict_permeability_batch,
)


def test_permeability_output_columns_linear_names():
    assert len(PERMEABILITY_OUTPUT_COLUMNS) == 4
    assert PERMEABILITY_OUTPUT_COLUMNS[0] == "Caco-2 ER"
    assert PERMEABILITY_OUTPUT_COLUMNS[1] == "Caco-2 Papp"
    assert "log" not in " ".join(PERMEABILITY_OUTPUT_COLUMNS).lower()


def test_linear_from_log10():
    assert _linear_from_log10(3.223) == pytest.approx(10**3.223, rel=1e-9)
    assert _linear_from_log10(-0.821) == pytest.approx(10**-0.821, rel=1e-9)


def test_linear_values_from_log_predictions():
    linear = _linear_values_from_log_predictions(
        {
            "caco2_er_log": -0.821,
            "caco2_papp_log": 3.223,
            "mdck_er_log": 0.637,
            "nih_mdck_er_log": 1.159,
        }
    )
    assert set(linear) == set(PERMEABILITY_OUTPUT_COLUMNS)
    assert linear["Caco-2 Papp"] == pytest.approx(10**3.223, rel=1e-6)


def test_format_permeability_row_na():
    row = format_permeability_row(None)
    assert all(row[h] == "N/A" for h in PERMEABILITY_OUTPUT_COLUMNS)


def test_format_permeability_row_linear():
    row = format_permeability_row({"Caco-2 ER": 0.15, "Caco-2 Papp": 1670.0})
    assert row["Caco-2 ER"] == "0.15"
    assert float(row["Caco-2 Papp"]) == pytest.approx(1670.0, rel=0.01)


def test_format_permeability_row_subset_columns():
    row = format_permeability_row(
        {"Caco-2 ER": 0.15, "Caco-2 Papp": 1670.0},
        columns=["Caco-2 Papp"],
    )
    assert list(row.keys()) == ["Caco-2 Papp"]
    assert "Caco-2 ER" not in row


def test_predict_permeability_batch_smiles_linear():
    if permeability_stack_import_error() is not None or not permeability_model_available():
        pytest.skip("Chemprop stack or GNN-MTL model.pt not installed")
    out = predict_permeability_batch(["CCO", "c1ccccc1O", "not_a_molecule"])
    assert len(out) == 3
    assert out[0] is not None
    assert out[1] is not None
    assert out[2] is None
    for col in PERMEABILITY_OUTPUT_COLUMNS:
        assert col in out[0]
    # Ethanol: model log Papp ≈ 3.223 → linear ×10⁻⁶ cm/s
    assert out[0]["Caco-2 Papp"] == pytest.approx(10**3.223, rel=0.01)
    assert out[0]["Caco-2 Papp"] > 100


def test_permeability_gpu_forced_off_env(monkeypatch) -> None:
    from mctoolkit.predictions.permeability_prediction import permeability_gpu_forced_off

    monkeypatch.delenv("MCTOOLKIT_PERMEABILITY_GPU", raising=False)
    assert permeability_gpu_forced_off() is False
    monkeypatch.setenv("MCTOOLKIT_PERMEABILITY_GPU", "0")
    assert permeability_gpu_forced_off() is True
    monkeypatch.setenv("MCTOOLKIT_PERMEABILITY_GPU", "cpu")
    assert permeability_gpu_forced_off() is True


def test_permeability_use_gpu_honors_env(monkeypatch) -> None:
    import sys
    from types import ModuleType

    from mctoolkit.predictions import permeability_prediction as perm

    monkeypatch.setenv("MCTOOLKIT_PERMEABILITY_GPU", "0")
    assert perm.permeability_use_gpu() is False
    assert perm.permeability_lightning_accelerator() == "cpu"

    monkeypatch.delenv("MCTOOLKIT_PERMEABILITY_GPU", raising=False)

    class _Cuda:
        @staticmethod
        def is_available() -> bool:
            return True

    fake = ModuleType("torch")
    fake.cuda = _Cuda  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "torch", fake)
    assert perm.permeability_use_gpu() is True
    assert perm.permeability_lightning_accelerator() == "gpu"


def test_permeability_lightning_accelerator_cpu_when_no_cuda(monkeypatch) -> None:
    from mctoolkit.predictions import permeability_prediction as perm

    monkeypatch.setattr(perm, "permeability_use_gpu", lambda: False)
    assert perm.permeability_lightning_accelerator() == "cpu"


def test_permeability_needs_cuda_isolation_uses_wheel_flag(monkeypatch) -> None:
    from mctoolkit.predictions import permeability_prediction as perm

    monkeypatch.setattr("mctoolkit.ionization.unipka_ensembles.torch_is_cuda_build", lambda: True)
    assert perm.permeability_needs_cuda_isolation() is True
    monkeypatch.setattr("mctoolkit.ionization.unipka_ensembles.torch_is_cuda_build", lambda: False)
    assert perm.permeability_needs_cuda_isolation() is False


def test_dispatch_permeability_predict_isolates_cuda_wheel(monkeypatch) -> None:
    from mctoolkit.workers import permeability_worker as pw

    seen: dict[str, object] = {}

    def _child(smiles, batch_size, cancel_event, progress_callback):
        seen["n"] = len(smiles)
        seen["batch"] = batch_size
        return [{"Caco-2 ER": 1.0}] * len(smiles)

    monkeypatch.setattr(pw, "permeability_needs_cuda_isolation", lambda: True)
    monkeypatch.setattr(pw, "_predict_in_cuda_child", _child)
    monkeypatch.setattr(
        pw,
        "predict_permeability_batch",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("in-process CUDA")),
    )
    out = pw.dispatch_permeability_predict(["CCO", "c1ccccc1"], batch_size=8)
    assert seen == {"n": 2, "batch": 8}
    assert len(out) == 2


def test_dispatch_permeability_predict_cpu_in_process(monkeypatch) -> None:
    from mctoolkit.workers import permeability_worker as pw

    monkeypatch.setattr(pw, "permeability_needs_cuda_isolation", lambda: False)

    def _in_process(smiles, batch_size=64, progress_callback=None):
        assert batch_size == 16
        return [None] * len(smiles)

    monkeypatch.setattr(pw, "predict_permeability_batch", _in_process)
    monkeypatch.setattr(
        pw,
        "_predict_in_cuda_child",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("child CPU")),
    )
    out = pw.dispatch_permeability_predict(["CCO"], batch_size=16)
    assert out == [None]


def test_chunk_smiles_splits_batches() -> None:
    from mctoolkit.workers.permeability_worker import _chunk_smiles

    assert _chunk_smiles([], 64) == []
    chunks = _chunk_smiles(["a", "b", "c", "d", "e"], 2)
    assert chunks == [["a", "b"], ["c", "d"], ["e"]]
