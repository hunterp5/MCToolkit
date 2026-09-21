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

"""Uni-pKa protonation-ensemble enumerator (MolGpKa SMARTS templates).

Port of the Apache-2.0 Uni-pKa ``enumerator`` (Luo et al., *JACS Au* 2024,
doi:10.1021/jacsau.4c00271; https://github.com/dptech-corp/Uni-pKa). SMARTS
come from MolGpKa (MIT; Pan et al., *J. Chem. Inf. Model.* 2021,
doi:10.1021/acs.jcim.1c00075). Vendored templates live in
``mctoolkit/resources/unipka/``.
"""

from __future__ import annotations

import csv
import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from rdkit import Chem, RDLogger
from rdkit.Chem import GetFormalCharge

from mctoolkit.platform_support.bundled_paths import resources_dir

logger = logging.getLogger(__name__)

RDLogger.DisableLog("rdApp.*")

_DEFAULT_TEMPLATES = resources_dir() / "unipka" / "simple_smarts_pattern.tsv"
_FULL_TEMPLATES = resources_dir() / "unipka" / "smarts_pattern.tsv"

# Unreasonable chemical structures (Uni-pKa enumerator FILTER_PATTERNS).
_FILTER_SMARTS = (
    "[#6X5]",
    "[#7X5]",
    "[#8X4]",
    "[*r]=[*r]=[*r]",
    "[#1]-[*+1]~[*-1]",
    "[#1]-[*+1]=,:[*]-,:[*-1]",
    "[#1]-[*+1]-,:[*]=,:[*-1]",
    "[*+2]",
    "[*-2]",
    "[#1]-[#8+1].[#8-1,#7-1,#6-1]",
    "[#1]-[#7+1,#8+1].[#7-1,#6-1]",
    "[#1]-[#8+1].[#8-1,#6-1]",
    "[#1]-[#7+1].[#8-1]-[C](-[C,#1])(-[C,#1])",
    "[OX1]=[C]-[OH2+1]",
    "[NX1,NX2H1,NX3H2]=[C]-[O]-[H]",
    "[#6-1]=[*]-[*]",
    "[cX2-1]",
    "[N+1](=O)-[O]-[H]",
)

DEFAULT_CHARGE_LOWER = -2
DEFAULT_CHARGE_UPPER = 2
DEFAULT_MAXITER = 10


@dataclass(frozen=True)
class TemplateRow:
    """One (de)protonation SMARTS rule."""

    name: str
    pattern: Chem.Mol
    index: int
    acid_or_base: str


def _compile_filter_patterns() -> tuple[Chem.Mol, ...]:
    out: list[Chem.Mol] = []
    for smarts in _FILTER_SMARTS:
        pat = Chem.MolFromSmarts(smarts)
        if pat is not None:
            out.append(pat)
    return tuple(out)


FILTER_PATTERNS = _compile_filter_patterns()


def _canon_smiles(mol: Chem.Mol | None) -> str | None:
    if mol is None:
        return None
    try:
        stripped = Chem.RemoveHs(mol)
    except Exception:
        stripped = mol
    try:
        smi = Chem.MolToSmiles(stripped, canonical=True, isomericSmiles=True)
    except Exception:
        return None
    return smi or None


def _mol_from_smi(smi: str) -> Chem.Mol | None:
    mol = Chem.MolFromSmiles(smi)
    if mol is None:
        return None
    try:
        Chem.SanitizeMol(mol)
    except Exception:
        return None
    return mol


def _read_template_rows(path: Path) -> tuple[tuple[TemplateRow, ...], tuple[TemplateRow, ...]]:
    a2b: list[TemplateRow] = []
    b2a: list[TemplateRow] = []
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        for row in reader:
            smarts = (row.get("SMARTS") or "").strip()
            flag = (row.get("Acid_or_base") or "").strip()
            name = (row.get("Substructure") or "").strip()
            try:
                index = int(row.get("Index") or 0)
            except (TypeError, ValueError):
                continue
            pattern = Chem.MolFromSmarts(smarts)
            if pattern is None:
                logger.debug("Skipping unparseable Uni-pKa SMARTS %s (%s)", name, smarts)
                continue
            item = TemplateRow(name=name, pattern=pattern, index=index, acid_or_base=flag)
            if flag == "A":
                a2b.append(item)
            elif flag == "B":
                b2a.append(item)
    return tuple(a2b), tuple(b2a)


@lru_cache(maxsize=4)
def load_templates(
    path: str | None = None,
) -> tuple[tuple[TemplateRow, ...], tuple[TemplateRow, ...]]:
    """Load acid→base and base→acid SMARTS rows (cached per path)."""
    template_path = Path(path) if path else _DEFAULT_TEMPLATES
    if not template_path.is_file():
        raise FileNotFoundError(f"Uni-pKa SMARTS template not found: {template_path}")
    return _read_template_rows(template_path)


def match_template(
    template: tuple[TemplateRow, ...], mol: Chem.Mol, *, add_hs: bool = True
) -> list[int]:
    """Atom indices to (de)protonate on an explicit-H copy of ``mol``."""
    mol_h = Chem.AddHs(mol) if add_hs else mol
    matches: set[int] = set()
    for row in template:
        for hit in mol_h.GetSubstructMatches(row.pattern):
            if 0 <= row.index < len(hit):
                matches.add(int(hit[row.index]))
    return list(matches)


def prot(mol: Chem.Mol, idx: int, mode: str) -> Chem.Mol | None:
    """Protonate (``b2a``) or deprotonate (``a2b``) at atom ``idx`` on an AddHs mol."""
    if mol is None or idx < 0 or idx >= mol.GetNumAtoms():
        return None
    mw = Chem.RWMol(mol)
    try:
        if mode == "a2b":
            atom = mw.GetAtomWithIdx(idx)
            if atom.GetAtomicNum() == 1:
                neighbors = atom.GetNeighbors()
                if not neighbors:
                    return None
                atom_a = neighbors[0]
                atom_a.SetFormalCharge(atom_a.GetFormalCharge() - 1)
                mw.RemoveAtom(idx)
            else:
                h_idxs = [n.GetIdx() for n in atom.GetNeighbors() if n.GetAtomicNum() == 1]
                atom.SetFormalCharge(atom.GetFormalCharge() - 1)
                if h_idxs:
                    mw.RemoveAtom(max(h_idxs))
                else:
                    n_h = atom.GetTotalNumHs()
                    atom.SetNumExplicitHs(max(0, n_h - 1))
                    atom.UpdatePropertyCache(strict=False)
            mol_prot = mw.GetMol()
        elif mode == "b2a":
            atom_b = mw.GetAtomWithIdx(idx)
            atom_b.SetFormalCharge(atom_b.GetFormalCharge() + 1)
            atom_b.SetNumExplicitHs(atom_b.GetNumExplicitHs() + 1)
            mol_prot = Chem.AddHs(mw)
        else:
            return None
        Chem.SanitizeMol(mol_prot)
        smi = Chem.MolToSmiles(mol_prot)
        return _mol_from_smi(smi)
    except Exception:
        return None


def prot_template(template: tuple[TemplateRow, ...], smi: str, mode: str) -> list[str]:
    """Apply every matching (de)protonation site; return unique canonical SMILES."""
    mol = _mol_from_smi(smi)
    if mol is None:
        return []
    mol_h = Chem.AddHs(mol)
    sites = match_template(template, mol_h, add_hs=False)
    out: set[str] = set()
    for site in sites:
        product = prot(mol_h, site, mode)
        canon = _canon_smiles(product)
        if canon:
            out.add(canon)
    return list(out)


def _sanitize_checker_impl(smi: str, filter_patterns: tuple[Chem.Mol, ...]) -> bool:
    mol = _mol_from_smi(smi)
    if mol is None:
        return False
    mol_h = Chem.AddHs(mol)
    for pattern in filter_patterns:
        if mol_h.HasSubstructMatch(pattern):
            return False
    try:
        Chem.SanitizeMol(mol_h)
    except Exception:
        return False
    return True


@lru_cache(maxsize=8192)
def _sanitize_checker_cached(smi: str) -> bool:
    return _sanitize_checker_impl(smi, FILTER_PATTERNS)


def sanitize_checker(smi: str, filter_patterns: tuple[Chem.Mol, ...] = FILTER_PATTERNS) -> bool:
    if filter_patterns is FILTER_PATTERNS:
        return _sanitize_checker_cached(smi)
    return _sanitize_checker_impl(smi, filter_patterns)


def sanitize_filter(
    smis: list[str], filter_patterns: tuple[Chem.Mol, ...] = FILTER_PATTERNS
) -> list[str]:
    return [smi for smi in smis if sanitize_checker(smi, filter_patterns)]


def _stereo_atom_count(smi: str) -> int:
    mol = Chem.MolFromSmiles(smi)
    if mol is None:
        return 0
    return sum(str(atom.GetChiralTag()) != "CHI_UNSPECIFIED" for atom in mol.GetAtoms())


def stereo_filter(smis: list[str]) -> list[str]:
    """Keep the SMILES with the most stereo information per non-stereo graph."""
    best: dict[str, tuple[str, int]] = {}
    for smi in smis:
        try:
            nonstereo = Chem.CanonSmiles(smi, useChiral=0)
        except Exception:
            nonstereo = smi
        count = _stereo_atom_count(smi)
        prev = best.get(nonstereo)
        if prev is None or count > prev[1]:
            best[nonstereo] = (smi, count)
    return [value[0] for value in best.values()]


def _filters(smis: list[str]) -> list[str]:
    return stereo_filter(sanitize_filter(smis))


def enumerate_template(
    smi: str | list[str],
    template_a2b: tuple[TemplateRow, ...],
    template_b2a: tuple[TemplateRow, ...],
    *,
    mode: str = "A",
    maxiter: int = DEFAULT_MAXITER,
) -> tuple[list[str], list[str]]:
    """Grow acid/base microstate pools from ``smi`` (Uni-pKa ``enumerate_template``)."""
    if isinstance(smi, str):
        smis = [smi]
    else:
        smis = list(smi)
    if mode == "A":
        smis_a_pool, smis_b_pool = list(smis), []
    elif mode == "B":
        smis_a_pool, smis_b_pool = [], list(smis)
    else:
        raise ValueError("mode must be 'A' or 'B'")

    pool_length_a = -1
    pool_length_b = -1
    i = 0
    expanded_a: set[str] = set()
    expanded_b: set[str] = set()
    while (len(smis_a_pool) != pool_length_a or len(smis_b_pool) != pool_length_b) and i < maxiter:
        pool_length_a, pool_length_b = len(smis_a_pool), len(smis_b_pool)
        if (mode == "A" and (i + 1) % 2) or (mode == "B" and i % 2):
            for acid_smi in list(smis_a_pool):
                if acid_smi in expanded_a:
                    continue
                expanded_a.add(acid_smi)
                smis_b_pool.extend(_filters(prot_template(template_a2b, acid_smi, "a2b")))
        elif (mode == "B" and (i + 1) % 2) or (mode == "A" and i % 2):
            for base_smi in list(smis_b_pool):
                if base_smi in expanded_b:
                    continue
                expanded_b.add(base_smi)
                smis_a_pool.extend(_filters(prot_template(template_b2a, base_smi, "b2a")))
        smis_a_pool = list(set(_filters(smis_a_pool)))
        smis_b_pool = list(set(_filters(smis_b_pool)))
        i += 1
    return list(smis_a_pool), list(smis_b_pool)


def enumerate_charge_ensemble(
    smi: str,
    *,
    lower: int = DEFAULT_CHARGE_LOWER,
    upper: int = DEFAULT_CHARGE_UPPER,
    maxiter: int = DEFAULT_MAXITER,
    template_path: str | None = None,
) -> dict[int, list[str]]:
    """Enumerate protonation microstates grouped by formal charge (default −2…+2)."""
    mol = _mol_from_smi(smi)
    if mol is None:
        return {}
    start = _canon_smiles(mol) or smi
    q0 = int(GetFormalCharge(mol))
    template_a2b, template_b2a = load_templates(template_path)
    ensemble: dict[int, list[str]] = {q0: [start]}
    smis_0 = [start]

    if q0 > lower:
        smis_0, smis_b1 = enumerate_template(
            smis_0, template_a2b, template_b2a, maxiter=maxiter, mode="A"
        )
        if smis_b1:
            ensemble[q0 - 1] = smis_b1
        for q in range(q0 - 2, lower - 1, -1):
            prev = ensemble.get(q + 1)
            if not prev:
                break
            _, smis_b = enumerate_template(
                prev, template_a2b, template_b2a, maxiter=maxiter, mode="A"
            )
            if smis_b:
                ensemble[q] = smis_b

    if q0 < upper:
        smis_a1, smis_0 = enumerate_template(
            smis_0, template_a2b, template_b2a, maxiter=maxiter, mode="B"
        )
        if smis_a1:
            ensemble[q0 + 1] = smis_a1
        for q in range(q0 + 2, upper + 1):
            prev = ensemble.get(q - 1)
            if not prev:
                break
            smis_a, _ = enumerate_template(
                prev, template_a2b, template_b2a, maxiter=maxiter, mode="B"
            )
            if smis_a:
                ensemble[q] = smis_a

    ensemble[q0] = list(dict.fromkeys(smis_0 or ensemble.get(q0, [start])))
    return {q: list(dict.fromkeys(smis)) for q, smis in sorted(ensemble.items())}


def flatten_charge_ensemble(ensemble: dict[int, list[str]]) -> list[tuple[int, str, Chem.Mol]]:
    """Unique (charge, SMILES, mol) rows, dropping unparseable SMILES."""
    out: list[tuple[int, str, Chem.Mol]] = []
    seen: set[str] = set()
    for charge, smis in ensemble.items():
        for smi in smis:
            if smi in seen:
                continue
            mol = _mol_from_smi(smi)
            if mol is None:
                continue
            seen.add(smi)
            out.append((int(GetFormalCharge(mol)), smi, mol))
    return out
