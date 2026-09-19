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

"""Tests for QSAR model fitting (no Qt)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from molmanager.analysis.qsar_models import (
    REGRESSION_MODELS,
    fit_qsar_model,
    infer_task_type,
    models_for_task,
    predict_qsar_rows,
)


def test_infer_task_type_regression_vs_classification():
    y_reg = np.array([1.2, 3.4, 5.6, 7.8, 2.1, 9.0, 4.4, 6.2])
    assert infer_task_type(y_reg) == "regression"
    y_cls = np.array([0, 0, 1, 1, 0, 1, 1, 0], dtype=float)
    assert infer_task_type(y_cls) == "classification"


def test_regression_models_include_new_algorithms():
    keys = {k for k, _ in models_for_task("regression")}
    assert keys >= {
        "ridge",
        "lasso",
        "mlr",
        "pls",
        "knn",
        "svr",
        "random_forest",
        "gradient_boosting",
    }
    assert set(REGRESSION_MODELS) == keys


def _synthetic_regression_frame(n: int = 40, seed: int = 42) -> tuple[pd.DataFrame, list[int]]:
    rng = np.random.default_rng(seed)
    mw = rng.uniform(200, 500, size=n)
    logp = rng.uniform(-1, 5, size=n)
    activity = 0.02 * mw + 0.5 * logp + rng.normal(0, 0.5, size=n)
    df = pd.DataFrame({"MW": mw, "LogP": logp, "pIC50": activity})
    return df, list(range(n))


def test_fit_and_predict_numeric_regression():
    df, oids = _synthetic_regression_frame()
    result = fit_qsar_model(
        df=df,
        oids=oids,
        activity_column="pIC50",
        feature_columns=["MW", "LogP"],
        fp_choice=None,
        mol_rows=None,
        model_key="ridge",
        task_mode="regression",
        train_fraction=0.75,
        cv_folds=3,
        standardize=True,
    )
    assert result.task == "regression"
    assert result.n_train == len(oids)
    assert "R²" in result.metrics_text or "RMSE" in result.metrics_text
    preds = predict_qsar_rows(
        result.bundle,
        df=df,
        oids=oids,
        mol_rows=None,
        output_column="QSAR_pIC50",
    )
    assert len(preds) == len(oids)
    assert preds[0][1]["QSAR_pIC50"]


@pytest.mark.parametrize("model_key", ["lasso", "mlr", "pls", "knn", "svr"])
def test_fit_and_predict_new_regressors(model_key: str):
    df, oids = _synthetic_regression_frame()
    result = fit_qsar_model(
        df=df,
        oids=oids,
        activity_column="pIC50",
        feature_columns=["MW", "LogP"],
        fp_choice=None,
        mol_rows=None,
        model_key=model_key,
        task_mode="regression",
        train_fraction=0.75,
        cv_folds=3,
        standardize=True,
    )
    assert result.task == "regression"
    assert result.model_key == model_key
    assert result.n_features == 2
    preds = predict_qsar_rows(
        result.bundle,
        df=df,
        oids=oids,
        mol_rows=None,
        output_column=f"QSAR_{model_key}",
    )
    assert len(preds) == len(oids)
    assert all(np.isfinite(float(p[1][f"QSAR_{model_key}"])) for p in preds)


def test_custom_model_params_applied():
    from molmanager.analysis.qsar_models import default_model_params, param_specs_for_model

    assert "alpha" in default_model_params("ridge")
    assert any(s["key"] == "n_neighbors" for s in param_specs_for_model("knn"))

    df, oids = _synthetic_regression_frame()
    result = fit_qsar_model(
        df=df,
        oids=oids,
        activity_column="pIC50",
        feature_columns=["MW", "LogP"],
        fp_choice=None,
        mol_rows=None,
        model_key="ridge",
        task_mode="regression",
        train_fraction=0.75,
        cv_folds=3,
        standardize=True,
        model_params={"alpha": 10.0},
    )
    assert "alpha=10.0" in result.metrics_text
    assert float(result.bundle.model.alpha) == 10.0

    knn = fit_qsar_model(
        df=df,
        oids=oids,
        activity_column="pIC50",
        feature_columns=["MW", "LogP"],
        fp_choice=None,
        mol_rows=None,
        model_key="knn",
        task_mode="regression",
        train_fraction=0.75,
        cv_folds=3,
        standardize=True,
        model_params={"n_neighbors": 3, "weights": "uniform", "p": 1},
    )
    assert knn.bundle.model.n_neighbors == 3
    assert knn.bundle.model.weights == "uniform"
    assert knn.bundle.model.p == 1
