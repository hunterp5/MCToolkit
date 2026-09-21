#!/usr/bin/env python3
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

"""Download ADMET-AI v2 Chemprop weights (Zenodo 10.5281/zenodo.18728250) into resources."""

from __future__ import annotations

import argparse
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "mctoolkit" / "resources" / "models" / "adme"
ZENODO_DOI = "10.5281/zenodo.18728250"
ZIP_URL = "https://zenodo.org/api/records/18728250/files/swansonk14/admet_ai-v_2.0.1.zip/content"
ENSEMBLES = ("admet_classification", "admet_regression")
N_FOLDS = 5


def _ensemble_complete(dest: Path) -> bool:
    for name in ENSEMBLES:
        folder = dest / name
        if not folder.is_dir():
            return False
        pts = sorted(folder.glob("*.pt"))
        if len(pts) < N_FOLDS:
            return False
        if any(p.stat().st_size <= 0 for p in pts):
            return False
    return True


def _extract_ensembles(zf: zipfile.ZipFile, dest: Path) -> int:
    dest.mkdir(parents=True, exist_ok=True)
    extracted = 0
    for info in zf.infolist():
        if info.is_dir():
            continue
        parts = Path(info.filename).parts
        if "admet_classification" not in parts and "admet_regression" not in parts:
            continue
        if not info.filename.endswith(".pt"):
            continue
        ensemble = "admet_classification" if "admet_classification" in parts else "admet_regression"
        out = dest / ensemble / Path(info.filename).name
        out.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(info) as src, out.open("wb") as dst:
            dst.write(src.read())
        extracted += 1
    return extracted


def download_models(dest: Path = DEST) -> int:
    dest.mkdir(parents=True, exist_ok=True)
    if _ensemble_complete(dest):
        n = sum(len(list((dest / name).glob("*.pt"))) for name in ENSEMBLES)
        print(f"Already present: {dest} ({n} checkpoints)")
        return 0
    print(f"Downloading ADMET-AI v2.0.1 weights from https://doi.org/{ZENODO_DOI} …")
    with tempfile.TemporaryDirectory() as tmp:
        zip_path = Path(tmp) / "admet_ai.zip"
        urllib.request.urlretrieve(ZIP_URL, zip_path)
        with zipfile.ZipFile(zip_path) as zf:
            n = _extract_ensembles(zf, dest)
    if not _ensemble_complete(dest):
        print("Download finished but ensembles are incomplete.", file=sys.stderr)
        return 1
    print(f"Done ({n} checkpoints) -> {dest}")
    print("Dependencies are in requirements.txt (pip install -r requirements.txt).")
    return 0


def verify_load(dest: Path = DEST) -> int:
    if not _ensemble_complete(dest):
        print("Models missing; run this script without --verify first.", file=sys.stderr)
        return 1
    try:
        import torch  # noqa: F401
        from chemprop.models.utils import load_model, load_output_columns
    except (ImportError, OSError, RuntimeError) as e:
        print(f"Chemprop/PyTorch import failed: {e}", file=sys.stderr)
        return 1
    for name in ENSEMBLES:
        folder = dest / name
        paths = sorted(folder.glob("*.pt"))
        print(f"{name}: {len(paths)} folds")
        try:
            tasks = load_output_columns(paths[0])
            load_model(paths[0], multicomponent=False)
        except TypeError:
            tasks = load_output_columns(paths[0])
            load_model(paths[0])
        print(f"  tasks ({len(tasks)}): {', '.join(str(t) for t in tasks)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Load checkpoints with this env's Chemprop and print task names.",
    )
    args = parser.parse_args(argv)
    code = download_models()
    if code != 0:
        return code
    if args.verify:
        return verify_load()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
