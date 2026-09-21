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
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with mctoolkit. If not, see <https://www.gnu.org/licenses/>.

"""Tests for Predict ADME (ADMET-AI v2 Chemprop weights)."""

from __future__ import annotations

import pytest

from mctoolkit.predictions.adme_prediction import (
    ADME_ENDPOINTS,
    ADME_OUTPUT_COLUMNS,
    ENSEMBLE_CLASSIFICATION,
    ENSEMBLE_REGRESSION,
    RECOMMENDED_ADME_COLUMNS,
    adme_gpu_forced_off,
    adme_models_available,
    adme_stack_import_error,
    ensembles_needed,
    endpoints_for_columns,
    format_adme_row,
    predict_adme_batch,
)


def test_adme_catalog_covers_v2_tasks():
    classification = {
        "AMES",
        "BBB_Martins",
        "Bioavailability_Ma",
        "CYP1A2_Veith",
        "CYP2C19_Veith",
        "CYP2C9_Substrate_CarbonMangels",
        "CYP2C9_Veith",
        "CYP2D6_Substrate_CarbonMangels",
        "CYP2D6_Veith",
        "CYP3A4_Substrate_CarbonMangels",
        "CYP3A4_Veith",
        "Carcinogens_Lagunin",
        "ClinTox",
        "DILI",
        "HIA_Hou",
        "NR-AR-LBD",
        "NR-AR",
        "NR-AhR",
        "NR-Aromatase",
        "NR-ER-LBD",
        "NR-ER",
        "NR-PPAR-gamma",
        "PAMPA_NCATS",
        "Pgp_Broccatelli",
        "SR-ARE",
        "SR-ATAD5",
        "SR-HSE",
        "SR-MMP",
        "SR-p53",
        "Skin_Reaction",
        "hERG",
    }
    regression = {
        "Caco2_Wang",
        "Clearance_Hepatocyte_AZ",
        "Clearance_Microsome_AZ",
        "Half_Life_Obach",
        "HydrationFreeEnergy_FreeSolv",
        "LD50_Zhu",
        "Lipophilicity_AstraZeneca",
        "PPBR_AZ",
        "Solubility_AqSolDB",
        "VDss_Lombardo",
    }
    keys = {ep.task_key for ep in ADME_ENDPOINTS}
    assert keys == classification | regression
    assert len(ADME_OUTPUT_COLUMNS) == len(ADME_ENDPOINTS)
    assert len(set(ADME_OUTPUT_COLUMNS)) == len(ADME_OUTPUT_COLUMNS)
    for col in RECOMMENDED_ADME_COLUMNS:
        assert col in ADME_OUTPUT_COLUMNS


def test_ensembles_needed_skips_unused_folder():
    assert ensembles_needed(["hERG"]) == (ENSEMBLE_CLASSIFICATION,)
    assert ensembles_needed(["PPB"]) == (ENSEMBLE_REGRESSION,)
    assert ensembles_needed(["hERG", "PPB"]) == (
        ENSEMBLE_CLASSIFICATION,
        ENSEMBLE_REGRESSION,
    )
    assert ensembles_needed(["not-a-column"]) == ()


def test_endpoints_for_columns_ignores_unknown():
    eps = endpoints_for_columns(["hERG", "missing", "hERG"])
    assert [ep.column for ep in eps] == ["hERG"]


def test_format_adme_row_subset_and_na():
    row = format_adme_row(None, columns=["hERG"])
    assert row == {"hERG": "N/A"}
    row = format_adme_row({"hERG": 0.8123, "PPB": 88.12}, columns=["hERG"])
    assert list(row.keys()) == ["hERG"]
    assert "PPB" not in row
    assert row["hERG"] == "0.812"


def test_format_adme_row_regression():
    row = format_adme_row({"PPB": 12.3456}, columns=["PPB"])
    assert row["PPB"] == "12.3456"


def test_adme_gpu_forced_off_env(monkeypatch) -> None:
    monkeypatch.delenv("MCTOOLKIT_ADME_GPU", raising=False)
    assert adme_gpu_forced_off() is False
    monkeypatch.setenv("MCTOOLKIT_ADME_GPU", "0")
    assert adme_gpu_forced_off() is True
    monkeypatch.setenv("MCTOOLKIT_ADME_GPU", "cpu")
    assert adme_gpu_forced_off() is True


def test_predict_adme_batch_empty_columns_returns_nones():
    out = predict_adme_batch(["CCO"], output_columns=())
    assert out == [None]


def test_predict_adme_batch_smiles(monkeypatch):
    if adme_stack_import_error() is not None or not adme_models_available():
        pytest.skip("Chemprop stack or ADME checkpoints not installed")
    out = predict_adme_batch(
        ["CCO", "not_a_molecule"],
        output_columns=("hERG",),
    )
    assert len(out) == 2
    assert out[0] is not None
    assert "hERG" in out[0]
    assert 0.0 <= out[0]["hERG"] <= 1.0
    assert out[1] is None


def test_dispatch_adme_predict_isolates_cuda_wheel(monkeypatch) -> None:
    from mctoolkit.workers import adme_worker as aw

    seen: dict[str, object] = {}

    def _child(smiles, batch_size, output_columns, cancel_event, progress_callback):
        seen["n"] = len(smiles)
        seen["cols"] = output_columns
        return [{"hERG": 0.2}] * len(smiles)

    monkeypatch.setattr(aw, "adme_needs_cuda_isolation", lambda: True)
    monkeypatch.setattr(aw, "_predict_in_cuda_child", _child)
    monkeypatch.setattr(
        aw,
        "predict_adme_batch",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("in-process CUDA")),
    )
    out = aw.dispatch_adme_predict(["CCO"], output_columns=("hERG",), batch_size=8)
    assert seen == {"n": 1, "cols": ("hERG",)}
    assert out == [{"hERG": 0.2}]


def test_dispatch_adme_predict_cpu_in_process(monkeypatch) -> None:
    from mctoolkit.workers import adme_worker as aw

    monkeypatch.setattr(aw, "adme_needs_cuda_isolation", lambda: False)

    def _in_process(smiles, output_columns=(), batch_size=64, progress_callback=None):
        assert output_columns == ("BBB",)
        return [None] * len(smiles)

    monkeypatch.setattr(aw, "predict_adme_batch", _in_process)
    monkeypatch.setattr(
        aw,
        "_predict_in_cuda_child",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("child CPU")),
    )
    out = aw.dispatch_adme_predict(["CCO"], output_columns=("BBB",), batch_size=16)
    assert out == [None]
