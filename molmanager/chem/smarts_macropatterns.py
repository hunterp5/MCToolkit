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

"""Parse SMARTS with RDKit ChemAxon-style macropatterns (M, MH, Q, QH, …).

Older RDKit builds accept ``[X]`` / ``[A]`` in ``MolFromSmarts`` but reject ``[M]`` /
``[Q]`` even though ``rdqueries.MAtomQueryAtom`` / ``QAtomQueryAtom`` exist. Expand
those atomic primitives to equivalent atom expressions before parsing so search and
filters accept the full documented macropattern set.
"""

from __future__ import annotations

import re
from functools import lru_cache

from rdkit import Chem
from rdkit.Chem import rdqueries

# Longest match first when scanning atom expressions.
_MACRO_NAMES: tuple[str, ...] = ("MH", "QH", "M", "Q")
_MACRO_TOKEN_RE = re.compile(r"(?<![A-Za-z0-9_#])(MH|QH|M|Q)(?![A-Za-z0-9_])")


@lru_cache(maxsize=1)
def _macro_inner_smarts() -> dict[str, str]:
    """Map macro name → atom expression *without* surrounding brackets."""
    factories = {
        "M": rdqueries.MAtomQueryAtom,
        "MH": rdqueries.MHAtomQueryAtom,
        "Q": rdqueries.QAtomQueryAtom,
        "QH": rdqueries.QHAtomQueryAtom,
    }
    out: dict[str, str] = {}
    for name, factory in factories.items():
        rw = Chem.RWMol()
        rw.AddAtom(factory())
        smarts = Chem.MolToSmarts(rw.GetMol()) or ""
        if smarts.startswith("[") and smarts.endswith("]"):
            out[name] = smarts[1:-1]
        else:
            out[name] = smarts
    return out


def expand_cx_smarts_macros(smarts: str) -> str:
    """
    Expand ChemAxon-style atom macros inside ``[...]`` to RDKit-parseable expressions.

    Leaves already-supported macros (``A``, ``AH``, ``X``, ``XH``, ``*``) unchanged.
    """
    text = smarts or ""
    if not text or not any(name in text for name in _MACRO_NAMES):
        return text
    inners = _macro_inner_smarts()
    if not inners:
        return text

    def _expand_atom_expr(expr: str) -> str:
        return _MACRO_TOKEN_RE.sub(lambda m: inners.get(m.group(1), m.group(1)), expr)

    parts: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch != "[":
            parts.append(ch)
            i += 1
            continue
        depth = 1
        j = i + 1
        while j < n and depth:
            if text[j] == "[":
                depth += 1
            elif text[j] == "]":
                depth -= 1
            j += 1
        if depth != 0:
            parts.append(text[i:])
            break
        inner = text[i + 1 : j - 1]
        parts.append("[" + _expand_atom_expr(inner) + "]")
        i = j
    return "".join(parts)


def mol_from_smarts(smarts: str) -> Chem.Mol | None:
    """``Chem.MolFromSmarts`` with ChemAxon macropattern expansion when needed."""
    text = (smarts or "").strip()
    if not text:
        return None
    try:
        mol = Chem.MolFromSmarts(text)
        if mol is not None:
            return mol
    except Exception:
        mol = None
    expanded = expand_cx_smarts_macros(text)
    if expanded == text:
        return None
    try:
        return Chem.MolFromSmarts(expanded)
    except Exception:
        return None
