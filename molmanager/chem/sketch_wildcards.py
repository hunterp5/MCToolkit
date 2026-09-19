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

"""Wildcard SMARTS helpers for sketcher atoms."""

from __future__ import annotations

from typing import Any

from rdkit import Chem

from .sketch_symbols import DEFAULT_WILDCARD_ELEMENTS, WILDCARD_ELEMENT, WILDCARD_ELEMENT_CHOICES


def _is_wildcard_node(n: dict[str, Any]) -> bool:
    return n.get("element") == WILDCARD_ELEMENT


def _normalize_wildcard_elements(n: dict[str, Any]) -> list[str]:
    raw = n.get("wildcard_els")
    if not raw:
        return list(DEFAULT_WILDCARD_ELEMENTS)
    out: list[str] = []
    for x in raw:
        s = str(x).strip()
        if s in WILDCARD_ELEMENT_CHOICES and s not in out:
            out.append(s)
    return out or list(DEFAULT_WILDCARD_ELEMENTS)


def _wildcard_symbol_to_smarts_token(symbol: str) -> str | None:
    """
    Map a sketcher element symbol to a SMARTS atom primitive.

    Use atomic numbers (``#6``) rather than organic-subset letters (``C``): in
    Daylight SMARTS, ``C``/``N``/``O`` match *aliphatic* atoms only and miss
    aromatic carbons/nitrogens in table molecules.
    """
    s = (symbol or "").strip()
    if not s:
        return None
    if s == "D":
        return "2#1"
    if s == "T":
        return "3#1"
    try:
        z = int(Chem.GetPeriodicTable().GetAtomicNumber(s))
    except Exception:  # noqa: BLE001
        return None
    if z <= 0:
        return None
    return f"#{z}"


def _wildcard_query_smarts(symbols: list[str], formal_charge: int = 0) -> str:
    """
    SMARTS atom query for a sketcher wildcard.

    Charge must be embedded in the SMARTS (``[#7,#8;+]``): ``SetFormalCharge`` on a
    QueryAtom is ignored by ``MolToSmarts``. Tokens use ``#Z`` so aromatic and
    aliphatic atoms both match.
    """
    tokens: list[str] = []
    seen: set[str] = set()
    for sym in symbols or list(DEFAULT_WILDCARD_ELEMENTS):
        tok = _wildcard_symbol_to_smarts_token(str(sym))
        if tok and tok not in seen:
            seen.add(tok)
            tokens.append(tok)
    if not tokens:
        for sym in DEFAULT_WILDCARD_ELEMENTS:
            tok = _wildcard_symbol_to_smarts_token(sym)
            if tok and tok not in seen:
                seen.add(tok)
                tokens.append(tok)
    tokens.sort()
    body = ",".join(tokens) if tokens else "*"
    fc = int(formal_charge)
    if fc == 0:
        return f"[{body}]"
    if fc > 0:
        ch = f"+{fc}" if fc > 1 else "+"
    else:
        ch = str(fc) if fc < -1 else "-"
    return f"[{body};{ch}]"
