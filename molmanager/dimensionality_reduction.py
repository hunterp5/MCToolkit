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

"""Numeric matrix preparation and sklearn PCA / t-SNE / UMAP plus NumPy Kohonen SOM (no Qt)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from typing import Any

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class DimensionReductionResult:
    method: str
    x: list[float]
    y: list[float]
    oids: list[int]
    hover: list[str]
    title: str
    summary: str
    color_values: list[Any] | None = None
    color_label: str | None = None


def result_to_dict(result: DimensionReductionResult) -> dict:
    """Serialize a reduction result for session / UI state (no Qt)."""
    return asdict(result)


def subset_dimension_reduction_result(
    result: DimensionReductionResult,
    keep: frozenset[int] | None,
) -> DimensionReductionResult:
    """Keep coordinates for OIDs that are still visible in the table."""
    if keep is None:
        return result
    xs: list[float] = []
    ys: list[float] = []
    oids: list[int] = []
    hover: list[str] = []
    has_color = result.color_values is not None
    colors: list[Any] = []
    n_x = len(result.x)
    n_y = len(result.y)
    n_h = len(result.hover)
    n_c = len(result.color_values) if has_color else 0
    for i, oid in enumerate(result.oids):
        if int(oid) not in keep:
            continue
        oids.append(int(oid))
        xs.append(result.x[i] if i < n_x else 0.0)
        ys.append(result.y[i] if i < n_y else 0.0)
        hover.append(result.hover[i] if i < n_h else f"OID {oid}")
        if has_color:
            colors.append(result.color_values[i] if i < n_c else None)
    return replace(
        result,
        x=xs,
        y=ys,
        oids=oids,
        hover=hover,
        color_values=colors if has_color else None,
    )


def prepare_numeric_matrix(
    df: pd.DataFrame,
    feature_columns: list[str],
    *,
    drop_incomplete_rows: bool = True,
) -> tuple[np.ndarray, np.ndarray, list[int]]:
    """
    Return ``(X, row_indices_into_df, valid_positions)`` where row_indices map back to the
    input dataframe index labels (0..n-1 positions in the passed frame).
    """
    if not feature_columns:
        raise ValueError("Select at least one numeric column.")
    missing = [c for c in feature_columns if c not in df.columns]
    if missing:
        raise ValueError(f"Unknown column(s): {', '.join(missing)}")
    num = df[feature_columns].apply(pd.to_numeric, errors="coerce")
    if drop_incomplete_rows:
        mask = num.notna().all(axis=1)
        num = num.loc[mask]
        positions = [int(i) for i in np.where(mask.to_numpy())[0]]
    else:
        num = num.fillna(num.mean(numeric_only=True))
        positions = list(range(len(num)))
    if len(num) < 2:
        raise ValueError("Need at least two complete rows for dimensionality reduction.")
    if num.shape[1] < 1:
        raise ValueError("Need at least one feature column.")
    return num.to_numpy(dtype=float), num.index.to_numpy(), positions


def is_fingerprint_bitcount_column(name: str) -> bool:
    """True for descriptor columns that store on-bit counts, not full bit vectors."""
    n = (name or "").strip()
    if n.startswith("FP_"):
        return True
    lo = n.lower()
    return "morgan" in lo and "bit" in lo and lo.endswith("bits")


def _standardize(X: np.ndarray, standardize: bool) -> np.ndarray:
    if not standardize:
        return X
    from sklearn.preprocessing import StandardScaler

    return StandardScaler().fit_transform(X)


def _tsne_init_method(n_features: int) -> str:
    """PCA init requires at least two features for a 2D embedding."""
    return "pca" if int(n_features) >= 2 else "random"


def build_fingerprint_matrix(
    mol_rows: list[tuple[int, object]],
    fp_choice: str,
) -> tuple[np.ndarray, list[int]]:
    """Full bit-vector matrix from in-memory structures (same fingerprints as Cluster)."""
    from rdkit import DataStructs

    from .memory_guards import check_fp_matrix_workload
    from .workers.fingerprint_similarity import fingerprint_bitvect_for_ui_choice
    from .rdkit_fingerprints import fingerprint_bitvect_for_row

    n_candidates = sum(1 for _oid, mol in mol_rows if mol is not None)
    guard = check_fp_matrix_workload(n_candidates, n_bits=2048)
    if not guard.ok:
        raise ValueError(guard.message)

    oids: list[int] = []
    rows: list[np.ndarray] = []
    for oid, mol in mol_rows:
        if mol is None:
            continue
        try:
            fp = fingerprint_bitvect_for_row(int(oid), mol, fp_choice)
            if fp is None:
                fp = fingerprint_bitvect_for_ui_choice(mol, fp_choice)
        except Exception:
            fp = None
        if fp is None:
            continue
        arr = np.zeros((int(fp.GetNumBits()),), dtype=np.float64)
        DataStructs.ConvertToNumpyArray(fp, arr)
        oids.append(int(oid))
        rows.append(arr)
    if len(rows) < 2:
        raise ValueError(
            "Need at least two rows with valid fingerprints in this scope. "
            "Check the structure source and that rows have parseable structures."
        )
    return np.vstack(rows), oids


def run_pca(
    X: np.ndarray,
    *,
    standardize: bool = True,
    n_components: int = 2,
) -> tuple[np.ndarray, np.ndarray, str]:
    from sklearn.decomposition import PCA

    Xs = _standardize(X, standardize)
    n_samples, n_features = Xs.shape
    n_comp = max(1, min(int(n_components), n_samples, n_features))
    pca = PCA(n_components=n_comp)
    coords_full = pca.fit_transform(Xs)
    ratios = pca.explained_variance_ratio_
    if coords_full.shape[1] >= 2:
        coords = coords_full[:, :2]
    else:
        coords = np.column_stack([coords_full[:, 0], np.zeros(coords_full.shape[0])])
    lines = [
        f"Samples: {n_samples}",
        f"Features: {n_features}",
        f"Components computed: {n_comp}",
        "",
        "Explained variance ratio:",
    ]
    for i, r in enumerate(ratios, start=1):
        lines.append(f"  PC{i}: {100.0 * float(r):.2f}%")
    lines.append(f"  Cumulative (PC1–PC{n_comp}): {100.0 * float(np.sum(ratios)):.2f}%")
    if n_features == 1:
        lines.append("")
        lines.append("Only one feature: plot shows PC1 on X and 0 on Y.")
    elif n_comp > 2:
        lines.append("")
        lines.append("Plot shows PC1 vs PC2.")
    return coords, ratios, "\n".join(lines)


def run_tsne(
    X: np.ndarray,
    *,
    standardize: bool = True,
    perplexity: float = 30.0,
    learning_rate: float = 200.0,
    max_iter: int = 1000,
    random_state: int = 42,
    max_points: int | None = 2500,
) -> tuple[np.ndarray, np.ndarray, str]:
    from sklearn.manifold import TSNE

    n_samples = X.shape[0]
    used_idx = np.arange(n_samples)
    note = ""
    if max_points is not None and n_samples > int(max_points):
        rng = np.random.default_rng(int(random_state))
        used_idx = np.sort(rng.choice(n_samples, size=int(max_points), replace=False))
        note = f"Subsampled {int(max_points)} of {n_samples} rows (fixed seed {random_state}).\n\n"

    Xs = _standardize(X[used_idx], standardize)
    n_used = Xs.shape[0]
    perp = float(perplexity)
    perp = max(5.0, min(perp, float(n_used - 1)))
    init = _tsne_init_method(Xs.shape[1])
    tsne = TSNE(
        n_components=2,
        perplexity=perp,
        learning_rate=float(learning_rate),
        max_iter=int(max_iter),
        init=init,
        random_state=int(random_state),
    )
    coords = tsne.fit_transform(Xs)
    summary = (
        f"{note}"
        f"Samples used: {n_used}\n"
        f"Features: {Xs.shape[1]}\n"
        f"t-SNE init: {init}\n"
        f"Perplexity: {perp:.1f}\n"
        f"Learning rate: {learning_rate}\n"
        f"Iterations: {max_iter}\n"
        f"Random state: {random_state}"
    )
    return coords, used_idx, summary


def run_umap(
    X: np.ndarray,
    *,
    standardize: bool = True,
    n_neighbors: int = 15,
    min_dist: float = 0.1,
    random_state: int = 42,
    max_points: int | None = 2500,
) -> tuple[np.ndarray, np.ndarray, str]:
    try:
        import umap
    except ImportError as exc:
        raise ImportError(
            "UMAP requires the umap-learn package. Install with: pip install umap-learn"
        ) from exc

    n_samples = X.shape[0]
    used_idx = np.arange(n_samples)
    note = ""
    if max_points is not None and n_samples > int(max_points):
        rng = np.random.default_rng(int(random_state))
        used_idx = np.sort(rng.choice(n_samples, size=int(max_points), replace=False))
        note = f"Subsampled {int(max_points)} of {n_samples} rows (fixed seed {random_state}).\n\n"

    Xs = _standardize(X[used_idx], standardize)
    n_used = Xs.shape[0]
    n_neigh = max(2, min(int(n_neighbors), n_used - 1))
    reducer = umap.UMAP(
        n_components=2,
        n_neighbors=n_neigh,
        min_dist=float(min_dist),
        random_state=int(random_state),
        n_jobs=1,
    )
    coords = reducer.fit_transform(Xs)
    summary = (
        f"{note}"
        f"Samples used: {n_used}\n"
        f"Features: {Xs.shape[1]}\n"
        f"n_neighbors: {n_neigh}\n"
        f"min_dist: {min_dist}\n"
        f"Random state: {random_state}"
    )
    return coords, used_idx, summary


def run_som(
    X: np.ndarray,
    *,
    standardize: bool = True,
    grid_width: int = 10,
    grid_height: int = 10,
    n_epochs: int = 50,
    learning_rate: float = 0.5,
    sigma: float | None = None,
    random_state: int = 42,
    max_points: int | None = 2500,
    jitter: float = 0.35,
) -> tuple[np.ndarray, np.ndarray, str]:
    """
    Train a rectangular Kohonen self-organizing map and return BMU grid coordinates.

    Plot coordinates are BMU column (X) and row (Y), with optional jitter so points that
    share a node are slightly separated. No extra package dependency (NumPy only).
    """
    n_samples = X.shape[0]
    used_idx = np.arange(n_samples)
    note = ""
    if max_points is not None and n_samples > int(max_points):
        rng = np.random.default_rng(int(random_state))
        used_idx = np.sort(rng.choice(n_samples, size=int(max_points), replace=False))
        note = f"Subsampled {int(max_points)} of {n_samples} rows (fixed seed {random_state}).\n\n"

    Xs = _standardize(X[used_idx], standardize).astype(np.float64, copy=False)
    n_used, n_features = Xs.shape
    gw = max(2, int(grid_width))
    gh = max(2, int(grid_height))
    n_nodes = gw * gh
    if n_nodes > 2_500:
        raise ValueError(
            f"SOM grid {gw}×{gh} ({n_nodes:,} nodes) exceeds 2,500. Reduce map width/height."
        )
    epochs = max(1, int(n_epochs))
    lr0 = max(1e-6, float(learning_rate))
    sigma0 = float(sigma) if sigma is not None and float(sigma) > 0 else max(gw, gh) / 2.0
    sigma0 = max(0.5, sigma0)

    rng = np.random.default_rng(int(random_state))
    # Sample subspace for weight init so maps start near the data cloud.
    init_n = min(n_used, max(n_nodes, 8))
    init_pick = rng.choice(n_used, size=init_n, replace=False)
    weights = (
        Xs[init_pick][rng.integers(0, init_n, size=n_nodes)].reshape(gh, gw, n_features).copy()
    )

    yy, xx = np.indices((gh, gw))
    order = np.arange(n_used)
    for epoch in range(epochs):
        frac = epoch / max(1, epochs - 1) if epochs > 1 else 1.0
        lr = lr0 * (1.0 - frac)
        sig = max(0.35, sigma0 * (1.0 - frac))
        rng.shuffle(order)
        inv_2sig2 = 1.0 / (2.0 * sig * sig)
        for i in order:
            sample = Xs[i]
            diff = weights - sample
            dist2 = np.einsum("ijk,ijk->ij", diff, diff)
            by, bx = np.unravel_index(int(np.argmin(dist2)), (gh, gw))
            d2 = (yy - by) ** 2 + (xx - bx) ** 2
            neigh = np.exp(-d2 * inv_2sig2)[..., None]
            weights += lr * neigh * (sample - weights)

    flat_w = weights.reshape(n_nodes, n_features)
    # Batched BMU assignment
    # ||x - w||^2 = ||x||^2 + ||w||^2 - 2 x·w
    x_sq = np.einsum("ij,ij->i", Xs, Xs)[:, None]
    w_sq = np.einsum("ij,ij->i", flat_w, flat_w)[None, :]
    dots = Xs @ flat_w.T
    bmu_flat = np.argmin(x_sq + w_sq - 2.0 * dots, axis=1)
    bmu_y = bmu_flat // gw
    bmu_x = bmu_flat % gw
    if jitter and float(jitter) > 0:
        j = float(jitter)
        coords = np.column_stack(
            [
                bmu_x.astype(float) + rng.uniform(-j, j, size=n_used),
                bmu_y.astype(float) + rng.uniform(-j, j, size=n_used),
            ]
        )
    else:
        coords = np.column_stack([bmu_x.astype(float), bmu_y.astype(float)])

    occupied = int(np.unique(bmu_flat).size)
    counts = np.bincount(bmu_flat, minlength=n_nodes)
    summary = (
        f"{note}"
        f"Samples used: {n_used}\n"
        f"Features: {n_features}\n"
        f"Grid: {gw} × {gh} ({n_nodes} nodes)\n"
        f"Occupied nodes: {occupied} ({100.0 * occupied / n_nodes:.1f}%)\n"
        f"Max node occupancy: {int(counts.max())}\n"
        f"Epochs: {epochs}\n"
        f"Initial learning rate: {lr0}\n"
        f"Initial sigma: {sigma0:.2f}\n"
        f"Random state: {random_state}\n"
        f"Plot: BMU column (X) vs row (Y)" + (" with jitter" if jitter else "")
    )
    return coords, used_idx, summary


def build_reduction_result(
    method: str,
    coords: np.ndarray,
    df: pd.DataFrame,
    oids: list[int],
    row_indices: np.ndarray,
    *,
    title: str,
    summary: str,
    color_column: str | None = None,
) -> DimensionReductionResult:
    """Map coordinates back to table oids and optional color column."""
    if len(oids) != len(df):
        raise ValueError("oids must align with dataframe rows.")
    pos_arr = np.asarray(row_indices, dtype=int)
    if coords.shape[0] != len(pos_arr):
        raise ValueError("coordinate count must match row index count.")
    if len(pos_arr) and (int(pos_arr.min()) < 0 or int(pos_arr.max()) >= len(oids)):
        raise ValueError("row index out of range for oid list.")
    xs = coords[:, 0].tolist()
    ys = coords[:, 1].tolist()
    out_oids: list[int] = []
    hover: list[str] = []
    color_values: list[Any] | None = [] if color_column else None

    for j in range(coords.shape[0]):
        p = int(pos_arr[j])
        oid = int(oids[p])
        out_oids.append(oid)
        parts = [f"OID {oid}"]
        if color_column and color_column in df.columns:
            cv = df.iloc[p][color_column]
            parts.append(f"{color_column}: {cv}")
            if color_values is not None:
                color_values.append(cv)
        hover.append("<br>".join(parts))

    return DimensionReductionResult(
        method=method,
        x=xs,
        y=ys,
        oids=out_oids,
        hover=hover,
        title=title,
        summary=summary,
        color_values=color_values,
        color_label=color_column,
    )
