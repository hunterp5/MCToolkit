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

"""Keep Windows from idle-suspending while a calculation job is running."""

from __future__ import annotations

import sys

# ES_CONTINUOUS | ES_SYSTEM_REQUIRED — blocks idle suspend / Modern Standby;
# the display may still turn off. Lid-close and Start-menu Sleep are not blocked.
_ES_CONTINUOUS = 0x80000000
_ES_SYSTEM_REQUIRED = 0x00000001

_held = False


def set_system_required_while_busy(busy: bool) -> bool:
    """Hold or release ``ES_SYSTEM_REQUIRED`` while *busy* is true.

    Returns True when the Windows API call succeeded (or was a no-op on the
    same state). Always returns False on non-Windows platforms.
    """
    global _held
    if sys.platform != "win32":
        return False
    want = bool(busy)
    if want == _held:
        return True
    try:
        import ctypes
    except (ImportError, OSError, AttributeError):
        return False
    flags = _ES_CONTINUOUS | (_ES_SYSTEM_REQUIRED if want else 0)
    try:
        ctypes.windll.kernel32.SetThreadExecutionState(flags)
    except (AttributeError, OSError):
        return False
    _held = want
    return True


def clear_system_required() -> None:
    """Drop any held execution-state request (call on app exit)."""
    set_system_required_while_busy(False)
