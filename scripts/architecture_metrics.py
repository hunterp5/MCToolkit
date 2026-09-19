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
"""Measure the coupling counters that ``architecture-ratchet.json`` freezes.

The ratchet exists because the layering described in ``docs/ARCHITECTURE.md`` is
documented but unenforced: nothing stops a new collaborator from accepting the whole
window, reaching into private window state, or putting chemistry in a Qt module. These
counters may only go down.

Usage::

    python scripts/architecture_metrics.py                  # report
    python scripts/architecture_metrics.py --check          # compare against baseline
    python scripts/architecture_metrics.py --write-baseline # re-freeze after a cleanup
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "molmanager"
TESTS = ROOT / "tests"
BASELINE_PATH = ROOT / "architecture-ratchet.json"

SKIP_DIR_NAMES = frozenset({"__pycache__", "static"})

# The composition root wires the Qt window to everything else, so it imports molmanager.ui
# by definition. Every other module outside molmanager/ui/ must not.
ENTRY_POINTS = frozenset({"molmanager/app.py"})

# Decision layers: plain data in, result objects out (docs/ARCHITECTURE.md "Workflow layer").
DECISION_PACKAGES = ("services", "workflows")

# A counter more than this far below its baseline means the baseline is stale and should
# be re-frozen, so the ratchet keeps its grip after a cleanup lands.
STALE_BASELINE_SLACK = 0.20

# Percentage points of drift allowed in the ui/ share of the codebase. A new dialog may
# nudge it; a new subsystem landing in the Qt layer should not.
UI_SHARE_TOLERANCE_PP = 0.5

# Largest contract a single protocol may declare. A collaborator that cannot state what it
# needs in this many members has not been factored yet, so declaring more is not the fix.
PROTOCOL_MEMBER_CAP = 8

_WINDOW_PARAM_RE = re.compile(r"(?<![\w.])(?:parent_app|app)\s*:\s*(?:\"?AppKernel\"?|Any)\b")
_PRIVATE_ACCESS_RE = re.compile(r"(?<!\w)(?:parent_app|_app|app)\.(_[A-Za-z]\w*)")
_BIND_MIXIN_CALL_RE = re.compile(r"(?<!def )\bbind_mixin_methods\s*\(")


@dataclass
class Metrics:
    """Counters plus the per-file detail used to explain a failure."""

    counters: dict[str, int] = field(default_factory=dict)
    invariants: dict[str, int] = field(default_factory=dict)
    tracked: dict[str, float] = field(default_factory=dict)
    offenders: dict[str, list[str]] = field(default_factory=dict)


def iter_python_files(base: Path) -> list[Path]:
    """Every first-party Python file under *base*, excluding caches and vendored assets."""
    out: list[Path] = []
    for path in sorted(base.rglob("*.py")):
        if SKIP_DIR_NAMES & set(path.parts):
            continue
        out.append(path)
    return out


def _rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def _root_module(node: ast.Import | ast.ImportFrom) -> set[str]:
    """Root names an import statement pulls in, ignoring relative package levels."""
    if isinstance(node, ast.Import):
        return {alias.name.split(".")[0] for alias in node.names}
    if node.level:
        if node.module:
            return {node.module.split(".")[0]}
        return {alias.name.split(".")[0] for alias in node.names}
    if node.module:
        return {node.module.split(".")[0]}
    return set()


def _imports_ui(node: ast.Import | ast.ImportFrom) -> bool:
    """Whether *node* imports ``molmanager.ui``, relatively or absolutely."""
    if isinstance(node, ast.ImportFrom) and node.level:
        return "ui" in _root_module(node)
    for name in _root_module(node):
        if name == "molmanager":
            break
    else:
        return False
    if isinstance(node, ast.Import):
        return any(alias.name.startswith("molmanager.ui") for alias in node.names)
    return bool(node.module and node.module.startswith("molmanager.ui"))


def _type_checking_import_lines(tree: ast.AST) -> set[int]:
    """Line numbers of imports guarded by ``if TYPE_CHECKING:`` (a sanctioned pattern)."""
    guarded: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        test = node.test
        name = (
            test.id
            if isinstance(test, ast.Name)
            else test.attr
            if isinstance(test, ast.Attribute)
            else ""
        )
        if name != "TYPE_CHECKING":
            continue
        for child in ast.walk(node):
            if isinstance(child, (ast.Import, ast.ImportFrom)):
                guarded.add(child.lineno)
    return guarded


def _deferred_intra_package_imports(tree: ast.AST) -> int:
    """Count nested imports of this package: imports that cannot sit at module top.

    Optional third-party dependencies guarded by ``try``/``except ImportError`` are
    absolute and not counted; only first-party imports signal a layering cycle.
    """
    guarded = _type_checking_import_lines(tree)
    total = 0
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        if node.col_offset == 0 or node.lineno in guarded:
            continue
        if isinstance(node, ast.ImportFrom) and node.level:
            total += 1
        elif "molmanager" in _root_module(node):
            total += 1
    return total


def _ui_protocols() -> dict[str, list[str]]:
    """Members declared by each ``Protocol`` under ``ui/``, keyed by ``module::Class``."""
    found: dict[str, list[str]] = {}
    for path in iter_python_files(PACKAGE / "ui"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=_rel(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            if not any(isinstance(b, ast.Name) and b.id == "Protocol" for b in node.bases):
                continue
            names = []
            for member in node.body:
                if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    names.append(member.name)
                elif isinstance(member, ast.AnnAssign) and isinstance(member.target, ast.Name):
                    names.append(member.target.id)
            found[f"{_rel(path)}::{node.name}"] = names
    return found


def _protocol_private_members(protocols: dict[str, list[str]]) -> set[str]:
    """Private window members that some ``ui/`` protocol declares.

    Reading one of these through ``self._app`` is coupling the window has admitted to, so
    ``private_cross_module_access`` skips it: converting a mixin body off
    ``bind_mixin_methods`` must not be punished for turning a hidden ``self._x`` into a
    visible ``self._app._x``. Declaring instead of reaching is the sanctioned move, and
    ``protocols_over_member_cap`` is what stops a protocol from absorbing a whole window.
    """
    return {
        name
        for names in protocols.values()
        for name in names
        if name.startswith("_") and not name.startswith("__")
    }


def _class_defs(path: Path) -> dict[str, ast.ClassDef]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {node.name: node for node in tree.body if isinstance(node, ast.ClassDef)}


def _declared_members(node: ast.ClassDef) -> int:
    return sum(
        1
        for member in node.body
        if isinstance(member, (ast.AnnAssign, ast.FunctionDef, ast.AsyncFunctionDef))
    )


def _app_kernel_member_count() -> int:
    """Total ``AppKernel`` surface: its own members plus every role it inherits.

    Roles are counted so that splitting the kernel into ``app_roles`` protocols does not
    move the number; it drops only when the surface a collaborator can reach shrinks.
    """
    kernel_path = PACKAGE / "ui" / "app_kernel.py"
    classes = _class_defs(kernel_path)
    kernel = classes.get("AppKernel")
    if kernel is None:
        raise AssertionError(f"AppKernel class not found in {_rel(kernel_path)}")
    roles = _class_defs(PACKAGE / "ui" / "app_roles.py")
    total = _declared_members(kernel)
    for base in kernel.bases:
        name = base.id if isinstance(base, ast.Name) else ""
        if name in ("Protocol", ""):
            continue
        role = roles.get(name) or classes.get(name)
        if role is None:
            raise AssertionError(f"AppKernel base {name!r} not found in ui/app_roles.py")
        total += _declared_members(role)
    return total


def collect() -> Metrics:
    """Measure every ratchet counter from the working tree."""
    metrics = Metrics()
    offenders: dict[str, list[str]] = {
        "domain_modules_importing_ui": [],
        "qt_in_decision_layers": [],
        "ui_in_decision_layers": [],
        "rdkit_in_ui_modules": [],
        "modules_taking_the_window": [],
    }

    ui_protocols = _ui_protocols()
    declared_private = _protocol_private_members(ui_protocols)
    offenders["protocols_over_member_cap"] = [
        f"{where} ({len(names)} members)"
        for where, names in sorted(ui_protocols.items())
        if len(names) > PROTOCOL_MEMBER_CAP
    ]
    window_params = 0
    private_access = 0
    deferred_imports = 0
    bind_sites = 0
    mixin_modules = 0
    ui_loc = 0
    total_loc = 0

    for path in iter_python_files(PACKAGE):
        rel = _rel(path)
        text = path.read_text(encoding="utf-8")
        loc = len(text.splitlines())
        total_loc += loc
        in_ui = rel.startswith("molmanager/ui/")
        in_decision = any(rel.startswith(f"molmanager/{pkg}/") for pkg in DECISION_PACKAGES)
        if in_ui:
            ui_loc += loc
        if path.name.endswith("_mixin.py"):
            mixin_modules += 1

        n_window_params = len(_WINDOW_PARAM_RE.findall(text))
        window_params += n_window_params
        if n_window_params:
            offenders["modules_taking_the_window"].append(rel)
        private_access += sum(
            1 for name in _PRIVATE_ACCESS_RE.findall(text) if name not in declared_private
        )
        bind_sites += len(_BIND_MIXIN_CALL_RE.findall(text))

        tree = ast.parse(text, filename=rel)
        deferred_imports += _deferred_intra_package_imports(tree)

        imports_ui = False
        imports_qt = False
        imports_rdkit = False
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Import, ast.ImportFrom)):
                continue
            roots = _root_module(node)
            imports_qt = imports_qt or bool({"PyQt5", "PyQtWebEngine"} & roots)
            imports_rdkit = imports_rdkit or "rdkit" in roots
            imports_ui = imports_ui or _imports_ui(node)

        if imports_ui and not in_ui and rel not in ENTRY_POINTS:
            offenders["domain_modules_importing_ui"].append(rel)
        if in_decision and imports_qt:
            offenders["qt_in_decision_layers"].append(rel)
        if in_decision and imports_ui:
            offenders["ui_in_decision_layers"].append(rel)
        if in_ui and imports_rdkit:
            offenders["rdkit_in_ui_modules"].append(rel)

    # bind_mixin_methods is defined in app_kernel.py; its own definition is not a call site.
    metrics.counters = {
        "window_typed_params": window_params,
        "modules_taking_the_window": len(offenders["modules_taking_the_window"]),
        "private_cross_module_access": private_access,
        "deferred_intra_package_imports": deferred_imports,
        "mixin_modules": mixin_modules,
        "bind_mixin_methods_sites": bind_sites,
        "rdkit_in_ui_modules": len(offenders["rdkit_in_ui_modules"]),
        "app_kernel_members": _app_kernel_member_count(),
    }
    metrics.invariants = {
        "domain_modules_importing_ui": len(offenders["domain_modules_importing_ui"]),
        "qt_in_decision_layers": len(offenders["qt_in_decision_layers"]),
        "ui_in_decision_layers": len(offenders["ui_in_decision_layers"]),
        "protocols_over_member_cap": len(offenders["protocols_over_member_cap"]),
    }

    gui_tests, all_tests = _test_shape()
    metrics.tracked = {
        "declared_private_kernel_members": len(declared_private),
        "ui_loc_share_pct": round(100.0 * ui_loc / total_loc, 1) if total_loc else 0.0,
        "ui_loc": ui_loc,
        "package_loc": total_loc,
        "gui_dependent_test_modules": gui_tests,
        "test_modules": all_tests,
    }
    metrics.offenders = offenders
    return metrics


def _test_shape() -> tuple[int, int]:
    """Count test modules, and how many of them need Qt to run.

    A module needs Qt when it imports Qt or ``molmanager.ui``, or takes the ``qapp``
    fixture. Mentioning ``PyQt5`` in a string does not count.
    """
    total = 0
    gui = 0
    for path in iter_python_files(TESTS):
        if not path.name.startswith("test_"):
            continue
        total += 1
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=_rel(path))
        needs_qt = False
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                needs_qt = needs_qt or bool({"PyQt5", "PyQtWebEngine"} & _root_module(node))
                needs_qt = needs_qt or _imports_ui(node)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                args = node.args
                names = {a.arg for a in (*args.posonlyargs, *args.args, *args.kwonlyargs)}
                needs_qt = needs_qt or "qapp" in names
        if needs_qt:
            gui += 1
    return gui, total


def load_baseline() -> dict:
    return json.loads(BASELINE_PATH.read_text(encoding="utf-8"))


def write_baseline(metrics: Metrics) -> None:
    payload = {
        "note": (
            "Coupling counters frozen by tests/test_architecture_ratchet.py. These may only "
            "go down. Re-freeze with: python scripts/architecture_metrics.py --write-baseline"
        ),
        "counters": metrics.counters,
        "invariants": metrics.invariants,
        "tracked": metrics.tracked,
    }
    BASELINE_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def format_report(metrics: Metrics, baseline: dict | None = None) -> str:
    lines: list[str] = []
    sections = (
        ("counters (may only go down)", metrics.counters),
        ("invariants (must stay 0)", metrics.invariants),
        ("tracked", metrics.tracked),
    )
    for title, values in sections:
        lines.append(title)
        base_values = (baseline or {}).get(title.split(" ")[0], {})
        for name, value in values.items():
            was = base_values.get(name)
            delta = "" if was is None or was == value else f"  (baseline {was})"
            lines.append(f"  {name:<34} {value}{delta}")
    return "\n".join(lines)


def check(metrics: Metrics, baseline: dict) -> list[str]:
    """Return human-readable failures comparing *metrics* against *baseline*."""
    failures: list[str] = []
    base_counters = baseline.get("counters", {})
    for name, value in metrics.counters.items():
        was = base_counters.get(name)
        if was is None:
            failures.append(f"{name}: missing from baseline; re-freeze it")
        elif value > was:
            failures.append(f"{name}: {value} > baseline {was}; move the logic out of the Qt layer")
        elif value < was * (1 - STALE_BASELINE_SLACK):
            failures.append(
                f"{name}: {value} is well below baseline {was}; re-freeze with "
                "python scripts/architecture_metrics.py --write-baseline"
            )
    for name, value in metrics.invariants.items():
        if value:
            detail = ", ".join(metrics.offenders.get(name, ())) or "see report"
            failures.append(f"{name}: expected 0, found {value} ({detail})")
    was_share = baseline.get("tracked", {}).get("ui_loc_share_pct")
    share = metrics.tracked["ui_loc_share_pct"]
    if was_share is not None and share > was_share + UI_SHARE_TOLERANCE_PP:
        failures.append(
            f"ui_loc_share_pct: {share}% exceeds baseline {was_share}% by more than "
            f"{UI_SHARE_TOLERANCE_PP}pp; new logic belongs below the Qt layer"
        )
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail when a counter grew")
    parser.add_argument("--write-baseline", action="store_true", help="re-freeze the baseline")
    parser.add_argument("--offenders", metavar="METRIC", help="list the files behind one metric")
    args = parser.parse_args()

    metrics = collect()

    if args.write_baseline:
        write_baseline(metrics)
        print(f"wrote {_rel(BASELINE_PATH)}")
        print(format_report(metrics))
        return 0

    if args.offenders:
        for rel in metrics.offenders.get(args.offenders, ()):
            print(rel)
        return 0

    baseline = load_baseline() if BASELINE_PATH.is_file() else None
    print(format_report(metrics, baseline))
    if args.check:
        if baseline is None:
            print(f"\nno baseline at {_rel(BASELINE_PATH)}", file=sys.stderr)
            return 1
        failures = check(metrics, baseline)
        if failures:
            print("\narchitecture ratchet failures:", file=sys.stderr)
            for failure in failures:
                print(f"  {failure}", file=sys.stderr)
            return 1
        print("\nok: architecture ratchet holds")
    return 0


if __name__ == "__main__":
    sys.exit(main())
