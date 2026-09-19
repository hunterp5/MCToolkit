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
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with MolManager. If not, see <https://www.gnu.org/licenses/>.

"""Offline tests for BioTransformer package copy (no network)."""

from __future__ import annotations

from pathlib import Path

from molmanager.predictions.biotransformer_install import (
    copy_biotransformer_tree,
    install_biotransformer,
)


def _fake_package(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    jar = root / "BioTransformer3.0_20230525.jar"
    jar.write_bytes(b"jar")
    (root / "btkb").mkdir()
    (root / "supportfiles").mkdir()
    (root / "config.json").write_text("{}", encoding="utf-8")
    (root / "README.md").write_text("upstream", encoding="utf-8")
    return root


def test_copy_biotransformer_tree_keeps_local_readme(tmp_path: Path) -> None:
    src = _fake_package(tmp_path / "src")
    dest = tmp_path / "dest"
    dest.mkdir()
    (dest / "README.md").write_text("local", encoding="utf-8")
    jar = copy_biotransformer_tree(src, dest)
    assert jar.name == "BioTransformer3.0_20230525.jar"
    assert (dest / "btkb").is_dir()
    assert (dest / "supportfiles").is_dir()
    assert (dest / "config.json").is_file()
    assert (dest / "README.md").read_text(encoding="utf-8") == "local"


def test_install_biotransformer_skips_complete_layout(tmp_path: Path) -> None:
    dest = _fake_package(tmp_path / "models")
    jar = install_biotransformer(dest)
    assert jar == dest / "BioTransformer3.0_20230525.jar"
