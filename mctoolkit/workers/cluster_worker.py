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

"""Cluster table rows by molecular fingerprint (scikit-learn + RDKit Butina / Leader sphere exclusion)."""

from __future__ import annotations

import logging
import threading
from collections.abc import Sequence

import numpy as np
from PySide6.QtCore import QRunnable
from rdkit import Chem
from rdkit import DataStructs
from rdkit.ML.Cluster import Butina
from rdkit.SimDivFilters.rdSimDivPickers import LeaderPicker

from .fingerprint_similarity import fingerprint_bitvect_for_ui_choice
from ..chem.molecule_conversion import mol_from_job_payload
from ..chem.rdkit_fingerprints import fingerprint_bitvect_for_row
from .signals import emit_partial_results_if_cancelled

logger = logging.getLogger(__name__)


_SKLEARN_CLUSTER_METHODS = frozenset({"kmeans", "agglomerative", "dbscan"})

# Combo labels (and explore-table short names) for each worker method key.
CLUSTER_METHOD_LABELS: tuple[tuple[str, str], ...] = (
    ("kmeans", "K-Means"),
    ("agglomerative", "Agglomerative"),
    ("dbscan", "DBSCAN (cosine)"),
    ("butina", "Butina (Tanimoto distance)"),
    ("sphere_exclusion", "Sphere exclusion (RDKit Leader)"),
    ("jarvis_patrick", "Jarvis-Patrick"),
)
CLUSTER_METHOD_SHORT_LABELS: dict[str, str] = {
    "kmeans": "K-Means",
    "agglomerative": "Agglomerative",
    "dbscan": "DBSCAN",
    "butina": "Butina",
    "sphere_exclusion": "Sphere exclusion",
    "jarvis_patrick": "Jarvis-Patrick",
}


def _bitvect_to_numpy(fp) -> np.ndarray:
    n = int(fp.GetNumBits())
    arr = np.zeros((n,), dtype=np.float64)
    DataStructs.ConvertToNumpyArray(fp, arr)
    return arr


def _dense_fingerprint_matrix(fps: Sequence) -> np.ndarray:
    return np.vstack([_bitvect_to_numpy(fp) for fp in fps])


def _method_needs_dense_matrix(method: str) -> bool:
    return str(method) in _SKLEARN_CLUSTER_METHODS


def _condensed_tanimoto_distances(
    fps: Sequence, cancel_event: threading.Event | None = None
) -> list[float] | None:
    """Lower-triangle condensed distances d = 1 - Tanimoto (same order as RDKit Butina)."""
    n = len(fps)
    out: list[float] = []
    for i in range(n):
        if cancel_event is not None and cancel_event.is_set():
            return None
        sims = DataStructs.BulkTanimotoSimilarity(fps[i], fps[: i + 1])
        for j in range(i):
            s = float(sims[j])
            d = 1.0 - s
            if d < 0.0:
                d = 0.0
            elif d > 1.0:
                d = 1.0
            out.append(d)
    return out


def _labels_from_butina_clusters(clusters: tuple[tuple[int, ...], ...], n: int) -> np.ndarray:
    lab = np.full((n,), -1, dtype=np.int32)
    for cid, group in enumerate(clusters):
        for idx in group:
            lab[int(idx)] = int(cid)
    return lab


def cluster_butina(
    fps: Sequence,
    dist_cutoff: float,
    *,
    reordering: bool = False,
    cancel_event: threading.Event | None = None,
) -> np.ndarray | None:
    """Butina sphere-exclusion on Tanimoto distance (1 - similarity)."""
    n = len(fps)
    if n < 2:
        return None
    if cancel_event is not None and cancel_event.is_set():
        return None
    dists = _condensed_tanimoto_distances(fps, cancel_event=cancel_event)
    if dists is None:
        return None
    clusters = Butina.ClusterData(
        dists,
        nPts=n,
        distThresh=float(dist_cutoff),
        isDistData=True,
        reordering=bool(reordering),
    )
    return _labels_from_butina_clusters(clusters, n)


def _leader_sphere_centroids(
    fps: Sequence,
    threshold: float,
    *,
    cancel_event: threading.Event | None = None,
) -> list[int] | None:
    """RDKit :class:`LeaderPicker` centroids (minimum Tanimoto distance ``threshold`` between leaders)."""
    n = len(fps)
    if n < 1:
        return []
    if cancel_event is not None and cancel_event.is_set():
        return None
    lp = LeaderPicker()
    try:
        return [int(i) for i in lp.LazyBitVectorPick(fps, n, float(threshold))]
    except Exception:
        logger.debug("LazyBitVectorPick failed; falling back to LazyPick", exc_info=True)

    def dist(i: int, j: int) -> float:
        if cancel_event is not None and cancel_event.is_set():
            raise _ClusterCancelled()
        if i == j:
            return 0.0
        return _tanimoto_distance(fps[i], fps[j])

    try:
        return [int(i) for i in lp.LazyPick(distFunc=dist, poolSize=n, threshold=float(threshold))]
    except _ClusterCancelled:
        return None


class _ClusterCancelled(Exception):
    pass


def _tanimoto_distance(fp_i, fp_j) -> float:
    s = float(DataStructs.TanimotoSimilarity(fp_i, fp_j))
    d = 1.0 - s
    if d < 0.0:
        return 0.0
    if d > 1.0:
        return 1.0
    return d


def cluster_sphere_exclusion(
    fps: Sequence,
    dist_cutoff: float,
    *,
    cancel_event: threading.Event | None = None,
) -> np.ndarray | None:
    """
    Sphere exclusion clustering (RDKit Leader / Sayle): pick cluster centroids with
    :meth:`LeaderPicker.LazyBitVectorPick`, then assign each compound to its nearest centroid.
    """
    n = len(fps)
    if n < 2:
        return None
    if cancel_event is not None and cancel_event.is_set():
        return None
    try:
        centroid_idxs = _leader_sphere_centroids(fps, float(dist_cutoff), cancel_event=cancel_event)
    except _ClusterCancelled:
        return None
    if centroid_idxs is None:
        return None
    if not centroid_idxs:
        return np.zeros((n,), dtype=np.int32)

    cid_map = {int(idx): int(cid) for cid, idx in enumerate(centroid_idxs)}
    cent_fps = [fps[int(i)] for i in centroid_idxs]
    labels = np.zeros((n,), dtype=np.int32)
    for i in range(n):
        if cancel_event is not None and cancel_event.is_set():
            return None
        if i in cid_map:
            labels[i] = cid_map[i]
            continue
        sims = DataStructs.BulkTanimotoSimilarity(fps[i], cent_fps)
        labels[i] = int(np.argmax(sims))
    return labels


class _DSU:
    __slots__ = ("p", "r")

    def __init__(self, n: int) -> None:
        self.p = list(range(n))
        self.r = [0] * n

    def find(self, x: int) -> int:
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return
        if self.r[ra] < self.r[rb]:
            self.p[ra] = rb
        elif self.r[ra] > self.r[rb]:
            self.p[rb] = ra
        else:
            self.p[rb] = ra
            self.r[ra] += 1


def cluster_jarvis_patrick(
    fps: Sequence,
    nn_count: int,
    common_neighbors: int,
    cancel_event: threading.Event | None = None,
) -> np.ndarray | None:
    """
    Jarvis–Patrick: link i,j if they share at least ``common_neighbors`` of their
    ``nn_count`` nearest neighbors (by Tanimoto similarity).
    """
    n = len(fps)
    if n < 2:
        return None
    j_nn = int(nn_count)
    p_req = int(common_neighbors)
    j_nn = max(1, min(j_nn, n - 1))
    p_req = max(1, min(p_req, j_nn))

    neighbors: list[set[int]] = []
    for i in range(n):
        if cancel_event is not None and cancel_event.is_set():
            return None
        sims = DataStructs.BulkTanimotoSimilarity(fps[i], fps)
        sim_arr = np.asarray(sims, dtype=np.float64)
        order = np.argsort(-sim_arr)
        neigh: list[int] = []
        for idx in order:
            ii = int(idx)
            if ii == i:
                continue
            neigh.append(ii)
            if len(neigh) >= j_nn:
                break
        neighbors.append(set(neigh))

    dsu = _DSU(n)
    for i in range(n):
        if cancel_event is not None and cancel_event.is_set():
            return None
        for j in range(i + 1, n):
            if len(neighbors[i] & neighbors[j]) >= p_req:
                dsu.union(i, j)

    root_to_label: dict[int, int] = {}
    labels = np.zeros((n,), dtype=np.int32)
    next_lab = 0
    for i in range(n):
        r = dsu.find(i)
        if r not in root_to_label:
            root_to_label[r] = next_lab
            next_lab += 1
        labels[i] = root_to_label[r]
    return labels


def _fit_sklearn_labels(X: np.ndarray, method: str, params: dict) -> np.ndarray:
    from sklearn.cluster import AgglomerativeClustering, DBSCAN, KMeans

    n_samples = X.shape[0]
    if method == "kmeans":
        k = int(params.get("n_clusters", 5))
        k = max(2, min(k, n_samples))
        model = KMeans(n_clusters=k, random_state=42, n_init=10)
        return model.fit_predict(X)
    if method == "agglomerative":
        k = int(params.get("n_clusters", 5))
        k = max(2, min(k, n_samples))
        linkage = str(params.get("linkage", "average"))
        model = AgglomerativeClustering(n_clusters=k, linkage=linkage)
        return model.fit_predict(X)
    eps = float(params.get("eps", 0.35))
    ms = int(params.get("min_samples", 5))
    ms = max(2, min(ms, n_samples))
    model = DBSCAN(eps=eps, min_samples=ms, metric="cosine")
    return model.fit_predict(X)


def _run_clustering(
    method: str,
    params: dict,
    *,
    X: np.ndarray | None,
    fps: Sequence,
    cancel_event: threading.Event | None = None,
) -> np.ndarray | None:
    if method == "butina":
        return cluster_butina(
            fps,
            float(params.get("cutoff", 0.25)),
            reordering=bool(params.get("reordering", False)),
            cancel_event=cancel_event,
        )
    if method == "sphere_exclusion":
        return cluster_sphere_exclusion(
            fps,
            float(params.get("cutoff", 0.35)),
            cancel_event=cancel_event,
        )
    if method == "jarvis_patrick":
        return cluster_jarvis_patrick(
            fps,
            int(params.get("nn_count", 16)),
            int(params.get("common_neighbors", 8)),
            cancel_event=cancel_event,
        )
    if X is None:
        raise ValueError(f"{method} clustering requires a dense fingerprint matrix.")
    return _fit_sklearn_labels(X, method, params)


def _summarize_partition(labels: np.ndarray, X: np.ndarray | None) -> dict[str, float | int | None]:
    n = int(labels.shape[0])
    noise_ct = int(np.sum(labels == -1))
    non_noise_mask = labels >= 0
    n_eff = int(np.sum(non_noise_mask))
    if noise_ct:
        if n_eff == 0:
            n_clusters = 0
            largest_pct: float | None = None
        else:
            n_clusters = int(len(np.unique(labels[non_noise_mask])))
            uids, cnts = np.unique(labels[non_noise_mask], return_counts=True)
            largest_pct = float(np.max(cnts)) / float(max(n_eff, 1)) * 100.0
    else:
        uniq, counts = np.unique(labels, return_counts=True)
        n_clusters = int(len(uniq))
        largest_pct = float(np.max(counts)) / float(max(n, 1)) * 100.0

    sil: float | None = None
    if X is not None and n >= 3 and n_clusters >= 2:
        try:
            from sklearn.metrics import silhouette_score

            if noise_ct:
                if n_eff >= 3:
                    xm = non_noise_mask
                    lab_sub = labels[xm]
                    sil = float(silhouette_score(X[xm], lab_sub, metric="euclidean"))
            else:
                sil = float(silhouette_score(X, labels, metric="euclidean"))
        except Exception:
            sil = None

    return {
        "n_clusters": n_clusters,
        "noise_pct": float(noise_ct) / float(max(n, 1)) * 100.0,
        "largest_pct": largest_pct,
        "silhouette": sil,
    }


def _spread_integers(lo: int, hi: int, count: int) -> list[int]:
    if hi < lo:
        return []
    if lo == hi:
        return [lo]
    count = max(1, count)
    xs = np.linspace(lo, hi, num=min(count, hi - lo + 1))
    out: list[int] = []
    seen: set[int] = set()
    for v in xs:
        k = int(round(float(v)))
        k = max(lo, min(hi, k))
        if k not in seen:
            seen.add(k)
            out.append(k)
    return sorted(out)


def generate_explore_trials(
    n: int,
    max_runs: int,
    include: dict[str, bool],
) -> list[tuple[str, dict]]:
    """Build a bounded list of (method, params) trials for exploratory mode."""
    trials: list[tuple[str, dict]] = []
    cap_k = max(2, min(n - 1, 80))

    if include.get("kmeans", True):
        for k in _spread_integers(2, min(cap_k, 40), 8):
            trials.append(("kmeans", {"n_clusters": k}))

    if include.get("agglomerative", True):
        for linkage in ("average", "complete"):
            for k in _spread_integers(2, min(cap_k, 40), 5):
                trials.append(("agglomerative", {"n_clusters": k, "linkage": linkage}))

    if include.get("dbscan", True):
        for eps in (0.12, 0.18, 0.25, 0.32, 0.4, 0.5):
            for ms in (3, 5, 8):
                trials.append(("dbscan", {"eps": float(eps), "min_samples": int(ms)}))

    if include.get("butina", True):
        for c in np.linspace(0.08, 0.45, num=8):
            trials.append(("butina", {"cutoff": float(c), "reordering": False}))
        trials.append(("butina", {"cutoff": 0.25, "reordering": True}))

    if include.get("sphere_exclusion", True):
        for c in np.linspace(0.15, 0.65, num=8):
            trials.append(("sphere_exclusion", {"cutoff": float(c)}))

    if include.get("jarvis_patrick", True):
        for j_nn, p_common in ((10, 4), (12, 5), (14, 6), (16, 8), (20, 10), (24, 12)):
            if p_common < j_nn < n:
                trials.append(("jarvis_patrick", {"nn_count": j_nn, "common_neighbors": p_common}))

    out: list[tuple[str, dict]] = []
    seen: set[tuple[str, str]] = set()
    for m, p in trials:
        key = (m, repr(sorted(p.items())) if p else "")
        if key in seen:
            continue
        seen.add(key)
        out.append((m, dict(p)))

    return out[: max(1, max_runs)]


def _format_params(method: str, params: dict) -> str:
    if method == "kmeans":
        return f"k={int(params['n_clusters'])}"
    if method == "agglomerative":
        return f"k={int(params['n_clusters'])}, {params.get('linkage', 'average')}"
    if method == "dbscan":
        return f"eps={float(params['eps']):.3f}, min_samples={int(params['min_samples'])}"
    if method == "butina":
        r = ", reorder" if params.get("reordering") else ""
        return f"cutoff={float(params.get('cutoff', 0.2)):.3f}{r}"
    if method == "sphere_exclusion":
        return f"cutoff={float(params.get('cutoff', 0.35)):.3f}"
    if method == "jarvis_patrick":
        return f"NN={int(params['nn_count'])}, common≥{int(params['common_neighbors'])}"
    return repr(params)


class ClusterWorker(QRunnable):
    """Build a fingerprint matrix and assign cluster labels; writes via ``WorkerSignals.calculated``."""

    def __init__(
        self,
        rows: list[tuple[int, Chem.Mol]],
        fp_choice: str,
        method: str,
        params: dict,
        column_name: str,
        signals,
        cancel_event: threading.Event | None = None,
        progress_state=None,
    ):
        super().__init__()
        self.rows = rows
        self.fp_choice = fp_choice
        self.method = method
        self.params = params
        self.column_name = column_name
        self.signals = signals
        self.cancel_event = cancel_event
        self.progress_state = progress_state

    def run(self) -> None:
        sk_methods = _SKLEARN_CLUSTER_METHODS
        if self.method in sk_methods:
            try:
                from sklearn.cluster import KMeans  # noqa: F401

                _ = KMeans
            except ImportError as e:
                self.signals.cluster_failed.emit(
                    f"scikit-learn is required for {self.method}. Install with: pip install scikit-learn ({e})"
                )
                return

        from ..platform_support.tool_progress import report_tool_progress

        cancel_ev = self.cancel_event
        oids: list[int] = []
        fps: list = []
        tot = max(len(self.rows), 1)
        cancelled = False
        throttle = [0, 0.0]

        for i, (oid, payload) in enumerate(self.rows, start=1):
            if cancel_ev is not None and cancel_ev.is_set():
                cancelled = True
                break
            report_tool_progress(
                message="Clustering",
                done=i,
                total=tot,
                progress_state=self.progress_state,
                signals=self.signals,
                throttle=throttle,
            )
            mol = mol_from_job_payload(payload)
            if mol is None:
                continue
            try:
                fp = fingerprint_bitvect_for_row(int(oid), mol, self.fp_choice)
                if fp is None:
                    fp = fingerprint_bitvect_for_ui_choice(mol, self.fp_choice)
            except Exception:
                fp = None
            if fp is None:
                continue
            try:
                fps.append(fp)
                oids.append(int(oid))
            except Exception:
                logger.debug("Fingerprint conversion failed for oid=%s", oid, exc_info=True)

        if len(fps) < 2:
            if cancelled and len(fps) == 1 and oids:
                # Keep completed work: one processed row still gets a deterministic cluster label.
                res = [(oids[0], {self.column_name: "0"})]
                emit_partial_results_if_cancelled(self.signals, "Cluster", 1, tot, True)
                self.signals.calculated.emit(res, [self.column_name])
                self.signals.cluster_failed.emit("Cancelled.")
                return
            if cancelled:
                self.signals.cluster_failed.emit("Cancelled.")
                return
            self.signals.cluster_failed.emit(
                "Need at least two rows with valid fingerprints in this scope to cluster."
            )
            return

        X = _dense_fingerprint_matrix(fps) if _method_needs_dense_matrix(self.method) else None

        try:
            labels = _run_clustering(
                self.method,
                self.params,
                X=X,
                fps=fps,
                cancel_event=None if cancelled else cancel_ev,
            )
        except Exception as e:
            logger.exception("Clustering fit failed")
            self.signals.cluster_failed.emit(str(e) or "Clustering failed.")
            return

        if labels is None:
            self.signals.cluster_failed.emit("Cancelled.")
            return

        def _label_txt(lab: int) -> str:
            if lab == -1:
                return "noise"
            return str(int(lab))

        res = [(oid, {self.column_name: _label_txt(int(lab))}) for oid, lab in zip(oids, labels)]
        report_tool_progress(
            message="Clustering",
            done=tot,
            total=tot,
            progress_state=self.progress_state,
            signals=self.signals,
            force_signal=True,
        )
        emit_partial_results_if_cancelled(self.signals, "Cluster", len(res), tot, cancelled)
        self.signals.calculated.emit(res, [self.column_name])
        if cancelled:
            self.signals.cluster_failed.emit("Cancelled.")


class ClusterExploreWorker(QRunnable):
    """
    Sample several (method, parameter) combinations and emit summary rows for the UI.
    """

    def __init__(
        self,
        rows: list[tuple[int, Chem.Mol]],
        fp_choice: str,
        max_runs: int,
        include: dict[str, bool],
        signals,
        cancel_event: threading.Event | None = None,
        progress_state=None,
    ):
        super().__init__()
        self.rows = rows
        self.fp_choice = fp_choice
        self.max_runs = int(max_runs)
        self.include = dict(include)
        self.signals = signals
        self.cancel_event = cancel_event
        self.progress_state = progress_state

    def run(self) -> None:
        from ..platform_support.tool_progress import report_tool_progress

        cancel_ev = self.cancel_event
        oids: list[int] = []
        fps: list = []
        tot = max(len(self.rows), 1)
        fp_throttle = [0, 0.0]

        for i, (oid, payload) in enumerate(self.rows, start=1):
            if cancel_ev is not None and cancel_ev.is_set():
                self.signals.cluster_failed.emit("Cancelled.")
                return
            report_tool_progress(
                message="Exploring clusters",
                done=i,
                total=tot,
                progress_state=self.progress_state,
                signals=self.signals,
                throttle=fp_throttle,
            )
            mol = mol_from_job_payload(payload)
            if mol is None:
                continue
            try:
                fp = fingerprint_bitvect_for_row(int(oid), mol, self.fp_choice)
                if fp is None:
                    fp = fingerprint_bitvect_for_ui_choice(mol, self.fp_choice)
            except Exception:
                fp = None
            if fp is None:
                continue
            try:
                fps.append(fp)
                oids.append(int(oid))
            except Exception:
                logger.debug("Fingerprint conversion failed for oid=%s", oid, exc_info=True)

        if len(fps) < 2:
            self.signals.cluster_failed.emit(
                "Need at least two rows with valid fingerprints in this scope to explore."
            )
            return

        n = len(fps)
        trials = generate_explore_trials(n, self.max_runs, self.include)
        needs_sk = any(m in ("kmeans", "agglomerative", "dbscan") for m, _ in trials)
        X = _dense_fingerprint_matrix(fps) if needs_sk else None
        if needs_sk:
            try:
                from sklearn.cluster import KMeans  # noqa: F401

                _ = KMeans
            except ImportError as e:
                self.signals.cluster_failed.emit(
                    f"scikit-learn is required for exploratory trials that include K-Means, "
                    f"Agglomerative, or DBSCAN. pip install scikit-learn ({e})"
                )
                return

        n_trials = max(len(trials), 1)
        results: list[dict] = []

        trial_throttle = [0, 0.0]
        for ti, (method, params) in enumerate(trials):
            if cancel_ev is not None and cancel_ev.is_set():
                report_tool_progress(
                    message="Exploring clusters",
                    done=min(ti, n_trials),
                    total=n_trials,
                    progress_state=self.progress_state,
                    signals=self.signals,
                    force_signal=True,
                )
                self.signals.cluster_explore_finished.emit(results)
                try:
                    self.signals.partial_results.emit("Cluster explore", len(results), n_trials)
                except Exception:
                    pass
                self.signals.cluster_failed.emit("Cancelled.")
                return
            report_tool_progress(
                message="Exploring clusters",
                done=ti + 1,
                total=n_trials,
                progress_state=self.progress_state,
                signals=self.signals,
                throttle=trial_throttle,
            )
            try:
                labels = _run_clustering(method, params, X=X, fps=fps, cancel_event=cancel_ev)
            except Exception as e:
                logger.debug("Explore trial failed: %s %s", method, params, exc_info=True)
                results.append(
                    {
                        "method": method,
                        "params": dict(params),
                        "settings": _format_params(method, params),
                        "n_clusters": None,
                        "silhouette": None,
                        "largest_pct": None,
                        "noise_pct": None,
                        "notes": str(e)[:120],
                    }
                )
                continue
            if labels is None:
                self.signals.cluster_explore_finished.emit(results)
                try:
                    self.signals.partial_results.emit("Cluster explore", len(results), n_trials)
                except Exception:
                    pass
                self.signals.cluster_failed.emit("Cancelled.")
                return
            stats = _summarize_partition(labels, X)
            sil = stats["silhouette"]
            results.append(
                {
                    "method": method,
                    "params": dict(params),
                    "settings": _format_params(method, params),
                    "n_clusters": stats["n_clusters"],
                    "silhouette": None if sil is None else round(float(sil), 4),
                    "largest_pct": None
                    if stats["largest_pct"] is None
                    else round(float(stats["largest_pct"]), 2),
                    "noise_pct": round(float(stats["noise_pct"]), 2),
                    "notes": "",
                }
            )

        report_tool_progress(
            message="Exploring clusters",
            done=n_trials,
            total=n_trials,
            progress_state=self.progress_state,
            signals=self.signals,
            force_signal=True,
        )
        self.signals.cluster_explore_finished.emit(results)
