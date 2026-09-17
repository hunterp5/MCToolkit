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
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with MolManager.  If not, see <https://www.gnu.org/licenses/>.

"""Shared helpers for chemistry tool workers."""

from __future__ import annotations

from .signals import WorkerSignals


def normalize_force_field(force_field: str) -> str:
    """Map dialog / param strings onto MMFF, MMFF94s, or UFF."""
    key = (force_field or "MMFF").strip().upper().replace(" ", "")
    if key in {"UFF"}:
        return "UFF"
    if key in {"MMFF94S"}:
        return "MMFF94s"
    return "MMFF"


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
    from ..tool_progress import report_tool_progress

    report_tool_progress(
        message=message,
        done=done,
        total=tot,
        progress_state=progress_state,
        signals=signals,
        throttle=state,
        force_signal=bool(force),
    )
