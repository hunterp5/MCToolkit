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
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with MCToolkit.  If not, see <https://www.gnu.org/licenses/>.
"""Insert the project GPL copyright notice at the top of tracked source files."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

HEADER = """\
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
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with MCToolkit.  If not, see <https://www.gnu.org/licenses/>.
"""

MARKER = "Copyright (C) 2026 Hunter Picard"
SHEBANG_RE = re.compile(r"^#!.*\n")
CODING_RE = re.compile(r"^#.*coding[:=]\s*[-w.]+.*\n", re.IGNORECASE)


def prepend_header(text: str) -> str | None:
    """Return updated file text, or None if the header is already present."""
    if MARKER in text[:800]:
        return None

    prefix = ""
    rest = text
    m = SHEBANG_RE.match(rest)
    if m:
        prefix += m.group(0)
        rest = rest[m.end() :]
    m = CODING_RE.match(rest)
    if m:
        prefix += m.group(0)
        rest = rest[m.end() :]

    # Keep a blank line between the notice and the body when the body is non-empty.
    body = rest.lstrip("\n") if rest.startswith("\n") else rest
    spacer = "\n" if body and not body.startswith("\n") else ""
    return f"{prefix}{HEADER}{spacer}{body}"


def tracked_python_files(root: Path) -> list[Path]:
    out = subprocess.check_output(
        ["git", "ls-files", "*.py"],
        cwd=root,
        text=True,
    )
    return [root / line.strip() for line in out.splitlines() if line.strip()]


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    changed = 0
    skipped = 0
    for path in tracked_python_files(root):
        if not path.is_file():
            continue
        original = path.read_text(encoding="utf-8")
        updated = prepend_header(original)
        if updated is None:
            skipped += 1
            continue
        path.write_text(updated, encoding="utf-8", newline="\n")
        changed += 1
    print(f"updated={changed} already_had_header={skipped}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
