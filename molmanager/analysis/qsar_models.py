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

"""QSAR model fitting and prediction (scikit-learn; no Qt)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

import numpy as np
import pandas as pd

TaskKind = Literal["regression", "classification"]

REGRESSION_MODELS: dict[str, str] = {
    "ridge": "Ridge regression",
    "lasso": "Lasso regression",
    "mlr": "Multiple linear regression (MLR)",
    "pls": "PLS regression",
    "knn": "k-nearest neighbors (KNN)",
    "svr": "Support vector regression (SVR)",
    "random_forest": "Random forest",
    "gradient_boosting": "Gradient boosting",
}
CLASSIFICATION_MODELS: dict[str, str] = {
    "logistic": "Logistic regression",
    "random_forest": "Random forest",
    "gradient_boosting": "Gradient boosting",
    "svm": "Support vector machine (SVM)",
}

# Tunable hyperparameters shown in the QSAR dialog (per algorithm key).
# Each spec: key, label, kind (float|int|choice|bool), default, and optional bounds/choices.
MODEL_PARAM_SPECS: dict[str, list[dict[str, Any]]] = {
    "ridge": [
        {
            "key": "alpha",
            "label": "Alpha (L2)",
            "kind": "float",
            "default": 1.0,
            "min": 1e-6,
            "max": 1e6,
            "decimals": 6,
            "tooltip": "L2 regularization strength (larger = stronger shrinkage).",
        },
    ],
    "lasso": [
        {
            "key": "alpha",
            "label": "Alpha (L1)",
            "kind": "float",
            "default": 0.1,
            "min": 1e-6,
            "max": 100.0,
            "decimals": 6,
            "tooltip": "L1 regularization strength (larger = sparser coefficients).",
        },
        {
            "key": "max_iter",
            "label": "Max iterations",
            "kind": "int",
            "default": 5000,
            "min": 100,
            "max": 100000,
        },
    ],
    "mlr": [
        {
            "key": "fit_intercept",
            "label": "Fit intercept",
            "kind": "bool",
            "default": True,
            "tooltip": "Whether to calculate the intercept for this model.",
        },
    ],
    "pls": [
        {
            "key": "n_components",
            "label": "Components",
            "kind": "int",
            "default": 2,
            "min": 1,
            "max": 50,
            "tooltip": "Latent components (capped at training samples/features during fit).",
        },
    ],
    "knn": [
        {
            "key": "n_neighbors",
            "label": "Neighbors (k)",
            "kind": "int",
            "default": 5,
            "min": 1,
            "max": 200,
            "tooltip": "Number of neighbors (capped below training-set size during fit).",
        },
        {
            "key": "weights",
            "label": "Weights",
            "kind": "choice",
            "default": "distance",
            "choices": [("uniform", "Uniform"), ("distance", "Distance")],
        },
        {
            "key": "p",
            "label": "Minkowski p",
            "kind": "int",
            "default": 2,
            "min": 1,
            "max": 5,
            "tooltip": "Distance metric power (1 = Manhattan, 2 = Euclidean).",
        },
    ],
    "svr": [
        {
            "key": "kernel",
            "label": "Kernel",
            "kind": "choice",
            "default": "rbf",
            "choices": [
                ("rbf", "RBF"),
                ("linear", "Linear"),
                ("poly", "Polynomial"),
                ("sigmoid", "Sigmoid"),
            ],
        },
        {
            "key": "C",
            "label": "C",
            "kind": "float",
            "default": 1.0,
            "min": 1e-4,
            "max": 1e4,
            "decimals": 4,
            "tooltip": "Regularization parameter (larger = less regularization).",
        },
        {
            "key": "epsilon",
            "label": "Epsilon",
            "kind": "float",
            "default": 0.1,
            "min": 0.0,
            "max": 10.0,
            "decimals": 4,
            "tooltip": "Epsilon-tube width within which no penalty is associated.",
        },
        {
            "key": "gamma",
            "label": "Gamma",
            "kind": "choice",
            "default": "scale",
            "choices": [("scale", "scale"), ("auto", "auto")],
            "tooltip": "Kernel coefficient for RBF / poly / sigmoid.",
        },
    ],
    "random_forest": [
        {
            "key": "n_estimators",
            "label": "Trees",
            "kind": "int",
            "default": 200,
            "min": 10,
            "max": 2000,
        },
        {
            "key": "max_depth",
            "label": "Max depth (0 = none)",
            "kind": "int",
            "default": 0,
            "min": 0,
            "max": 100,
            "tooltip": "Maximum tree depth; 0 means unlimited.",
        },
        {
            "key": "min_samples_leaf",
            "label": "Min samples / leaf",
            "kind": "int",
            "default": 1,
            "min": 1,
            "max": 100,
        },
    ],
    "gradient_boosting": [
        {
            "key": "n_estimators",
            "label": "Estimators",
            "kind": "int",
            "default": 100,
            "min": 10,
            "max": 2000,
        },
        {
            "key": "learning_rate",
            "label": "Learning rate",
            "kind": "float",
            "default": 0.1,
            "min": 0.001,
            "max": 1.0,
            "decimals": 4,
        },
        {
            "key": "max_depth",
            "label": "Max depth",
            "kind": "int",
            "default": 3,
            "min": 1,
            "max": 20,
        },
    ],
    "logistic": [
        {
            "key": "C",
            "label": "C (inverse regularization)",
            "kind": "float",
            "default": 1.0,
            "min": 1e-4,
            "max": 1e4,
            "decimals": 4,
        },
        {
            "key": "penalty",
            "label": "Penalty",
            "kind": "choice",
            "default": "l2",
            "choices": [("l2", "L2"), ("l1", "L1"), ("none", "None")],
        },
        {
            "key": "max_iter",
            "label": "Max iterations",
            "kind": "int",
            "default": 3000,
            "min": 100,
            "max": 50000,
        },
    ],
    "svm": [
        {
            "key": "kernel",
            "label": "Kernel",
            "kind": "choice",
            "default": "linear",
            "choices": [
                ("linear", "Linear"),
                ("rbf", "RBF"),
                ("poly", "Polynomial"),
                ("sigmoid", "Sigmoid"),
            ],
        },
        {
            "key": "C",
            "label": "C",
            "kind": "float",
            "default": 1.0,
            "min": 1e-4,
            "max": 1e4,
            "decimals": 4,
        },
        {
            "key": "gamma",
            "label": "Gamma",
            "kind": "choice",
            "default": "scale",
            "choices": [("scale", "scale"), ("auto", "auto")],
        },
    ],
}


def default_model_params(model_key: str) -> dict[str, Any]:
    """Default hyperparameter values for *model_key*."""
    out: dict[str, Any] = {}
    for spec in MODEL_PARAM_SPECS.get(str(model_key), []):
        out[str(spec["key"])] = spec["default"]
    return out


def param_specs_for_model(model_key: str) -> list[dict[str, Any]]:
    """Return UI parameter specs for *model_key* (may be empty)."""
    return list(MODEL_PARAM_SPECS.get(str(model_key), []))


@dataclass(frozen=True)
class QSARModelBundle:
    """Fitted model and preprocessing state for predictions on new rows."""

    task: TaskKind
    model_key: str
    activity_column: str
    feature_columns: tuple[str, ...] | None
    fp_choice: str | None
    n_numeric_features: int
    standardize_numeric: bool
    model: Any
    scaler: Any | None
    class_labels: tuple[Any, ...] | None = None


@dataclass(frozen=True)
class QSARFitResult:
    task: TaskKind
    model_key: str
    activity_column: str
    metrics_text: str
    bundle: QSARModelBundle
    n_train: int
    n_features: int
    top_features_text: str = ""


def infer_task_type(y: np.ndarray, *, force: TaskKind | None = None) -> TaskKind:
    """Choose regression vs classification from activity values."""
    if force is not None:
        return force
    y = np.asarray(y, dtype=float)
    finite = y[np.isfinite(y)]
    if finite.size < 3:
        return "regression"
    rounded = np.round(finite, 6)
    uniq = np.unique(rounded)
    if len(uniq) <= 2:
        return "classification"
    if len(uniq) <= 12 and np.allclose(uniq, np.round(uniq)):
        if len(uniq) / max(finite.size, 1) < 0.35:
            return "classification"
    return "regression"


def _activity_and_features(
    *,
    df: pd.DataFrame,
    oids: list[int],
    activity_column: str,
    feature_columns: list[str] | None,
    mol_rows: list[tuple[int, object]] | None,
    fp_choice: str | None,
    min_rows: int = 8,
) -> tuple[np.ndarray, np.ndarray, list[str] | None, int, str]:
    """Build X and y for QSAR from numeric columns, fingerprints, or both."""
    from ..descriptors.ml_feature_matrix import build_combined_feature_matrix

    if activity_column not in df.columns:
        raise ValueError(f"Activity column not found: {activity_column}")
    built = build_combined_feature_matrix(
        df=df,
        oids=oids,
        feature_columns=feature_columns,
        mol_rows=mol_rows,
        fp_choice=fp_choice,
        min_rows=min_rows,
        activity_column=activity_column,
    )
    y_all = pd.to_numeric(df[activity_column], errors="coerce").to_numpy(dtype=float)
    y = np.asarray([float(y_all[p]) for p in built.df_positions], dtype=float)
    feat_names = built.feature_names if built.n_numeric_features > 0 else None
    return built.X, y, feat_names, built.n_numeric_features, built.summary


def _prepare_labels(y: np.ndarray, task: TaskKind) -> tuple[np.ndarray, tuple[Any, ...] | None]:
    if task == "regression":
        return y.astype(float), None
    rounded = np.round(y, 6)
    labels = tuple(sorted(np.unique(rounded).tolist()))
    label_to_i = {lab: i for i, lab in enumerate(labels)}
    y_cls = np.asarray([label_to_i[v] for v in rounded], dtype=int)
    return y_cls, labels


def _merge_model_params(model_key: str, params: dict[str, Any] | None) -> dict[str, Any]:
    """Defaults for *model_key*, overridden by any keys present in *params*."""
    merged = default_model_params(model_key)
    if not params:
        return merged
    known = set(merged) | {str(s["key"]) for s in MODEL_PARAM_SPECS.get(str(model_key), [])}
    for key, value in params.items():
        if str(key) in known:
            merged[str(key)] = value
    return merged


def _rf_max_depth(params: dict[str, Any]) -> int | None:
    depth = int(params.get("max_depth", 0) or 0)
    return None if depth <= 0 else depth


def _make_model(
    task: TaskKind,
    model_key: str,
    params: dict[str, Any] | None = None,
) -> Any:
    p = _merge_model_params(model_key, params)
    if task == "regression":
        if model_key == "ridge":
            from sklearn.linear_model import Ridge

            return Ridge(alpha=float(p["alpha"]))
        if model_key == "lasso":
            from sklearn.linear_model import Lasso

            return Lasso(
                alpha=float(p["alpha"]),
                max_iter=int(p["max_iter"]),
                random_state=42,
            )
        if model_key == "mlr":
            from sklearn.linear_model import LinearRegression

            return LinearRegression(fit_intercept=bool(p.get("fit_intercept", True)))
        if model_key == "pls":
            from sklearn.cross_decomposition import PLSRegression

            # n_components is capped at fit time by n_samples / n_features.
            return PLSRegression(n_components=int(p["n_components"]), scale=False)
        if model_key == "knn":
            from sklearn.neighbors import KNeighborsRegressor

            return KNeighborsRegressor(
                n_neighbors=int(p["n_neighbors"]),
                weights=str(p.get("weights") or "distance"),
                p=int(p.get("p", 2)),
            )
        if model_key == "svr":
            from sklearn.svm import SVR

            return SVR(
                kernel=str(p.get("kernel") or "rbf"),
                C=float(p["C"]),
                epsilon=float(p["epsilon"]),
                gamma=str(p.get("gamma") or "scale"),
            )
        if model_key == "random_forest":
            from sklearn.ensemble import RandomForestRegressor

            return RandomForestRegressor(
                n_estimators=int(p["n_estimators"]),
                max_depth=_rf_max_depth(p),
                min_samples_leaf=int(p.get("min_samples_leaf", 1)),
                random_state=42,
                n_jobs=-1,
            )
        if model_key == "gradient_boosting":
            from sklearn.ensemble import GradientBoostingRegressor

            return GradientBoostingRegressor(
                n_estimators=int(p["n_estimators"]),
                learning_rate=float(p["learning_rate"]),
                max_depth=int(p["max_depth"]),
                random_state=42,
            )
        raise ValueError(f"Unknown regression model: {model_key}")
    if model_key == "logistic":
        from sklearn.linear_model import LogisticRegression

        penalty = str(p.get("penalty") or "l2")
        kwargs: dict[str, Any] = {
            "C": float(p["C"]),
            "max_iter": int(p["max_iter"]),
            "random_state": 42,
        }
        if penalty == "none":
            kwargs["penalty"] = None
        elif penalty == "l1":
            kwargs["penalty"] = "l1"
            kwargs["solver"] = "saga"
        else:
            kwargs["penalty"] = "l2"
        return LogisticRegression(**kwargs)
    if model_key == "random_forest":
        from sklearn.ensemble import RandomForestClassifier

        return RandomForestClassifier(
            n_estimators=int(p["n_estimators"]),
            max_depth=_rf_max_depth(p),
            min_samples_leaf=int(p.get("min_samples_leaf", 1)),
            random_state=42,
            n_jobs=-1,
        )
    if model_key == "gradient_boosting":
        from sklearn.ensemble import GradientBoostingClassifier

        return GradientBoostingClassifier(
            n_estimators=int(p["n_estimators"]),
            learning_rate=float(p["learning_rate"]),
            max_depth=int(p["max_depth"]),
            random_state=42,
        )
    if model_key == "svm":
        from sklearn.svm import SVC

        return SVC(
            kernel=str(p.get("kernel") or "linear"),
            C=float(p["C"]),
            gamma=str(p.get("gamma") or "scale"),
            random_state=42,
        )
    raise ValueError(f"Unknown classification model: {model_key}")


def _scale_fit(
    X: np.ndarray, *, standardize_numeric: bool, n_numeric: int
) -> tuple[np.ndarray, Any | None]:
    from ..descriptors.ml_feature_matrix import standardize_feature_matrix

    return standardize_feature_matrix(X, n_numeric, enabled=standardize_numeric, fit=True)


def _scale_apply(X: np.ndarray, scaler: Any | None, *, n_numeric: int) -> np.ndarray:
    from ..descriptors.ml_feature_matrix import standardize_feature_matrix

    out, _ = standardize_feature_matrix(
        X, n_numeric, enabled=scaler is not None, scaler_state=scaler, fit=False
    )
    return out


def _regression_metrics(y: np.ndarray, y_hat: np.ndarray) -> dict[str, float]:
    y = np.asarray(y, dtype=float)
    y_hat = np.asarray(y_hat, dtype=float)
    n = len(y)
    ss_res = float(np.sum((y - y_hat) ** 2))
    y_mean = float(np.mean(y))
    ss_tot = float(np.sum((y - y_mean) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else float("nan")
    rmse = float(np.sqrt(ss_res / n)) if n else float("nan")
    mae = float(np.mean(np.abs(y - y_hat))) if n else float("nan")
    return {"r2": r2, "rmse": rmse, "mae": mae}


def _classification_metrics(y: np.ndarray, y_hat: np.ndarray) -> dict[str, float]:
    from sklearn.metrics import accuracy_score, balanced_accuracy_score

    return {
        "accuracy": float(accuracy_score(y, y_hat)),
        "balanced_accuracy": float(balanced_accuracy_score(y, y_hat)),
    }


def _top_feature_lines(
    model: Any,
    feature_names: list[str] | None,
    *,
    n: int = 12,
) -> str:
    if feature_names is None:
        return ""
    scores: np.ndarray | None = None
    imp = getattr(model, "feature_importances_", None)
    if imp is not None and len(feature_names) == len(imp):
        scores = np.asarray(imp, dtype=float)
    else:
        coef = getattr(model, "coef_", None)
        if coef is not None:
            arr = np.asarray(coef, dtype=float)
            if arr.ndim == 2:
                # Linear models: (1, n_features) or PLS: (n_features, n_targets)
                if arr.shape[0] == 1:
                    arr = arr.ravel()
                elif arr.shape[1] == 1:
                    arr = arr.ravel()
                elif arr.shape[0] == len(feature_names):
                    arr = np.sum(np.abs(arr), axis=1)
                elif arr.shape[1] == len(feature_names):
                    arr = np.sum(np.abs(arr), axis=0)
                else:
                    arr = np.abs(arr).ravel()
            else:
                arr = arr.ravel()
            if len(feature_names) == len(arr):
                scores = np.abs(arr)
    if scores is None:
        return ""
    order = np.argsort(scores)[::-1][:n]
    lines = []
    for i in order:
        lines.append(f"  {feature_names[i]}: {float(scores[i]):.4f}")
    return "\n".join(lines) if lines else ""


def _prepare_model_for_x(model: Any, X: np.ndarray) -> Any:
    """Adjust model hyperparameters that depend on matrix shape (e.g. PLS components)."""
    name = type(model).__name__
    if name == "PLSRegression":
        max_c = max(1, min(int(X.shape[0]) - 1, int(X.shape[1])))
        want = int(getattr(model, "n_components", 2) or 2)
        model.set_params(n_components=max(1, min(want, max_c)))
    if name == "KNeighborsRegressor":
        n_neighbors = int(getattr(model, "n_neighbors", 5) or 5)
        model.set_params(n_neighbors=max(1, min(n_neighbors, max(1, int(X.shape[0]) - 1))))
    return model


def fit_qsar_model(
    *,
    df: pd.DataFrame,
    oids: list[int],
    activity_column: str,
    feature_columns: list[str] | None,
    fp_choice: str | None,
    mol_rows: list[tuple[int, object]] | None,
    model_key: str,
    task_mode: str,
    train_fraction: float,
    cv_folds: int,
    standardize: bool,
    model_params: dict[str, Any] | None = None,
) -> QSARFitResult:
    """
    Fit a QSAR model on rows with known activity; return metrics and a prediction bundle.
    """
    from sklearn.model_selection import cross_val_score, train_test_split

    X, y_raw, feat_names, n_numeric, feat_summary = _activity_and_features(
        df=df,
        oids=oids,
        activity_column=activity_column,
        feature_columns=feature_columns,
        mol_rows=mol_rows,
        fp_choice=fp_choice,
    )
    standardize_numeric = bool(standardize and n_numeric > 0)

    force_task: TaskKind | None = None
    if task_mode == "regression":
        force_task = "regression"
    elif task_mode == "classification":
        force_task = "classification"
    task = infer_task_type(y_raw, force=force_task)
    y, class_labels = _prepare_labels(y_raw, task)

    if task == "classification" and class_labels is not None and len(class_labels) < 2:
        raise ValueError("Classification needs at least two distinct activity classes.")

    Xs, scaler = _scale_fit(X, standardize_numeric=standardize_numeric, n_numeric=n_numeric)

    test_size = max(0.1, min(0.4, 1.0 - float(train_fraction)))
    stratify = y if task == "classification" and len(np.unique(y)) > 1 else None
    try:
        X_train, X_test, y_train, y_test = train_test_split(
            Xs,
            y,
            test_size=test_size,
            random_state=42,
            stratify=stratify,
        )
    except ValueError as exc:
        raise ValueError(
            f"Could not split data for training (too few samples per class?). Details: {exc}"
        ) from exc

    resolved_params = _merge_model_params(model_key, model_params)
    model = _prepare_model_for_x(_make_model(task, model_key, resolved_params), X_train)
    model.fit(X_train, y_train)
    y_hat = np.asarray(model.predict(X_test)).ravel()

    lines: list[str] = [feat_summary, ""]
    lines.append(f"Task: {task}")
    lines.append(f"Model: {_model_label(task, model_key)}")
    if resolved_params:
        param_bits = ", ".join(f"{k}={v}" for k, v in resolved_params.items())
        lines.append(f"Parameters: {param_bits}")
    lines.append(f"Training rows: {len(y)}  |  Features: {X.shape[1]}")
    lines.append(f"Hold-out fraction: {test_size:.0%}  ({len(y_test)} test rows)")
    lines.append("")

    if task == "regression":
        m = _regression_metrics(y_test, y_hat)
        lines.append("Hold-out metrics:")
        lines.append(f"  R² = {m['r2']:.4f}")
        lines.append(f"  RMSE = {m['rmse']:.4f}")
        lines.append(f"  MAE = {m['mae']:.4f}")
        scoring = "r2"
    else:
        m = _classification_metrics(y_test, y_hat)
        lines.append("Hold-out metrics:")
        lines.append(f"  Accuracy = {m['accuracy']:.4f}")
        lines.append(f"  Balanced accuracy = {m['balanced_accuracy']:.4f}")
        if class_labels is not None:
            lines.append(f"  Classes: {', '.join(str(c) for c in class_labels)}")
        scoring = "accuracy"

    folds = max(2, min(int(cv_folds), len(y_train)))
    if len(y_train) >= folds + 1:
        try:
            cv_model = _prepare_model_for_x(_make_model(task, model_key, resolved_params), X_train)
            cv_scores = cross_val_score(
                cv_model, X_train, y_train, cv=folds, scoring=scoring, n_jobs=-1
            )
            lines.append("")
            lines.append(f"{folds}-fold CV on training set ({scoring}):")
            lines.append(
                f"  mean = {float(np.mean(cv_scores)):.4f}  std = {float(np.std(cv_scores)):.4f}"
            )
        except Exception as exc:
            lines.append("")
            lines.append(f"Cross-validation skipped: {exc}")

    top_feat_eval = _top_feature_lines(model, feat_names)

    deploy = _prepare_model_for_x(_make_model(task, model_key, resolved_params), Xs)
    deploy.fit(Xs, y)
    top_feat = _top_feature_lines(deploy, feat_names) or top_feat_eval
    if top_feat:
        lines.append("")
        lines.append("Top feature importances (full-data model):")
        lines.append(top_feat)
    bundle = QSARModelBundle(
        task=task,
        model_key=model_key,
        activity_column=activity_column,
        feature_columns=tuple(feature_columns) if feature_columns else None,
        fp_choice=fp_choice,
        n_numeric_features=n_numeric,
        standardize_numeric=standardize_numeric,
        model=deploy,
        scaler=scaler,
        class_labels=class_labels,
    )

    return QSARFitResult(
        task=task,
        model_key=model_key,
        activity_column=activity_column,
        metrics_text="\n".join(lines),
        bundle=bundle,
        n_train=len(y),
        n_features=int(X.shape[1]),
        top_features_text=top_feat,
    )


def _model_label(task: TaskKind, model_key: str) -> str:
    if task == "regression":
        return REGRESSION_MODELS.get(model_key, model_key)
    return CLASSIFICATION_MODELS.get(model_key, model_key)


def predict_qsar_rows(
    bundle: QSARModelBundle,
    *,
    df: pd.DataFrame,
    oids: list[int],
    mol_rows: list[tuple[int, object]] | None,
    output_column: str | None = None,
) -> list[tuple[int, dict[str, str]]]:
    """Predict activity for all in-scope rows with valid features."""
    out_col = (output_column or "").strip() or f"QSAR_{bundle.activity_column}"

    from ..descriptors.ml_feature_matrix import build_combined_feature_matrix

    if not bundle.feature_columns and not bundle.fp_choice:
        return []
    try:
        built = build_combined_feature_matrix(
            df=df,
            oids=oids,
            feature_columns=list(bundle.feature_columns) if bundle.feature_columns else None,
            mol_rows=mol_rows,
            fp_choice=bundle.fp_choice,
            min_rows=1,
        )
    except ValueError:
        return []
    X = built.X
    pred_oids = built.oids

    Xs = _scale_apply(X, bundle.scaler, n_numeric=bundle.n_numeric_features)
    raw = np.asarray(bundle.model.predict(Xs)).ravel()
    results: list[tuple[int, dict[str, str]]] = []
    if bundle.task == "classification" and bundle.class_labels is not None:
        for oid, pred_i in zip(pred_oids, raw):
            lab = bundle.class_labels[int(pred_i)]
            results.append((int(oid), {out_col: str(lab)}))
    else:
        for oid, val in zip(pred_oids, raw):
            results.append((int(oid), {out_col: f"{float(val):.6g}"}))
    return results


def models_for_task(task: TaskKind) -> list[tuple[str, str]]:
    """Return (key, label) pairs for UI combo."""
    if task == "regression":
        return list(REGRESSION_MODELS.items())
    return list(CLASSIFICATION_MODELS.items())
