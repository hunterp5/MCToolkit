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

"""GNN-MTL permeability / efflux predictions via Chemprop (Ohlsson et al., ACS Omega 2025).

Model artifact: https://doi.org/10.5281/zenodo.16948542 (``model.pt``, Chemprop v2.1.0).
Chemprop task order (log10): Caco-2 ER, Caco-2 Papp, MDCK-MDR1 ER, NIH MDCK ER — converted to
linear units for table output.
"""

from __future__ import annotations

import contextlib
import logging
import threading
import warnings
from pathlib import Path
from collections.abc import Callable
from typing import Sequence

from .bundled_paths import gnn_mtl_model_path

logger = logging.getLogger(__name__)

# Table column headers (linear scale; see ``_linear_values_from_log_predictions``).
PERMEABILITY_OUTPUT_COLUMNS: tuple[str, ...] = (
    "Caco-2 ER",
    "Caco-2 Papp",
    "MDCK-MDR1 ER",
    "NIH MDCK ER",
)

# (table column, checkbox label) for the Predict Permeability dialog.
PERMEABILITY_ENDPOINT_OPTIONS: tuple[tuple[str, str], ...] = (
    ("Caco-2 ER", "Caco-2 — efflux ratio (ER)"),
    ("Caco-2 Papp", "Caco-2 — apparent permeability (Papp)"),
    ("MDCK-MDR1 ER", "MDCK-MDR1 — efflux ratio (ER)"),
    ("NIH MDCK ER", "NIH MDCK — efflux ratio (ER)"),
)

# Zenodo / Chemprop task order (indices 0–3), model outputs are log10.
_PERMEABILITY_LOG_TASK_KEYS: tuple[str, ...] = (
    "caco2_er_log",
    "caco2_papp_log",
    "mdck_er_log",
    "nih_mdck_er_log",
)


def _linear_from_log10(log_val: float) -> float:
    return float(10.0**log_val)


def _linear_values_from_log_predictions(log_by_task: dict[str, float]) -> dict[str, float]:
    """Map raw model log outputs to linear ER (unitless) and Papp (×10⁻⁶ cm/s)."""
    mapping = zip(_PERMEABILITY_LOG_TASK_KEYS, PERMEABILITY_OUTPUT_COLUMNS)
    return {
        col: _linear_from_log10(log_by_task[key])
        for key, col in mapping
        if key in log_by_task
    }


def _format_efflux_ratio(val: float) -> str:
    if val < 0.01 or val >= 1000:
        return f"{val:.4g}"
    return f"{val:.4f}".rstrip("0").rstrip(".")


def _format_papp(val: float) -> str:
    """Apparent permeability in ×10⁻⁶ cm/s (linear)."""
    if val < 0.01 or val >= 1000:
        return f"{val:.4g}"
    return f"{val:.4f}".rstrip("0").rstrip(".")

_model_lock = threading.Lock()
_model_singleton = None

ZENODO_MODEL_URL = (
    "https://zenodo.org/api/records/16948542/files/model.pt/content"
)
ZENODO_DOI = "10.5281/zenodo.16948542"

_LIGHTNING_LOGGER_NAMES = (
    "lightning",
    "lightning.pytorch",
    "lightning.pytorch.utilities.rank_zero",
    "lightning.fabric",
)


@contextlib.contextmanager
def _quiet_lightning_predict():
    """Hide Lightning Trainer tips and dataloader warnings during embedded predict."""
    saved: list[tuple[logging.Logger, int]] = []
    for name in _LIGHTNING_LOGGER_NAMES:
        lg = logging.getLogger(name)
        saved.append((lg, lg.level))
        lg.setLevel(logging.ERROR)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=UserWarning)
        warnings.filterwarnings(
            "ignore",
            message=r".*predict_dataloader.*num_workers.*",
            category=UserWarning,
        )
        warnings.filterwarnings(
            "ignore",
            message=r".*tensorboardX.*",
            category=UserWarning,
        )
        try:
            yield
        finally:
            for lg, prev in saved:
                lg.setLevel(prev)


def permeability_model_file() -> Path:
    """Path to ``model.pt`` (may be missing until bootstrap download)."""
    return gnn_mtl_model_path()


def permeability_model_available() -> bool:
    p = permeability_model_file()
    return p.is_file() and p.stat().st_size > 0


_WINDOWS_TORCH_DLL_HELP = (
    "PyTorch could not load its native libraries (Windows DLL error).\n\n"
    "Reinstall dependencies (includes CPU PyTorch 2.5.1 and Chemprop):\n"
    "  scripts\\install_pytorch_pka.ps1\n"
    "  pip install -r requirements.txt\n"
)


def permeability_stack_import_error() -> str | None:
    """Return an error message when Chemprop / PyTorch cannot be imported."""
    try:
        # Import torch first; on Windows, loading only from a QThread can fail (WinError 1114).
        import torch  # noqa: F401

        import chemprop  # noqa: F401
        import lightning  # noqa: F401
    except ImportError as e:
        return (
            "Chemprop is not installed. Install dependencies from the repo root:\n"
            "  pip install -r requirements.txt\n"
            f"Details: {e}"
        )
    except OSError as e:
        winerr = getattr(e, "winerror", None)
        msg = str(e).lower()
        if winerr == 1114 or "c10.dll" in msg or "dll" in msg:
            return _WINDOWS_TORCH_DLL_HELP + f"\n\nDetails: {e}"
        return f"PyTorch failed to load native libraries:\n{e}"
    except Exception as e:
        msg = str(e).lower()
        if "_array_api" in msg or "numpy" in msg:
            return (
                "This stack needs NumPy 1.x (PyTorch 2.5 / UMAP). NumPy 2 is not supported yet.\n\n"
                "  pip install -r requirements.txt\n\n"
                f"Details: {e}"
            )
        if "torchvision" in msg or "torch" in msg:
            return (
                "Chemprop could not load PyTorch / Lightning (version mismatch is common).\n\n"
                "Reinstall dependencies:\n"
                "  scripts\\install_pytorch_pka.ps1\n"
                "  pip install -r requirements.txt\n\n"
                f"Details: {e}"
            )
        return f"Chemprop stack failed to initialize:\n{e}"
    return None


def ensure_permeability_stack_ready() -> str | None:
    """
    Verify Chemprop/PyTorch on the **calling thread** (use the GUI thread before enqueueing workers).

    Returns an error message, or ``None`` when the stack is importable.
    """
    return permeability_stack_import_error()


def _load_gnn_mtl_model():
    global _model_singleton
    err = permeability_stack_import_error()
    if err:
        raise RuntimeError(err)
    path = permeability_model_file()
    if not path.is_file():
        raise FileNotFoundError(
            f"GNN-MTL model not found at {path}.\n"
            f"Download from https://doi.org/{ZENODO_DOI} or run:\n"
            "  python scripts/bootstrap_gnn_mtl_model.py"
        )
    from chemprop.models.utils import load_model

    with _model_lock:
        if _model_singleton is None:
            logger.debug("Loading GNN-MTL permeability model from %s", path)
            with _quiet_lightning_predict():
                _model_singleton = load_model(path)
    return _model_singleton


def predict_permeability_batch(
    smiles_list: Sequence[str],
    *,
    batch_size: int = 64,
    progress_callback: Callable[[int, int], None] | None = None,
) -> list[dict[str, float] | None]:
    """
    Predict four permeability endpoints for each SMILES string.

    Returns one dict per input (linear-scale column name → value) or ``None`` when invalid.
    """
    import numpy as np
    import torch
    from chemprop import data, featurizers
    from lightning import pytorch as pl

    if not smiles_list:
        return []

    mpnn = _load_gnn_mtl_model()
    featurizer = featurizers.SimpleMoleculeMolGraphFeaturizer()
    out: list[dict[str, float] | None] = [None] * len(smiles_list)
    valid_idx: list[int] = []
    datapoints = []

    for i, smi in enumerate(smiles_list):
        s = (smi or "").strip()
        if not s:
            continue
        try:
            dp = data.MoleculeDatapoint.from_smi(s)
        except (RuntimeError, ValueError) as e:
            logger.debug("Skip invalid SMILES %r: %s", s[:80], e)
            continue
        valid_idx.append(i)
        datapoints.append(dp)

    if not datapoints:
        return out

    bs = max(1, int(batch_size))
    preds_chunks: list[np.ndarray] = []
    with torch.inference_mode(), _quiet_lightning_predict():
        trainer = pl.Trainer(
            logger=False,
            enable_progress_bar=False,
            enable_model_summary=False,
            barebones=True,
            accelerator="cpu",
            devices=1,
        )
        n_dp = len(datapoints)
        for start in range(0, n_dp, bs):
            chunk = datapoints[start : start + bs]
            dset = data.MoleculeDataset(chunk, featurizer=featurizer)
            loader = data.build_dataloader(dset, shuffle=False, num_workers=0)
            batch_preds = trainer.predict(mpnn, loader)
            preds_chunks.append(np.concatenate(batch_preds, axis=0))
            if progress_callback is not None:
                progress_callback(min(start + len(chunk), n_dp), n_dp)

    arr = np.concatenate(preds_chunks, axis=0)
    keys = _PERMEABILITY_LOG_TASK_KEYS
    for j, row_i in enumerate(valid_idx):
        if j >= len(arr):
            break
        log_row = {keys[k]: float(arr[j, k]) for k in range(min(len(keys), arr.shape[1]))}
        out[row_i] = _linear_values_from_log_predictions(log_row)

    return out


def format_permeability_row(
    values: dict[str, float] | None,
    columns: Sequence[str] | None = None,
) -> dict[str, str]:
    """Format linear-scale prediction dict for table cells (``N/A`` when missing)."""
    headers = tuple(columns) if columns else PERMEABILITY_OUTPUT_COLUMNS
    if not values:
        return {h: "N/A" for h in headers}
    out: dict[str, str] = {}
    for h in headers:
        if h not in values:
            out[h] = "N/A"
        elif h == "Caco-2 Papp":
            out[h] = _format_papp(values[h])
        else:
            out[h] = _format_efflux_ratio(values[h])
    return out
