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

"""IUPAC GR-2.1.5 / GR-2.1.6 atom-label orientation helpers."""

from __future__ import annotations

import re
from typing import Any

# Common condensed / abbreviated labels and their right-attachment (reversed) forms (GR-2.1.6).
_REVERSE_LABELS: dict[str, str] = {
    "OH": "HO",
    "HO": "OH",
    "NH": "HN",
    "HN": "NH",
    "NH2": "H2N",
    "H2N": "NH2",
    "NH3": "H3N",
    "H3N": "NH3",
    "SH": "HS",
    "HS": "SH",
    "PH": "HP",
    "HP": "PH",
    "PH2": "H2P",
    "H2P": "PH2",
    "CH": "HC",
    "HC": "CH",
    "CH2": "H2C",
    "H2C": "CH2",
    "CH3": "H3C",
    "H3C": "CH3",
    "CF3": "F3C",
    "F3C": "CF3",
    "CCl3": "Cl3C",
    "Cl3C": "CCl3",
    "CBr3": "Br3C",
    "Br3C": "CBr3",
    "CN": "NC",
    "NC": "CN",
    "NO2": "O2N",
    "O2N": "NO2",
    "NO": "ON",
    "ON": "NO",
    "OMe": "MeO",
    "MeO": "OMe",
    "OEt": "EtO",
    "EtO": "OEt",
    "OAc": "AcO",
    "AcO": "OAc",
    "OTs": "TsO",
    "TsO": "OTs",
    "OMs": "MsO",
    "MsO": "OMs",
    "COOH": "HOOC",
    "HOOC": "COOH",
    "CO2H": "HO2C",
    "HO2C": "CO2H",
    "CHO": "OHC",
    "OHC": "CHO",
    "SO3H": "HO3S",
    "HO3S": "SO3H",
    "SO2NH2": "H2NO2S",
    "PO3H2": "H2O3P",
    "H2O3P": "PO3H2",
}


def reverse_atom_label(text: str) -> str:
    """
    Reverse a multi-character atom label for right-side attachment (GR-2.1.6).

    The bonded-element symbol stays at the attachment end of the string after reversal
    (e.g. ``OH`` → ``HO``, ``NH2`` → ``H2N``, ``CF3`` → ``F3C``, ``OMe`` → ``MeO``).
    """
    s = str(text or "").strip()
    if not s or len(s) == 1:
        return s
    known = _REVERSE_LABELS.get(s)
    if known is not None:
        return known
    # Element + optional Hn + trailing fragment: move ElementHn to the end.
    m = re.match(r"^([A-Z][a-z]?)(H\d*)?(.*)$", s)
    if m:
        el, h, rest = m.group(1), m.group(2) or "", m.group(3) or ""
        if rest:
            return f"{rest}{h}{el}" if h else f"{rest}{el}"
        if h:
            # NH2 → H2N (H + optional digits + element), not 2HN.
            if h.startswith("H"):
                digits = h[1:]
                return f"H{digits}{el}"
            return f"{h}{el}"
    # Fallback: reverse token-ish by putting the first element symbol at the end.
    m2 = re.match(r"^([A-Z][a-z]?)(.*)$", s)
    if m2 and m2.group(2):
        return f"{m2.group(2)}{m2.group(1)}"
    return s


def neighbor_bond_sides(
    node_id: int,
    pos_xy: tuple[float, float],
    nodes: list[dict[str, Any]],
    bonds: list,
    *,
    unpack,
) -> tuple[bool, bool, bool, bool]:
    """
    Return ``(has_left, has_right, has_up, has_down)`` for bonds at *node_id*.

    Screen coordinates: +x right, +y down.
    """
    by_id = {int(n["id"]): n for n in nodes}
    px, py = pos_xy
    left = right = up = down = False
    for b in bonds:
        a, bo, _o, _s = unpack(b)
        if a != node_id and bo != node_id:
            continue
        oid = bo if a == node_id else a
        on = by_id.get(oid)
        if on is None:
            continue
        dx = float(on["pos"].x()) - px
        dy = float(on["pos"].y()) - py
        if abs(dx) >= abs(dy):
            if dx < -1e-6:
                left = True
            elif dx > 1e-6:
                right = True
        else:
            if dy < -1e-6:
                up = True
            elif dy > 1e-6:
                down = True
    return left, right, up, down


def label_should_reverse(
    text: str,
    *,
    has_left: bool,
    has_right: bool,
) -> bool:
    """
    GR-2.1.6: reverse multi-character labels when bonds are on the right but not the left.

    Single-character labels are never reversed.
    """
    if not text or len(str(text)) <= 1:
        return False
    if has_right and not has_left:
        return True
    return False


def oriented_display_label(text: str, *, reverse: bool) -> str:
    """Return the string to paint for *text*, reversed when *reverse* is set."""
    s = str(text or "")
    if not reverse or len(s) <= 1:
        return s
    return reverse_atom_label(s)
