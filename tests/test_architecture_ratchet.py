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
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with mctoolkit. If not, see <https://www.gnu.org/licenses/>.

"""Freeze the coupling counters in ``architecture-ratchet.json`` against growth.

``docs/ARCHITECTURE.md`` describes the layering; these tests are what enforce it. The
counters measure how much the Qt layer owns that it should not: modules that accept the
whole window, private window state read across module boundaries, chemistry imported into
Qt modules, and first-party imports that cannot sit at module top because of a cycle.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load_metrics_module():
    """Import the checker by path; ``scripts/`` is not a package and must not be on sys.path."""
    path = ROOT / "scripts" / "architecture_metrics.py"
    spec = importlib.util.spec_from_file_location("architecture_metrics", path)
    assert spec and spec.loader, f"cannot load {path}"
    module = importlib.util.module_from_spec(spec)
    # dataclasses resolves annotations through sys.modules, so register before executing.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


am = _load_metrics_module()


@pytest.fixture(scope="module")
def metrics() -> am.Metrics:
    return am.collect()


@pytest.fixture(scope="module")
def baseline() -> dict:
    assert am.BASELINE_PATH.is_file(), (
        f"missing {am.BASELINE_PATH.name}; create it with "
        "python scripts/architecture_metrics.py --write-baseline"
    )
    return am.load_baseline()


def test_coupling_counters_do_not_grow(metrics: am.Metrics, baseline: dict) -> None:
    """New code must not add window-shaped dependencies, only remove them."""
    grew = []
    for name, value in metrics.counters.items():
        was = baseline["counters"].get(name)
        assert was is not None, f"{name} is missing from the baseline; re-freeze it"
        if value > was:
            grew.append(f"{name}: {value} > baseline {was}")
    assert not grew, (
        "Architecture ratchet grew:\n  "
        + "\n  ".join(grew)
        + "\nPut the decision in mctoolkit/workflows/ or the computation in "
        "mctoolkit/services/ instead of the Qt layer. See docs/ARCHITECTURE.md."
    )


def test_layering_invariants_hold(metrics: am.Metrics) -> None:
    """Domain code never imports the UI, and decision layers never import Qt."""
    for name, value in metrics.invariants.items():
        offenders = ", ".join(metrics.offenders.get(name, ())) or "unknown"
        assert value == 0, f"{name}: expected 0, found {value} ({offenders})"


def test_ui_share_of_codebase_does_not_drift(metrics: am.Metrics, baseline: dict) -> None:
    """Two-thirds of the code is Qt today; new subsystems must not deepen that."""
    was = baseline["tracked"]["ui_loc_share_pct"]
    share = metrics.tracked["ui_loc_share_pct"]
    assert share <= was + am.UI_SHARE_TOLERANCE_PP, (
        f"mctoolkit/ui/ is {share}% of the package, over the {was}% baseline by more than "
        f"{am.UI_SHARE_TOLERANCE_PP}pp. Widgets belong in ui/; decisions do not."
    )


def test_baseline_is_not_stale(metrics: am.Metrics, baseline: dict) -> None:
    """A counter far below its baseline means the ratchet lost its grip."""
    stale = [
        f"{name}: {value} vs baseline {baseline['counters'][name]}"
        for name, value in metrics.counters.items()
        if value < baseline["counters"].get(name, 0) * (1 - am.STALE_BASELINE_SLACK)
    ]
    assert not stale, (
        "Architecture ratchet is looser than the code:\n  "
        + "\n  ".join(stale)
        + "\nRe-freeze it: python scripts/architecture_metrics.py --write-baseline"
    )


def test_decision_layers_import_no_qt_at_runtime() -> None:
    """Importing a workflow must not load PySide6 (generalizes test_tool_readiness)."""
    import importlib

    for name in list(sys.modules):
        if name.startswith("mctoolkit.workflows"):
            del sys.modules[name]
    qt_already_loaded = "PySide6.QtWidgets" in sys.modules
    package = ROOT / "mctoolkit" / "workflows"
    for path in sorted(package.glob("*.py")):
        module = f"mctoolkit.workflows.{path.stem}" if path.stem != "__init__" else None
        importlib.import_module(module or "mctoolkit.workflows")
    if not qt_already_loaded:
        assert "PySide6.QtWidgets" not in sys.modules, "a workflow pulled in Qt"
