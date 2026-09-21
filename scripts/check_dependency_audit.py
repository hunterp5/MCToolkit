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
"""Run pip-audit and fail CI on critical / malware findings (with ignore list).

pip-audit does not provide a severity cutoff flag. This wrapper:

1. Audits the current environment (JSON).
2. Ignores IDs listed in ``docs/pip-audit-ignore.txt``.
3. Fails on remaining findings that are malware (``MAL-*``) or have severity
   CRITICAL / HIGH when the advisory includes severity metadata.
4. Prints other findings as warnings without failing (document upgrades later).

Document every ignored ID in ``docs/dependency-audit-exceptions.md``.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IGNORE_FILE = ROOT / "docs" / "pip-audit-ignore.txt"
GATE_SEVERITIES = frozenset({"CRITICAL", "HIGH"})


def load_ignore_ids(path: Path) -> set[str]:
    ids: set[str] = set()
    if not path.is_file():
        return ids
    for line in path.read_text(encoding="utf-8").splitlines():
        raw = line.split("#", 1)[0].strip()
        if raw:
            ids.add(raw)
    return ids


def vuln_severity(vuln: dict) -> str | None:
    for key in ("severity", "fix_severity", "cvss_severity"):
        val = vuln.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip().upper()
        if isinstance(val, dict):
            for nested in ("severity", "rating", "level"):
                nested_val = val.get(nested)
                if isinstance(nested_val, str) and nested_val.strip():
                    return nested_val.strip().upper()
    return None


def is_gating(vuln_id: str, severity: str | None) -> bool:
    if vuln_id.upper().startswith("MAL-"):
        return True
    if severity is not None and severity in GATE_SEVERITIES:
        return True
    return False


def main() -> int:
    ignore = load_ignore_ids(IGNORE_FILE)
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pip_audit",
            "--format",
            "json",
            "--progress-spinner",
            "off",
            "--skip-editable",
        ],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    # pip-audit exits 1 when vulns are found; still parse stdout JSON.
    payload_text = proc.stdout.strip()
    if not payload_text:
        print(proc.stderr or "pip-audit produced no JSON output", file=sys.stderr)
        return 2 if proc.returncode not in (0, 1) else proc.returncode

    try:
        data = json.loads(payload_text)
    except json.JSONDecodeError:
        print(payload_text, file=sys.stderr)
        print(proc.stderr, file=sys.stderr)
        return 2

    deps = data if isinstance(data, list) else data.get("dependencies", [])
    gating: list[str] = []
    warnings: list[str] = []

    for dep in deps:
        name = dep.get("name", "?")
        version = dep.get("version", "?")
        for vuln in dep.get("vulns", []) or []:
            vuln_id = str(vuln.get("id") or vuln.get("aliases") or "?")
            aliases = vuln.get("aliases") or []
            ids = {vuln_id, *[str(a) for a in aliases]}
            if ids & ignore:
                continue
            severity = vuln_severity(vuln)
            line = f"{name}=={version}  {vuln_id}  severity={severity or 'unknown'}"
            if is_gating(vuln_id, severity):
                gating.append(line)
            else:
                warnings.append(line)

    if warnings:
        print("Non-gating vulnerabilities (warning only):")
        for line in warnings:
            print(f"  {line}")
        print()

    if gating:
        print("Gating vulnerabilities (CRITICAL/HIGH/malware):", file=sys.stderr)
        for line in gating:
            print(f"  {line}", file=sys.stderr)
        print(
            "\nFix the dependency, or document an exception in "
            "docs/dependency-audit-exceptions.md and docs/pip-audit-ignore.txt",
            file=sys.stderr,
        )
        return 1

    print(f"ok: no gating vulnerabilities (ignored={len(ignore)}, warnings={len(warnings)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
