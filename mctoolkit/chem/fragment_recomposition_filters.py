# This file is part of MCToolkit.
# Copyright (C) 2026 Hunter Picard
#
# MCToolkit is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# MCToolkit is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with MCToolkit.  If not, see <https://www.gnu.org/licenses/>.

"""Property constraints for BRICS / RECAP fragment recomposition."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable

from rdkit import Chem
from rdkit.Chem import Crippen, Descriptors, Lipinski, QED

from .molecule_conversion import safe_float

_COMPARISON_RE = re.compile(
    r"^\s*(?P<prop>.+?)\s*(?P<op><=|>=|<>|!=|<|>|=)\s*(?P<val>-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)\s*$"
)
_RANGE_RE = re.compile(
    r"^\s*(?P<prop>.+?)\s*(?P<lo>-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)\s*(?:-|to)\s*"
    r"(?P<hi>-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)\s*$",
    re.IGNORECASE,
)

_PROPERTY_ALIASES: dict[str, str] = {
    "mw": "MolWt",
    "molwt": "MolWt",
    "molweight": "MolWt",
    "mol weight": "MolWt",
    "logp": "MolLogP",
    "mologp": "MolLogP",
    "clogp": "MolLogP",
    "tpsa": "TPSA",
    "heavyatoms": "HeavyAtomCount",
    "heavyatomcount": "HeavyAtomCount",
    "heavy atoms": "HeavyAtomCount",
    "hbd": "NumHDonors",
    "numhdonors": "NumHDonors",
    "h-bond donors": "NumHDonors",
    "hba": "NumHAcceptors",
    "numhacceptors": "NumHAcceptors",
    "h-bond acceptors": "NumHAcceptors",
    "rotbonds": "NumRotatableBonds",
    "numrotatablebonds": "NumRotatableBonds",
    "rotatable bonds": "NumRotatableBonds",
    "rings": "RingCount",
    "ringcount": "RingCount",
    "heteroatoms": "NumHeteroatoms",
    "numheteroatoms": "NumHeteroatoms",
    "formalcharge": "NET_FORMAL_CHARGE",
    "netcharge": "NET_FORMAL_CHARGE",
    "net formal charge": "NET_FORMAL_CHARGE",
    "qed": "QED",
    "ro5violations": "RO5_VIOLATIONS",
    "ro5 violations": "RO5_VIOLATIONS",
    "lipinski violations": "RO5_VIOLATIONS",
    "fractioncsp3": "FractionCSP3",
    "fsp3": "FractionCSP3",
    "labuteasa": "LabuteASA",
    "molmr": "MolMR",
    "molar refractivity": "MolMR",
    "aromaticrings": "NumAromaticRings",
    "numaromaticrings": "NumAromaticRings",
    "valenceelectrons": "NumValenceElectrons",
    "numvalenceelectrons": "NumValenceElectrons",
}

_FILTER_PROPERTY_HELP = (
    "MW, LogP, TPSA, HeavyAtoms, HBD, HBA, RotBonds, Rings, Heteroatoms, "
    "FormalCharge, QED, Ro5Violations, FractionCSP3, LabuteASA, MolMR, AromaticRings"
)


def _lipinski_violations(mol: Chem.Mol) -> int:
    n = 0
    if Descriptors.MolWt(mol) > 500.0:
        n += 1
    if Descriptors.MolLogP(mol) > 5.0:
        n += 1
    if Lipinski.NumHDonors(mol) > 5:
        n += 1
    if Lipinski.NumHAcceptors(mol) > 10:
        n += 1
    return n


@dataclass(frozen=True)
class RecompFilterRule:
    """One numeric predicate on a product property."""

    property_key: str
    op: str  # "range" | "eq" | "ne" | "lt" | "lte" | "gt" | "gte"
    lo: float | None = None
    hi: float | None = None
    value: float | None = None


def recomposition_filter_property_help() -> str:
    return _FILTER_PROPERTY_HELP


def normalize_filter_property_name(name: str) -> str:
    key = re.sub(r"\s+", " ", (name or "").strip().lower())
    if not key:
        raise ValueError("Filter property name is required.")
    canonical = _PROPERTY_ALIASES.get(key)
    if canonical:
        return canonical
    compact = key.replace(" ", "")
    canonical = _PROPERTY_ALIASES.get(compact)
    if canonical:
        return canonical
    # Allow direct RDKit descriptor ids (e.g. MolWt, HeavyAtomCount).
    return name.strip()


def parse_recomposition_filter_text(text: str) -> list[RecompFilterRule]:
    """
    Parse comma- or newline-separated AND filters.

    Examples::

        MW 200-500
        LogP <= 5
        HeavyAtoms >= 10
        TPSA < 140
    """
    raw = (text or "").strip()
    if not raw:
        return []
    parts = [p.strip() for chunk in raw.replace("\n", ",").split(",") if (p := chunk.strip())]
    rules: list[RecompFilterRule] = []
    for part in parts:
        m_range = _RANGE_RE.match(part)
        if m_range:
            prop = normalize_filter_property_name(m_range.group("prop"))
            lo = safe_float(m_range.group("lo"))
            hi = safe_float(m_range.group("hi"))
            if lo is None or hi is None:
                raise ValueError(f"Invalid numeric range in filter: {part!r}")
            if lo > hi:
                lo, hi = hi, lo
            rules.append(RecompFilterRule(property_key=prop, op="range", lo=lo, hi=hi))
            continue
        m_cmp = _COMPARISON_RE.match(part)
        if m_cmp:
            prop = normalize_filter_property_name(m_cmp.group("prop"))
            val = safe_float(m_cmp.group("val"))
            if val is None:
                raise ValueError(f"Invalid numeric value in filter: {part!r}")
            op_raw = m_cmp.group("op")
            op = {
                "=": "eq",
                "<>": "ne",
                "!=": "ne",
                "<=": "lte",
                ">=": "gte",
                "<": "lt",
                ">": "gt",
            }[op_raw]
            rules.append(RecompFilterRule(property_key=prop, op=op, value=val))
            continue
        raise ValueError(
            f"Could not parse filter {part!r}. Use forms like 'MW 200-500' or 'LogP <= 5'."
        )
    return rules


def _property_getter(property_key: str) -> Callable[[Chem.Mol], float]:
    if property_key == "MolLogP":
        return lambda m: float(Crippen.MolLogP(m))
    if property_key == "NumHDonors":
        return lambda m: float(Lipinski.NumHDonors(m))
    if property_key == "NumHAcceptors":
        return lambda m: float(Lipinski.NumHAcceptors(m))
    if property_key == "RO5_VIOLATIONS":
        return lambda m: float(_lipinski_violations(m))
    if property_key == "QED":
        return lambda m: float(QED.qed(m))
    if property_key == "NET_FORMAL_CHARGE":
        return lambda m: float(sum(atom.GetFormalCharge() for atom in m.GetAtoms()))
    fn = getattr(Descriptors, property_key, None)
    if fn is not None:
        return lambda m, f=fn: float(f(m))
    raise ValueError(f"Unknown filter property: {property_key}")


def _value_passes_rule(value: float, rule: RecompFilterRule) -> bool:
    if rule.op == "range":
        assert rule.lo is not None and rule.hi is not None
        return rule.lo <= value <= rule.hi
    assert rule.value is not None
    if rule.op == "eq":
        return value == rule.value
    if rule.op == "ne":
        return value != rule.value
    if rule.op == "lt":
        return value < rule.value
    if rule.op == "lte":
        return value <= rule.value
    if rule.op == "gt":
        return value > rule.value
    if rule.op == "gte":
        return value >= rule.value
    raise ValueError(f"Unsupported filter operator: {rule.op}")


def product_passes_filters(mol: Chem.Mol, rules: list[RecompFilterRule]) -> bool:
    if not rules:
        return True
    return product_passes_compiled(mol, compile_recomposition_filters(rules))


def compile_recomposition_filters(
    rules: list[RecompFilterRule],
) -> list[tuple[RecompFilterRule, Callable[[Chem.Mol], float]]]:
    """Pre-build property getters for repeated filter evaluation in a hot loop."""
    getters: dict[str, Callable[[Chem.Mol], float]] = {}
    compiled: list[tuple[RecompFilterRule, Callable[[Chem.Mol], float]]] = []
    for rule in rules:
        if rule.property_key not in getters:
            getters[rule.property_key] = _property_getter(rule.property_key)
        compiled.append((rule, getters[rule.property_key]))
    return compiled


def product_passes_compiled(
    mol: Chem.Mol,
    compiled: list[tuple[RecompFilterRule, Callable[[Chem.Mol], float]]],
) -> bool:
    if not compiled:
        return True
    for rule, getter in compiled:
        try:
            value = getter(mol)
        except Exception:
            return False
        if not _value_passes_rule(value, rule):
            return False
    return True


def filter_product_smiles(
    product_smiles: list[str],
    filter_text: str,
) -> tuple[list[str], int]:
    """
    Keep products whose computed properties satisfy all parsed filter rules.

    Returns ``(kept_smiles, n_filtered_out)``.
    """
    rules = parse_recomposition_filter_text(filter_text)
    if not rules:
        return list(product_smiles), 0
    kept: list[str] = []
    filtered_out = 0
    for smi in product_smiles:
        text = (smi or "").strip()
        if not text:
            filtered_out += 1
            continue
        mol = Chem.MolFromSmiles(text)
        if mol is None or not product_passes_filters(mol, rules):
            filtered_out += 1
            continue
        kept.append(text)
    return kept, filtered_out
