#!/usr/bin/env python3
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

"""Prefetch Uni-pKa fold weights (~550 MB) so the first Predict pKa is not a download."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mctoolkit.ionization.unipka_install import prefetch_unipka_model


def main() -> int:
    try:
        path = prefetch_unipka_model(progress=print)
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        return 1
    print(f"Uni-pKa weights: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
