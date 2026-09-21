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

"""Predict ADME via ADMET-AI v2 Chemprop ensembles (TDC ADMET endpoints).

Weights: https://doi.org/10.5281/zenodo.18728250 (classification + regression, 5-fold each).
Do not import the ``admet-ai`` package; load checkpoints with the Chemprop already in this env.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..platform_support.bundled_paths import adme_models_dir
from ..platform_support.env import env_get
from .permeability_prediction import (
    _quiet_lightning_predict,
    permeability_stack_import_error,
    pin_permeability_torch_threads,
)

logger = logging.getLogger(__name__)

ENSEMBLE_CLASSIFICATION = "admet_classification"
ENSEMBLE_REGRESSION = "admet_regression"
ADME_ENSEMBLES: tuple[str, ...] = (ENSEMBLE_CLASSIFICATION, ENSEMBLE_REGRESSION)

GROUP_ABSORPTION = "Absorption"
GROUP_DISTRIBUTION = "Distribution"
GROUP_METABOLISM = "Metabolism"
GROUP_EXCRETION = "Excretion"
GROUP_TOXICITY = "Toxicity"
ADME_GROUP_ORDER: tuple[str, ...] = (
    GROUP_ABSORPTION,
    GROUP_DISTRIBUTION,
    GROUP_METABOLISM,
    GROUP_EXCRETION,
    GROUP_TOXICITY,
)

ZENODO_DOI = "10.5281/zenodo.18728250"

_ensemble_lock = threading.Lock()
_ensemble_cache: dict[str, tuple[list[Any], tuple[str, ...]]] = {}
_ADME_DEVICE_LOGGED = False


@dataclass(frozen=True)
class AdmeEndpoint:
    """One TDC ADMET task shown as a Predict ADME checkbox."""

    column: str
    label: str
    ensemble: str
    task_key: str
    group: str


# Chemprop output column names from the v2.0.1 checkpoints (do not rename task_key).
ADME_ENDPOINTS: tuple[AdmeEndpoint, ...] = (
    AdmeEndpoint(
        "HIA",
        "HIA (human intestinal absorption)",
        ENSEMBLE_CLASSIFICATION,
        "HIA_Hou",
        GROUP_ABSORPTION,
    ),
    AdmeEndpoint(
        "Caco-2 Papp (TDC)",
        "Caco-2 Papp (TDC Wang; not GNN-MTL)",
        ENSEMBLE_REGRESSION,
        "Caco2_Wang",
        GROUP_ABSORPTION,
    ),
    AdmeEndpoint(
        "PAMPA", "PAMPA (NCATS)", ENSEMBLE_CLASSIFICATION, "PAMPA_NCATS", GROUP_ABSORPTION
    ),
    AdmeEndpoint(
        "P-gp inhibitor",
        "P-glycoprotein inhibitor",
        ENSEMBLE_CLASSIFICATION,
        "Pgp_Broccatelli",
        GROUP_ABSORPTION,
    ),
    AdmeEndpoint(
        "Oral bioavailability",
        "Oral bioavailability",
        ENSEMBLE_CLASSIFICATION,
        "Bioavailability_Ma",
        GROUP_ABSORPTION,
    ),
    AdmeEndpoint(
        "Lipophilicity (TDC)",
        "Lipophilicity (AstraZeneca TDC)",
        ENSEMBLE_REGRESSION,
        "Lipophilicity_AstraZeneca",
        GROUP_ABSORPTION,
    ),
    AdmeEndpoint(
        "Aqueous solubility",
        "Aqueous solubility (AqSolDB)",
        ENSEMBLE_REGRESSION,
        "Solubility_AqSolDB",
        GROUP_ABSORPTION,
    ),
    AdmeEndpoint(
        "Hydration free energy",
        "Hydration free energy (FreeSolv)",
        ENSEMBLE_REGRESSION,
        "HydrationFreeEnergy_FreeSolv",
        GROUP_ABSORPTION,
    ),
    AdmeEndpoint(
        "BBB",
        "Blood–brain barrier (Martins)",
        ENSEMBLE_CLASSIFICATION,
        "BBB_Martins",
        GROUP_DISTRIBUTION,
    ),
    AdmeEndpoint(
        "PPB",
        "Plasma protein binding (AstraZeneca)",
        ENSEMBLE_REGRESSION,
        "PPBR_AZ",
        GROUP_DISTRIBUTION,
    ),
    AdmeEndpoint(
        "VDss",
        "Volume of distribution (Lombardo)",
        ENSEMBLE_REGRESSION,
        "VDss_Lombardo",
        GROUP_DISTRIBUTION,
    ),
    AdmeEndpoint(
        "CYP1A2 inhibitor",
        "CYP1A2 inhibitor",
        ENSEMBLE_CLASSIFICATION,
        "CYP1A2_Veith",
        GROUP_METABOLISM,
    ),
    AdmeEndpoint(
        "CYP2C19 inhibitor",
        "CYP2C19 inhibitor",
        ENSEMBLE_CLASSIFICATION,
        "CYP2C19_Veith",
        GROUP_METABOLISM,
    ),
    AdmeEndpoint(
        "CYP2C9 inhibitor",
        "CYP2C9 inhibitor",
        ENSEMBLE_CLASSIFICATION,
        "CYP2C9_Veith",
        GROUP_METABOLISM,
    ),
    AdmeEndpoint(
        "CYP2D6 inhibitor",
        "CYP2D6 inhibitor",
        ENSEMBLE_CLASSIFICATION,
        "CYP2D6_Veith",
        GROUP_METABOLISM,
    ),
    AdmeEndpoint(
        "CYP3A4 inhibitor",
        "CYP3A4 inhibitor",
        ENSEMBLE_CLASSIFICATION,
        "CYP3A4_Veith",
        GROUP_METABOLISM,
    ),
    AdmeEndpoint(
        "CYP2C9 substrate",
        "CYP2C9 substrate",
        ENSEMBLE_CLASSIFICATION,
        "CYP2C9_Substrate_CarbonMangels",
        GROUP_METABOLISM,
    ),
    AdmeEndpoint(
        "CYP2D6 substrate",
        "CYP2D6 substrate",
        ENSEMBLE_CLASSIFICATION,
        "CYP2D6_Substrate_CarbonMangels",
        GROUP_METABOLISM,
    ),
    AdmeEndpoint(
        "CYP3A4 substrate",
        "CYP3A4 substrate",
        ENSEMBLE_CLASSIFICATION,
        "CYP3A4_Substrate_CarbonMangels",
        GROUP_METABOLISM,
    ),
    AdmeEndpoint(
        "Half-life",
        "Plasma half-life (Obach)",
        ENSEMBLE_REGRESSION,
        "Half_Life_Obach",
        GROUP_EXCRETION,
    ),
    AdmeEndpoint(
        "Clearance (hepatocyte)",
        "Hepatocyte clearance (AstraZeneca)",
        ENSEMBLE_REGRESSION,
        "Clearance_Hepatocyte_AZ",
        GROUP_EXCRETION,
    ),
    AdmeEndpoint(
        "Clearance (microsome)",
        "Microsomal clearance (AstraZeneca)",
        ENSEMBLE_REGRESSION,
        "Clearance_Microsome_AZ",
        GROUP_EXCRETION,
    ),
    AdmeEndpoint("hERG", "hERG liability", ENSEMBLE_CLASSIFICATION, "hERG", GROUP_TOXICITY),
    AdmeEndpoint("AMES", "Ames mutagenicity", ENSEMBLE_CLASSIFICATION, "AMES", GROUP_TOXICITY),
    AdmeEndpoint(
        "DILI", "Drug-induced liver injury", ENSEMBLE_CLASSIFICATION, "DILI", GROUP_TOXICITY
    ),
    AdmeEndpoint(
        "Skin reaction",
        "Skin sensitization",
        ENSEMBLE_CLASSIFICATION,
        "Skin_Reaction",
        GROUP_TOXICITY,
    ),
    AdmeEndpoint(
        "Carcinogens",
        "Carcinogenicity (Lagunin)",
        ENSEMBLE_CLASSIFICATION,
        "Carcinogens_Lagunin",
        GROUP_TOXICITY,
    ),
    AdmeEndpoint(
        "ClinTox", "Clinical toxicity", ENSEMBLE_CLASSIFICATION, "ClinTox", GROUP_TOXICITY
    ),
    AdmeEndpoint(
        "LD50", "Acute toxicity LD50 (Zhu)", ENSEMBLE_REGRESSION, "LD50_Zhu", GROUP_TOXICITY
    ),
    AdmeEndpoint(
        "Tox21 AR", "Tox21 androgen receptor", ENSEMBLE_CLASSIFICATION, "NR-AR", GROUP_TOXICITY
    ),
    AdmeEndpoint(
        "Tox21 AR-LBD",
        "Tox21 androgen receptor LBD",
        ENSEMBLE_CLASSIFICATION,
        "NR-AR-LBD",
        GROUP_TOXICITY,
    ),
    AdmeEndpoint(
        "Tox21 AhR",
        "Tox21 aryl hydrocarbon receptor",
        ENSEMBLE_CLASSIFICATION,
        "NR-AhR",
        GROUP_TOXICITY,
    ),
    AdmeEndpoint(
        "Tox21 aromatase",
        "Tox21 aromatase",
        ENSEMBLE_CLASSIFICATION,
        "NR-Aromatase",
        GROUP_TOXICITY,
    ),
    AdmeEndpoint(
        "Tox21 ER", "Tox21 estrogen receptor", ENSEMBLE_CLASSIFICATION, "NR-ER", GROUP_TOXICITY
    ),
    AdmeEndpoint(
        "Tox21 ER-LBD",
        "Tox21 estrogen receptor LBD",
        ENSEMBLE_CLASSIFICATION,
        "NR-ER-LBD",
        GROUP_TOXICITY,
    ),
    AdmeEndpoint(
        "Tox21 PPAR-gamma",
        "Tox21 PPAR-gamma",
        ENSEMBLE_CLASSIFICATION,
        "NR-PPAR-gamma",
        GROUP_TOXICITY,
    ),
    AdmeEndpoint(
        "Tox21 ARE", "Tox21 antioxidant response", ENSEMBLE_CLASSIFICATION, "SR-ARE", GROUP_TOXICITY
    ),
    AdmeEndpoint("Tox21 ATAD5", "Tox21 ATAD5", ENSEMBLE_CLASSIFICATION, "SR-ATAD5", GROUP_TOXICITY),
    AdmeEndpoint(
        "Tox21 HSE", "Tox21 heat-shock response", ENSEMBLE_CLASSIFICATION, "SR-HSE", GROUP_TOXICITY
    ),
    AdmeEndpoint(
        "Tox21 MMP",
        "Tox21 mitochondrial membrane potential",
        ENSEMBLE_CLASSIFICATION,
        "SR-MMP",
        GROUP_TOXICITY,
    ),
    AdmeEndpoint("Tox21 p53", "Tox21 p53", ENSEMBLE_CLASSIFICATION, "SR-p53", GROUP_TOXICITY),
)

ADME_BY_COLUMN: dict[str, AdmeEndpoint] = {ep.column: ep for ep in ADME_ENDPOINTS}
ADME_OUTPUT_COLUMNS: tuple[str, ...] = tuple(ep.column for ep in ADME_ENDPOINTS)

RECOMMENDED_ADME_COLUMNS: tuple[str, ...] = (
    "hERG",
    "CYP3A4 inhibitor",
    "Oral bioavailability",
    "BBB",
    "DILI",
    "PPB",
    "Clearance (hepatocyte)",
    "Aqueous solubility",
)

ADME_ENDPOINT_OPTIONS: tuple[tuple[str, str], ...] = tuple(
    (ep.column, ep.label) for ep in ADME_ENDPOINTS
)


def adme_stack_import_error() -> str | None:
    """Same Chemprop / PyTorch stack as Predict Permeability."""
    return permeability_stack_import_error()


def adme_gpu_forced_off() -> bool:
    raw = (env_get("MCTOOLKIT_ADME_GPU") or "").strip().lower()
    return raw in {"0", "false", "no", "off", "cpu"}


def adme_needs_cuda_isolation() -> bool:
    """True when Chemprop must run in a child process (CUDA PyTorch wheel)."""
    from ..ionization.unipka_ensembles import torch_is_cuda_build

    return torch_is_cuda_build()


def adme_use_gpu() -> bool:
    """Whether ADME inference should run on CUDA. Initializes CUDA; worker process only."""
    if adme_gpu_forced_off():
        return False
    raw = (env_get("MCTOOLKIT_ADME_GPU") or "").strip().lower()
    try:
        import torch

        cuda = bool(torch.cuda.is_available())
    except (ImportError, OSError, RuntimeError):
        cuda = False
    if raw in {"1", "true", "yes", "on", "cuda", "gpu"} and not cuda:
        logger.warning(
            "MCTOOLKIT_ADME_GPU requested CUDA but this PyTorch build has no GPU; using CPU"
        )
        return False
    return cuda


def adme_lightning_accelerator() -> str:
    return "gpu" if adme_use_gpu() else "cpu"


def _log_adme_compute_device(use_gpu: bool) -> None:
    global _ADME_DEVICE_LOGGED
    if _ADME_DEVICE_LOGGED:
        return
    _ADME_DEVICE_LOGGED = True
    if use_gpu:
        try:
            import torch

            name = torch.cuda.get_device_name(0)
        except (ImportError, OSError, RuntimeError):
            name = "CUDA"
        logger.info("Predict ADME on GPU (%s)", name)
        return
    logger.debug("Predict ADME on CPU")
    from ..ionization.unipka_ensembles import warn_if_cuda_torch_missing

    warn_if_cuda_torch_missing()


def adme_models_available() -> bool:
    root = adme_models_dir()
    for name in ADME_ENSEMBLES:
        folder = root / name
        pts = list(folder.glob("*.pt")) if folder.is_dir() else []
        if len(pts) < 1:
            return False
        if any(p.stat().st_size <= 0 for p in pts):
            return False
    return True


def endpoints_for_columns(columns: Sequence[str]) -> list[AdmeEndpoint]:
    """Resolve checked table columns; unknown names are ignored."""
    out: list[AdmeEndpoint] = []
    seen: set[str] = set()
    for col in columns:
        ep = ADME_BY_COLUMN.get(col)
        if ep is None or ep.column in seen:
            continue
        seen.add(ep.column)
        out.append(ep)
    return out


def ensembles_needed(columns: Sequence[str]) -> tuple[str, ...]:
    """Which checkpoint folders to load for the checked columns."""
    needed: list[str] = []
    for name in ADME_ENSEMBLES:
        if any(ep.ensemble == name for ep in endpoints_for_columns(columns)):
            needed.append(name)
    return tuple(needed)


def _missing_models_message(path: Path) -> str:
    return (
        f"ADME Chemprop weights were not found at {path}.\n"
        f"Download from https://doi.org/{ZENODO_DOI} or run:\n"
        "  python scripts/bootstrap_adme_models.py"
    )


def _load_model_file(path: Path):
    from chemprop.models.utils import load_model

    try:
        return load_model(path, multicomponent=False)
    except TypeError:
        return load_model(path)


def _load_ensemble(name: str) -> tuple[list[Any], tuple[str, ...]]:
    err = adme_stack_import_error()
    if err:
        raise RuntimeError(err)
    folder = adme_models_dir() / name
    paths = sorted(p for p in folder.glob("*.pt") if p.is_file() and p.stat().st_size > 0)
    if not paths:
        raise FileNotFoundError(_missing_models_message(folder))
    with _ensemble_lock:
        cached = _ensemble_cache.get(name)
        if cached is not None:
            return cached
        from chemprop.models.utils import load_output_columns

        logger.debug("Loading ADME ensemble %s from %s (%s folds)", name, folder, len(paths))
        with _quiet_lightning_predict():
            models = [_load_model_file(p) for p in paths]
        tasks = tuple(str(t) for t in load_output_columns(paths[0]))
        packed = (models, tasks)
        _ensemble_cache[name] = packed
        return packed


def _predict_ensemble(
    name: str,
    datapoints: list,
    *,
    batch_size: int,
    accelerator: str,
    progress_callback: Callable[[int, int], None] | None,
    progress_offset: int,
    progress_total: int,
) -> dict[str, list[float]]:
    import numpy as np
    import torch
    from chemprop import data, featurizers
    from lightning import pytorch as pl

    models, tasks = _load_ensemble(name)
    if accelerator == "gpu":
        models = [m.to("cuda") for m in models]
    featurizer = featurizers.SimpleMoleculeMolGraphFeaturizer()
    bs = max(1, int(batch_size))
    fold_chunks: list[list[np.ndarray]] = [[] for _ in models]
    n_dp = len(datapoints)
    with torch.inference_mode(), _quiet_lightning_predict():
        trainer = pl.Trainer(
            logger=False,
            enable_progress_bar=False,
            enable_model_summary=False,
            barebones=True,
            accelerator=accelerator,
            devices=1,
        )
        for start in range(0, n_dp, bs):
            chunk = datapoints[start : start + bs]
            dset = data.MoleculeDataset(chunk, featurizer=featurizer)
            loader = data.build_dataloader(dset, shuffle=False, num_workers=0)
            for i, model in enumerate(models):
                batch_preds = trainer.predict(model, loader)
                fold_chunks[i].append(np.concatenate(batch_preds, axis=0))
            if progress_callback is not None:
                done = progress_offset + min(start + len(chunk), n_dp)
                progress_callback(min(done, progress_total), progress_total)
    fold_arrs = [np.concatenate(chunks, axis=0) for chunks in fold_chunks]
    mean = np.mean(np.stack(fold_arrs, axis=0), axis=0)
    out: dict[str, list[float]] = {}
    for j, task in enumerate(tasks):
        if j >= mean.shape[1]:
            break
        out[task] = [float(mean[i, j]) for i in range(mean.shape[0])]
    return out


def predict_adme_batch(
    smiles_list: Sequence[str],
    *,
    output_columns: Sequence[str],
    batch_size: int = 64,
    progress_callback: Callable[[int, int], None] | None = None,
) -> list[dict[str, float] | None]:
    """Predict checked ADME endpoints. Returns one dict per SMILES, or ``None`` if invalid."""
    from chemprop import data

    if not smiles_list:
        return []
    endpoints = endpoints_for_columns(output_columns)
    if not endpoints:
        return [None] * len(smiles_list)
    needed = ensembles_needed(output_columns)

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

    accelerator = adme_lightning_accelerator()
    use_gpu = accelerator == "gpu"
    _log_adme_compute_device(use_gpu)

    task_preds: dict[str, list[float]] = {}
    n_valid = len(datapoints)
    for e_i, name in enumerate(needed):
        part = _predict_ensemble(
            name,
            datapoints,
            batch_size=batch_size,
            accelerator=accelerator,
            progress_callback=progress_callback,
            progress_offset=e_i * n_valid,
            progress_total=n_valid * len(needed),
        )
        task_preds.update(part)

    for j, row_i in enumerate(valid_idx):
        row: dict[str, float] = {}
        for ep in endpoints:
            vals = task_preds.get(ep.task_key)
            if vals is None or j >= len(vals):
                continue
            row[ep.column] = vals[j]
        out[row_i] = row if row else None
    return out


def _format_number(value: float, *, classification: bool) -> str:
    if classification:
        clipped = min(1.0, max(0.0, float(value)))
        text = f"{clipped:.3f}"
        return text.rstrip("0").rstrip(".") if "." in text else text
    if abs(value) < 0.01 or abs(value) >= 1000:
        return f"{value:.4g}"
    text = f"{value:.4f}".rstrip("0").rstrip(".")
    return text or "0"


def format_adme_row(
    values: dict[str, float] | None,
    columns: Sequence[str] | None = None,
) -> dict[str, str]:
    """Format prediction dict for table cells (``N/A`` when missing)."""
    headers = tuple(columns) if columns is not None else ADME_OUTPUT_COLUMNS
    if not values:
        return {h: "N/A" for h in headers}
    out: dict[str, str] = {}
    for h in headers:
        if h not in values:
            out[h] = "N/A"
            continue
        ep = ADME_BY_COLUMN.get(h)
        is_clf = ep is not None and ep.ensemble == ENSEMBLE_CLASSIFICATION
        out[h] = _format_number(values[h], classification=is_clf)
    return out


def mp_predict_adme_chunk(
    smiles: list[str],
    batch_size: int,
    output_columns: tuple[str, ...],
) -> list[dict[str, float] | None]:
    """Process-pool entry: Qt-free so the CUDA child does not import PySide6."""
    pin_permeability_torch_threads()
    return predict_adme_batch(smiles, output_columns=output_columns, batch_size=batch_size)
