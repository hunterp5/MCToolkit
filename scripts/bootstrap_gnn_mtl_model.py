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
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with mctoolkit.  If not, see <https://www.gnu.org/licenses/>.

"""Download the GNN-MTL Chemprop model (Zenodo 10.5281/zenodo.16948542) into resources."""

from __future__ import annotations

import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "mctoolkit" / "resources" / "models" / "gnn_mtl" / "model.pt"
URL = "https://zenodo.org/api/records/16948542/files/model.pt/content"


def main() -> int:
    DEST.parent.mkdir(parents=True, exist_ok=True)
    if DEST.is_file() and DEST.stat().st_size > 0:
        print(f"Already present: {DEST} ({DEST.stat().st_size} bytes)")
        return 0
    print(f"Downloading GNN-MTL model to {DEST} …")
    urllib.request.urlretrieve(URL, DEST)
    print(f"Done ({DEST.stat().st_size} bytes).")
    print("Dependencies are in requirements.txt (pip install -r requirements.txt).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
