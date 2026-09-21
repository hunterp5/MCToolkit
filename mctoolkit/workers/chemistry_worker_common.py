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

"""Shared helpers for chemistry tool workers."""

from __future__ import annotations

from .signals import WorkerSignals


def normalize_force_field(force_field: str) -> str:
    """Map dialog / param strings onto MMFF, MMFF94s, UFF, GAFF, or GAFF2."""
    key = (force_field or "MMFF").strip().upper().replace(" ", "")
    if key in {"UFF"}:
        return "UFF"
    if key in {"MMFF94S"}:
        return "MMFF94s"
    if key in {"GAFF2", "GAFF-2", "GAFF2.11", "GAFF-2.11"}:
        return "GAFF2"
    if key in {"GAFF", "GAFF1", "GAFF-1.81"}:
        return "GAFF"
    return "MMFF"


def is_gaff_force_field(force_field: str) -> bool:
    """True when *force_field* is GAFF or GAFF2 (AmberTools + OpenMM)."""
    return normalize_force_field(force_field) in {"GAFF", "GAFF2"}


def mmff_variant(force_field: str) -> str:
    """RDKit MMFF variant name for *force_field*."""
    return "MMFF94s" if normalize_force_field(force_field) == "MMFF94s" else "MMFF94"


def emit_tool_progress_throttled(
    signals: WorkerSignals,
    message: str,
    done: int,
    tot: int,
    state: list,
    *,
    progress_state=None,
    force: bool = False,
) -> None:
    """Limit ``tool_progress`` emissions; always refresh ``ToolProgressState`` when provided."""
    from ..platform_support.tool_progress import report_tool_progress

    report_tool_progress(
        message=message,
        done=done,
        total=tot,
        progress_state=progress_state,
        signals=signals,
        throttle=state,
        force_signal=bool(force),
    )
