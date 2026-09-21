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

"""Prefetch Uni-pKa weights without hitting Hugging Face."""

from __future__ import annotations

from pathlib import Path

import pytest

from mctoolkit.ionization import unipka_install as mod
from mctoolkit.ionization.unipka_install import (
    UNIPKA_MISSING_INSTALL,
    prefetch_unipka_model,
)


def test_prefetch_skips_existing_checkpoint(tmp_path, monkeypatch) -> None:
    ckpt = tmp_path / "fold_1" / "checkpoint_best.pt"
    ckpt.parent.mkdir(parents=True)
    ckpt.write_bytes(b"weights")
    monkeypatch.setattr(mod, "unipka_checkpoint_path", lambda: ckpt)

    def _boom():
        raise AssertionError("must not download when the checkpoint is present")

    monkeypatch.setattr(mod, "_import_downloader", lambda: _boom)
    notes: list[str] = []
    assert prefetch_unipka_model(progress=notes.append) == ckpt
    assert any("Already present" in line for line in notes)


def test_prefetch_downloads_when_missing(tmp_path, monkeypatch) -> None:
    ckpt = tmp_path / "fold_1" / "checkpoint_best.pt"
    monkeypatch.setattr(mod, "unipka_checkpoint_path", lambda: ckpt)

    def _download() -> tuple[Path, ...]:
        ckpt.parent.mkdir(parents=True)
        ckpt.write_bytes(b"downloaded")
        return (ckpt,)

    monkeypatch.setattr(mod, "_import_downloader", lambda: _download)
    notes: list[str] = []
    assert prefetch_unipka_model(progress=notes.append) == ckpt
    assert ckpt.read_bytes() == b"downloaded"
    assert any("Downloading" in line for line in notes)


def test_prefetch_missing_unipkainfer(monkeypatch) -> None:
    def _missing():
        raise ImportError("no unipkainfer")

    monkeypatch.setattr(mod, "_import_downloader", _missing)
    with pytest.raises(RuntimeError, match="unipkainfer is not installed"):
        prefetch_unipka_model()
    assert "requirements.txt" in UNIPKA_MISSING_INSTALL
