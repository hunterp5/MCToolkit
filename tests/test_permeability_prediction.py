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

"""Tests for GNN-MTL permeability prediction (optional Chemprop + model file)."""

from __future__ import annotations

import pytest

from molmanager.predictions.permeability_prediction import (
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
