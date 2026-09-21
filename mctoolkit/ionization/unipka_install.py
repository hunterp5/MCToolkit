# This file is part of MCToolkit.
# Copyright (C) 2026 Hunter Picard
#
# MCToolkit is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# MCToolkit is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with MCToolkit. If not, see <https://www.gnu.org/licenses/>.

"""Prefetch Uni-pKa fold weights into unipkainfer's per-user model directory.

The Hugging Face checkpoint is ~550 MB, so it is not stored in git or the
mctoolkit wheel. ``pip install`` cannot fetch it. Call this after the pKa
stack is installed so the first Predict pKa job does not download weights.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

ProgressFn = Callable[[str], None]

UNIPKA_MISSING_INSTALL = (
    "unipkainfer is not installed. Install the pKa stack first:\n"
    "  pip install -r requirements.txt\n"
    "  or: pip install 'mctoolkit[pka]'"
)


def _emit(progress: ProgressFn | None, message: str) -> None:
    if progress is not None:
        progress(message)


def _import_downloader():
    from unipkainfer.download_model import download_unipka_model

    return download_unipka_model


def unipka_checkpoint_path() -> Path:
    """Local path for the default Uni-pKa fold checkpoint (may not exist yet)."""
    from unipkainfer.models import DEFAULT_FOLD
    from unipkainfer.paths import default_model_dir

    return default_model_dir() / f"fold_{DEFAULT_FOLD}" / "checkpoint_best.pt"


def prefetch_unipka_model(*, progress: ProgressFn | None = None) -> Path:
    """Download and verify the default Uni-pKa fold if it is not already on disk.

    Returns the checkpoint path. Raises ``RuntimeError`` when unipkainfer is
    missing or the download fails.
    """
    try:
        download_unipka_model = _import_downloader()
    except ImportError as exc:
        raise RuntimeError(UNIPKA_MISSING_INSTALL) from exc

    ckpt = unipka_checkpoint_path()
    if ckpt.is_file() and ckpt.stat().st_size > 0:
        _emit(progress, f"Already present: {ckpt} ({ckpt.stat().st_size} bytes)")
        return ckpt

    _emit(progress, f"Downloading Uni-pKa fold weights to {ckpt.parent.parent} (~550 MB)…")
    try:
        paths = download_unipka_model()
    except (OSError, RuntimeError, ValueError) as exc:
        raise RuntimeError(f"Uni-pKa weight download failed: {exc}") from exc
    ready = Path(paths[0]) if paths else ckpt
    _emit(progress, f"Ready: {ready} ({ready.stat().st_size if ready.is_file() else 0} bytes)")
    return ready
