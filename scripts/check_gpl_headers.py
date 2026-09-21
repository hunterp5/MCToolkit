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
"""Fail CI if tracked first-party Python files lack the mctoolkit GPL header."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

MARKER = "Copyright (C) 2026 Hunter Picard"
SKIP_PREFIXES = ("mctoolkit/ui/static/",)


def tracked_python_files(root: Path) -> list[Path]:
    out = subprocess.check_output(
        ["git", "ls-files", "*.py"],
        cwd=root,
        text=True,
    )
    files: list[Path] = []
    for line in out.splitlines():
        rel = line.strip().replace("\\", "/")
        if not rel:
            continue
        if any(rel.startswith(prefix) for prefix in SKIP_PREFIXES):
            continue
        files.append(root / rel)
    return files


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    missing: list[str] = []
    for path in tracked_python_files(root):
        if not path.is_file():
            continue
        head = path.read_text(encoding="utf-8", errors="replace")[:800]
        if MARKER not in head:
            missing.append(str(path.relative_to(root)).replace("\\", "/"))
    if missing:
        print("Missing GPL copyright header:", file=sys.stderr)
        for rel in missing:
            print(f"  {rel}", file=sys.stderr)
        print(
            "\nAdd the standard header (see docs/CONTRIBUTING.md) "
            "or run: python scripts/add_gpl_headers.py",
            file=sys.stderr,
        )
        return 1
    print(f"ok: {len(tracked_python_files(root))} tracked Python files have GPL headers")
    return 0


if __name__ == "__main__":
    sys.exit(main())
