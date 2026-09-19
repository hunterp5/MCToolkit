#!/usr/bin/env python3
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

"""Download BioTransformer 3 (Bitbucket runnable JAR + btkb + supportfiles) into resources."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from molmanager.predictions.biotransformer_install import install_biotransformer


def main() -> int:
    jar = install_biotransformer(progress=print)
    print(f"Ready: {jar}")
    print("Requires Java on PATH (java -version).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
