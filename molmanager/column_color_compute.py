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

"""Column background color RGB computation (gradient / categorical)."""

from __future__ import annotations

import zlib
from dataclasses import dataclass

from PyQt5.QtGui import QColor

from .utils import safe_float


@dataclass(frozen=True)
class ColumnColorRule:
    mode: str
    min_value: float = 0.0
    mid_value: float = 0.5
    max_value: float = 1.0
    low_rgb: int = 0
    mid_rgb: int = 0
    high_rgb: int = 0
    alpha: int = 96


def lerp_channel(c0: int, c1: int, t: float) -> int:
    return int(round(c0 + (c1 - c0) * t))


def color_rgb_for_value(rule: ColumnColorRule, raw_value: str) -> int | None:
    """Return packed RGBA for *raw_value* under *rule*, or ``None`` when uncolored."""
    txt = (raw_value or "").strip()
    if not txt:
        return None
    if rule.mode == "numeric":
        f = safe_float(txt)
        if f is None:
            return None
        lo = rule.min_value
        hi = rule.max_value
        if hi <= lo:
            t = 0.5
        else:
            t = (float(f) - lo) / (hi - lo)
        t = max(0.0, min(1.0, t))
        c0 = QColor.fromRgb(rule.low_rgb)
        c1 = QColor.fromRgb(rule.high_rgb)
        return QColor(
            lerp_channel(c0.red(), c1.red(), t),
            lerp_channel(c0.green(), c1.green(), t),
            lerp_channel(c0.blue(), c1.blue(), t),
            rule.alpha,
        ).rgba()
    if rule.mode == "numeric3":
        f = safe_float(txt)
        if f is None:
            return None
        lo = rule.min_value
        mid = max(lo, min(rule.mid_value, rule.max_value))
        hi = rule.max_value
        fv = float(f)
        if hi <= lo:
            c = QColor.fromRgb(rule.mid_rgb or rule.low_rgb)
            return QColor(c.red(), c.green(), c.blue(), rule.alpha).rgba()
        if fv <= mid:
            span = max(mid - lo, 1e-12)
            t = max(0.0, min(1.0, (fv - lo) / span))
            c0 = QColor.fromRgb(rule.low_rgb)
            c1 = QColor.fromRgb(rule.mid_rgb or rule.high_rgb)
        else:
            span = max(hi - mid, 1e-12)
            t = max(0.0, min(1.0, (fv - mid) / span))
            c0 = QColor.fromRgb(rule.mid_rgb or rule.low_rgb)
            c1 = QColor.fromRgb(rule.high_rgb)
        return QColor(
            lerp_channel(c0.red(), c1.red(), t),
            lerp_channel(c0.green(), c1.green(), t),
            lerp_channel(c0.blue(), c1.blue(), t),
            rule.alpha,
        ).rgba()
    if rule.mode == "categorical":
        hue = zlib.crc32(txt.encode("utf-8", errors="ignore")) % 360
        return QColor.fromHsl(int(hue), 140, 215, rule.alpha).rgba()
    return None
