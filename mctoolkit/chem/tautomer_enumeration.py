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

"""Likely tautomer enumeration (RDKit MolStandardize TautomerEnumerator).

This is connectivity tautomerism (keto–enol, heterocycle NH), not ionization.
Charge-state (protomer) enumeration lives in ``ionization/``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from rdkit import Chem
from rdkit.Chem.MolStandardize import rdMolStandardize

from mctoolkit.platform_support.exception_policy import log_swallowed_exception

logger = logging.getLogger(__name__)

DEFAULT_MAX_TAUTOMERS = 8
ENUMERATOR_MAX_TAUTOMERS = 32
ENUMERATOR_MAX_TRANSFORMS = 1000


@dataclass(frozen=True)
class TautomerHit:
    """One unique tautomer SMILES with RDKit tautomer score and role flags."""

    smiles: str
    score: int
    is_canonical: bool
    is_input: bool


def likely_score_cutoff(max_score: int) -> int:
    """Keep forms within a small margin of the best RDKit tautomer score.

    Absolute floor of 3 drops acetone-style enols when the keto scores 5; 3% of
    the max keeps 2-pyridone (102) with 2-hydroxypyridine (100) and drops the
    quinoid (6).
    """
    return int(max_score) - max(3, int(max_score) * 3 // 100)


def canonical_smiles(mol: Chem.Mol | None) -> str | None:
    """Isomeric canonical SMILES, or ``None`` when the mol cannot be written."""
    if mol is None:
        return None
    try:
        smi = Chem.MolToSmiles(mol, canonical=True, isomericSmiles=True)
    except (ValueError, RuntimeError):
        return None
    return smi or None


def enumerate_likely_tautomers(
    mol: Chem.Mol | None,
    *,
    max_tautomers: int = DEFAULT_MAX_TAUTOMERS,
) -> tuple[TautomerHit, ...]:
    """Return unique likely tautomers of *mol*, ranked by RDKit tautomer score.

    Always includes the input form when it can be written. Caps the result at
    ``max_tautomers`` after dropping low-scoring outliers, except the input may
    push the list one past the cap.
    """
    if mol is None:
        return ()
    cap = max(1, min(int(max_tautomers), ENUMERATOR_MAX_TAUTOMERS))
    input_smi = canonical_smiles(mol)
    if not input_smi:
        return ()

    enumerator = rdMolStandardize.TautomerEnumerator()
    enumerator.SetMaxTautomers(ENUMERATOR_MAX_TAUTOMERS)
    enumerator.SetMaxTransforms(ENUMERATOR_MAX_TRANSFORMS)

    try:
        tauts = list(enumerator.Enumerate(mol))
    except Exception:  # noqa: BLE001
        log_swallowed_exception(logger, "Tautomer enumeration failed; keeping the input form")
        return (TautomerHit(input_smi, 0, is_canonical=True, is_input=True),)

    scored: dict[str, int] = {}
    for taut in tauts:
        smi = canonical_smiles(taut)
        if not smi:
            continue
        try:
            score = int(enumerator.ScoreTautomer(taut))
        except Exception:  # noqa: BLE001
            log_swallowed_exception(logger, "Tautomer score failed; treating score as 0")
            score = 0
        prev = scored.get(smi)
        if prev is None or score > prev:
            scored[smi] = score

    if input_smi not in scored:
        try:
            scored[input_smi] = int(enumerator.ScoreTautomer(mol))
        except Exception:  # noqa: BLE001
            log_swallowed_exception(logger, "Input tautomer score failed; treating score as 0")
            scored[input_smi] = 0

    if not scored:
        return (TautomerHit(input_smi, 0, is_canonical=True, is_input=True),)

    canon_smi = input_smi
    try:
        canon_mol = enumerator.Canonicalize(mol)
        written = canonical_smiles(canon_mol)
        if written:
            canon_smi = written
            if canon_smi not in scored:
                scored[canon_smi] = int(enumerator.ScoreTautomer(canon_mol))
    except Exception:  # noqa: BLE001
        log_swallowed_exception(logger, "Canonical tautomer pick failed")

    max_score = max(scored.values())
    cutoff = likely_score_cutoff(max_score)
    ranked = sorted(scored.items(), key=lambda item: (-item[1], item[0]))
    likely = [(smi, score) for smi, score in ranked if score >= cutoff]
    if not likely:
        likely = ranked[:1]

    kept = likely[:cap]
    kept_smiles = {smi for smi, _score in kept}
    if input_smi not in kept_smiles:
        kept.append((input_smi, scored[input_smi]))

    return tuple(
        TautomerHit(
            smiles=smi,
            score=score,
            is_canonical=smi == canon_smi,
            is_input=smi == input_smi,
        )
        for smi, score in kept
    )
