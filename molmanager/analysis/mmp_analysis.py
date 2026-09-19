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

"""Matched molecular pair (MMP) core: fragment, pair, and apply transforms.

Session payloads live in ``mmp_session``, table write-back in ``mmp_table``,
and pair-atom highlights in ``mmp_depict``.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from statistics import fmean, median

from rdkit import Chem
from rdkit.Chem import rdFMCS, rdMMPA

# Core key type: (core_smiles, sidechain_tuple)
CoreSideKey = tuple[str, tuple[str, ...]]

# Absolute Δ below this is treated as flat for win-rate accounting.
_FLAT_DELTA_EPS = 1e-12


def parse_mmp_core_query(text: str | None) -> Chem.Mol | None:
    """
    Parse an optional core / MCS pattern from SMARTS or SMILES.

    Empty / whitespace returns ``None`` (no core constraint).
    """
    raw = (text or "").strip()
    if not raw:
        return None
    query = Chem.MolFromSmarts(raw)
    if query is not None and query.GetNumAtoms() > 0:
        return query
    mol = Chem.MolFromSmiles(raw)
    if mol is None or mol.GetNumAtoms() < 1:
        return None
    try:
        smarts = Chem.MolToSmarts(mol)
    except Exception:
        return None
    if not smarts:
        return None
    query = Chem.MolFromSmarts(smarts)
    if query is None or query.GetNumAtoms() < 1:
        return None
    return query


def mol_contains_core_query(mol: Chem.Mol | None, query: Chem.Mol | None) -> bool:
    """True when *mol* contains *query* (or when *query* is unset)."""
    if query is None:
        return True
    if mol is None:
        return False
    try:
        return bool(mol.HasSubstructMatch(query))
    except Exception:
        return False


def core_smiles_contains_query(core_smiles: str, query: Chem.Mol | None) -> bool:
    """True when the MMP constant-core SMILES contains *query* as a substructure."""
    if query is None:
        return True
    smi = (core_smiles or "").strip()
    if not smi:
        return False
    core = Chem.MolFromSmiles(smi)
    if core is None:
        return False
    try:
        return bool(core.HasSubstructMatch(query))
    except Exception:
        return False


def filter_fragment_keys_by_core_query(
    keys: Sequence[CoreSideKey],
    query: Chem.Mol | None,
) -> list[CoreSideKey]:
    """Keep only ``(core, sides)`` keys whose constant core contains *query*."""
    if query is None:
        return list(keys)
    return [(core, sides) for core, sides in keys if core_smiles_contains_query(core, query)]


def compute_mcs_smarts(
    mols: Sequence[Chem.Mol],
    *,
    timeout: int = 12,
) -> str:
    """
    Compute an MCS SMARTS for *mols* (RDKit ``FindMCS``).

    Returns an empty string when MCS cannot be found.
    """
    usable = [m for m in mols if m is not None and m.GetNumAtoms() > 0]
    if len(usable) < 2:
        return ""
    try:
        res = rdFMCS.FindMCS(
            usable,
            timeout=max(1, int(timeout)),
            matchValences=True,
            ringMatchesRingOnly=True,
            completeRingsOnly=False,
        )
    except Exception:
        return ""
    if res is None or getattr(res, "canceled", False):
        return ""
    if int(getattr(res, "numAtoms", 0) or 0) < 1:
        return ""
    return str(getattr(res, "smartsString", "") or "").strip()


@dataclass(frozen=True)
class MmpPair:
    """One matched molecular pair linking two table molecules."""

    oid_a: int
    oid_b: int
    smiles_a: str
    smiles_b: str
    activity_a: float
    activity_b: float
    delta_activity: float
    transform: str
    core: str
    sidechain_a: str
    sidechain_b: str


@dataclass(frozen=True)
class TransformSummary:
    """Aggregated evidence for one chemically canonical ``from>>to`` transform on a core."""

    transform: str
    core: str
    sidechain_from: str
    sidechain_to: str
    n: int
    median_delta: float
    mean_delta: float
    win_rate: float
    n_improve: int
    n_worsen: int
    n_flat: int
    min_delta: float
    max_delta: float
    pair_indices: tuple[int, ...]


def canonicalize_pair_direction(pair: MmpPair) -> tuple[str, str, str, float]:
    """
    Orient a pair so sidechains are lexicographically ordered.

    Returns ``(transform, sidechain_from, sidechain_to, delta)`` where
    ``transform`` is ``from>>to`` and ``delta`` is activity(to mol) − activity(from mol)
    after any flip (negated when sides are swapped).
    """
    side_from = pair.sidechain_a
    side_to = pair.sidechain_b
    delta = float(pair.delta_activity)
    if side_from > side_to:
        side_from, side_to = side_to, side_from
        delta = -delta
    return f"{side_from}>>{side_to}", side_from, side_to, delta


def pairs_involving_oid(pairs: Sequence[MmpPair], oid: int) -> list[MmpPair]:
    """Return pairs where *oid* is either partner."""
    ref = int(oid)
    return [p for p in pairs if int(p.oid_a) == ref or int(p.oid_b) == ref]


def orient_pair_relative_to_reference(
    pair: MmpPair, reference_oid: int
) -> tuple[str, str, str, float] | None:
    """
    Orient a pair as ``reference → partner``.

    Returns ``(transform, side_from, side_to, delta)`` where delta is
    activity(partner) − activity(reference), or ``None`` if *reference_oid*
    is not in the pair.
    """
    ref = int(reference_oid)
    if int(pair.oid_a) == ref:
        side_from, side_to = pair.sidechain_a, pair.sidechain_b
        delta = float(pair.delta_activity)
    elif int(pair.oid_b) == ref:
        side_from, side_to = pair.sidechain_b, pair.sidechain_a
        delta = -float(pair.delta_activity)
    else:
        return None
    return f"{side_from}>>{side_to}", side_from, side_to, delta


def reference_oids_in_pairs(pairs: Sequence[MmpPair]) -> list[int]:
    """Sorted unique molecule IDs that appear in at least one pair."""
    oids: set[int] = set()
    for p in pairs:
        oids.add(int(p.oid_a))
        oids.add(int(p.oid_b))
    return sorted(oids)


def aggregate_transforms(
    pairs: Sequence[MmpPair],
    *,
    reference_oid: int | None = None,
) -> list[TransformSummary]:
    """
    Group pairs by core and transform; compute evidence stats.

    When *reference_oid* is set, only pairs involving that molecule are kept and
    each transform is oriented as reference → partner (Δ = partner − reference).
    Otherwise transforms are lexicographically canonicalized.

    Win rate is the fraction of pairs with ``delta > 0`` after orientation.
    Flat pairs (``|delta| < 1e-12``) are counted separately and are not wins.
    Results are sorted by ``|median_delta|`` descending, then ``n`` descending.
    """
    buckets: dict[tuple[str, str], list[tuple[int, float, str, str]]] = defaultdict(list)
    ref = int(reference_oid) if reference_oid is not None else None
    for idx, pair in enumerate(pairs):
        if ref is not None:
            oriented = orient_pair_relative_to_reference(pair, ref)
            if oriented is None:
                continue
            transform, side_from, side_to, delta = oriented
        else:
            transform, side_from, side_to, delta = canonicalize_pair_direction(pair)
        buckets[(pair.core or "", transform)].append((idx, delta, side_from, side_to))

    summaries: list[TransformSummary] = []
    for (core, transform), items in buckets.items():
        deltas = [d for _i, d, _sf, _st in items]
        n = len(deltas)
        n_improve = sum(1 for d in deltas if d > _FLAT_DELTA_EPS)
        n_worsen = sum(1 for d in deltas if d < -_FLAT_DELTA_EPS)
        n_flat = n - n_improve - n_worsen
        side_from = items[0][2]
        side_to = items[0][3]
        summaries.append(
            TransformSummary(
                transform=transform,
                core=core,
                sidechain_from=side_from,
                sidechain_to=side_to,
                n=n,
                median_delta=float(median(deltas)),
                mean_delta=float(fmean(deltas)),
                win_rate=(n_improve / n) if n else 0.0,
                n_improve=n_improve,
                n_worsen=n_worsen,
                n_flat=n_flat,
                min_delta=float(min(deltas)),
                max_delta=float(max(deltas)),
                pair_indices=tuple(i for i, _d, _sf, _st in items),
            )
        )

    summaries.sort(key=lambda s: (-abs(s.median_delta), -s.n, s.core, s.transform))
    return summaries


def pairs_for_transform(
    pairs: Sequence[MmpPair],
    transform: str,
    *,
    core: str | None = None,
) -> list[MmpPair]:
    """Return pairs matching *transform* (and *core* when provided)."""
    key = (transform or "").strip()
    if not key:
        return []
    out: list[MmpPair] = []
    for p in pairs:
        if canonicalize_pair_direction(p)[0] != key:
            continue
        if core is not None and (p.core or "") != core:
            continue
        out.append(p)
    return out


def pairs_for_summary(pairs: Sequence[MmpPair], summary: TransformSummary) -> list[MmpPair]:
    """Return the pairs that contributed to *summary* (by stored indices)."""
    out: list[MmpPair] = []
    for idx in summary.pair_indices:
        if 0 <= idx < len(pairs):
            out.append(pairs[idx])
    return out


def apply_transform_to_mol(
    mol: Chem.Mol,
    side_from: str,
    side_to: str,
    *,
    max_cuts: int | None = None,
    max_cut_bonds: int = 20,
    require_core: str | None = None,
) -> list[str]:
    """
    Apply an MMP ``from>>to`` fragment transform to *mol*.

    Re-fragments the seed with ``rdMMPA.FragmentMol``, keeps cuts whose variable
    side(s) match *side_from*, then ``molzip``s the constant core with *side_to*.
    Returns unique product SMILES (may be empty if the from-fragment is absent).

    Multi-cut transforms use dotted sides (``N[*:1].O[*:2]>>...``); atom-map
    numbers must align between from and to for ``molzip``.
    """
    if mol is None:
        return []
    from_raw = [p.strip() for p in (side_from or "").split(".") if p.strip()]
    to_raw = [p.strip() for p in (side_to or "").split(".") if p.strip()]
    if not from_raw or not to_raw or len(from_raw) != len(to_raw):
        return []

    n_cuts = len(from_raw)
    cuts = max(1, min(int(max_cuts) if max_cuts is not None else n_cuts, 3))
    cuts = max(cuts, n_cuts)
    max_cut_bonds = max(1, int(max_cut_bonds))

    norm_cache: dict[str, str] = {}
    from_key = tuple(sorted(_normalize_fragment_smiles(p, norm_cache) for p in from_raw))
    require_core_n = _normalize_fragment_smiles(require_core, norm_cache) if require_core else None

    try:
        frags = rdMMPA.FragmentMol(
            mol,
            maxCuts=cuts,
            maxCutBonds=max_cut_bonds,
            resultsAsMols=False,
        )
    except Exception:
        return []

    products: list[str] = []
    seen: set[str] = set()

    def _emit(core_smiles: str) -> None:
        core_mol = Chem.MolFromSmiles(core_smiles)
        if core_mol is None:
            return
        combo = core_mol
        for piece in to_raw:
            piece_mol = Chem.MolFromSmiles(piece)
            if piece_mol is None:
                return
            combo = Chem.CombineMols(combo, piece_mol)
        try:
            zipped = Chem.molzip(combo)
            Chem.SanitizeMol(zipped)
            smi = Chem.MolToSmiles(zipped, isomericSmiles=True)
        except Exception:
            return
        if not smi or smi in seen:
            return
        seen.add(smi)
        products.append(smi)

    for core_smi, rest in frags or ():
        core_smi = (core_smi or "").strip()
        rest = (rest or "").strip()
        if not rest:
            continue
        if core_smi:
            sides = tuple(
                sorted(
                    _normalize_fragment_smiles(p, norm_cache) for p in rest.split(".") if p.strip()
                )
            )
            if sides != from_key:
                continue
            core_n = _normalize_fragment_smiles(core_smi, norm_cache)
            if require_core_n is not None and core_n != require_core_n:
                continue
            _emit(core_smi)
            continue

        # Single-cut empty-core form: ``side.core``.
        if n_cuts != 1:
            continue
        parts = [p for p in rest.split(".") if p.strip()]
        if len(parts) != 2:
            continue
        a_n = _normalize_fragment_smiles(parts[0], norm_cache)
        b_n = _normalize_fragment_smiles(parts[1], norm_cache)
        if from_key[0] == a_n:
            core_candidate = parts[1]
            core_n = b_n
        elif from_key[0] == b_n:
            core_candidate = parts[0]
            core_n = a_n
        else:
            continue
        if require_core_n is not None and core_n != require_core_n:
            continue
        _emit(core_candidate)

    return products


def apply_transform_summary_to_mol(
    mol: Chem.Mol,
    summary: TransformSummary,
    *,
    max_cuts: int | None = None,
    max_cut_bonds: int = 20,
    require_core: bool = False,
) -> list[str]:
    """Apply a ledger transform summary to *mol* (optional strict core match)."""
    return apply_transform_to_mol(
        mol,
        summary.sidechain_from,
        summary.sidechain_to,
        max_cuts=max_cuts,
        max_cut_bonds=max_cut_bonds,
        require_core=summary.core if require_core else None,
    )


def _heavy_atom_count(smiles: str, cache: dict[str, int] | None = None) -> int:
    if cache is not None and smiles in cache:
        return cache[smiles]
    mol = Chem.MolFromSmiles(smiles)
    n = 0 if mol is None else int(mol.GetNumHeavyAtoms())
    if cache is not None:
        cache[smiles] = n
    return n


def _normalize_fragment_smiles(smiles: str, cache: dict[str, str] | None = None) -> str:
    if cache is not None and smiles in cache:
        return cache[smiles]
    mol = Chem.MolFromSmiles(smiles)
    out = (smiles or "").strip() if mol is None else Chem.MolToSmiles(mol, isomericSmiles=True)
    if cache is not None:
        cache[smiles] = out
    return out


def fragment_keys_for_mol(
    mol: Chem.Mol,
    *,
    max_cuts: int = 1,
    max_cut_bonds: int = 20,
    core_query: Chem.Mol | None = None,
) -> list[CoreSideKey]:
    """Return unique ``(core, sidechains)`` keys for *mol* (list form for pickling)."""
    keys = list(iter_core_sidechain_keys(mol, max_cuts=max_cuts, max_cut_bonds=max_cut_bonds))
    return filter_fragment_keys_by_core_query(keys, core_query)


def iter_core_sidechain_keys(
    mol: Chem.Mol,
    *,
    max_cuts: int = 1,
    max_cut_bonds: int = 20,
) -> Iterable[CoreSideKey]:
    """
    Yield ``(core_smiles, sidechain_smiles_tuple)`` keys for *mol*.

    For single cuts RDKit returns an empty core and ``side.core`` in the second
    field; the larger fragment is treated as the constant core. Equal-sized
    fragments yield both orientations.
    """
    if mol is None:
        return
    max_cuts = max(1, min(int(max_cuts), 3))
    max_cut_bonds = max(1, int(max_cut_bonds))
    try:
        frags = rdMMPA.FragmentMol(
            mol,
            maxCuts=max_cuts,
            maxCutBonds=max_cut_bonds,
            resultsAsMols=False,
        )
    except Exception:
        return

    norm_cache: dict[str, str] = {}
    heavy_cache: dict[str, int] = {}
    seen: set[CoreSideKey] = set()
    for core_smi, rest in frags or ():
        core_smi = (core_smi or "").strip()
        rest = (rest or "").strip()
        if not rest:
            continue
        if core_smi:
            sides = tuple(
                sorted(
                    _normalize_fragment_smiles(p, norm_cache) for p in rest.split(".") if p.strip()
                )
            )
            if not sides:
                continue
            key = (_normalize_fragment_smiles(core_smi, norm_cache), sides)
            if key not in seen:
                seen.add(key)
                yield key
            continue

        parts = [p for p in rest.split(".") if p.strip()]
        if len(parts) != 2:
            continue
        a = _normalize_fragment_smiles(parts[0], norm_cache)
        b = _normalize_fragment_smiles(parts[1], norm_cache)
        na, nb = _heavy_atom_count(a, heavy_cache), _heavy_atom_count(b, heavy_cache)
        if na == nb:
            orientations = [(a, (b,)), (b, (a,))]
        elif na > nb:
            orientations = [(a, (b,))]
        else:
            orientations = [(b, (a,))]
        for key in orientations:
            if key not in seen:
                seen.add(key)
                yield key


def pairs_from_fragment_records(
    records: list[tuple[int, str, float, list[CoreSideKey]]],
    *,
    max_variable_heavy_atoms: int | None = 13,
    min_activity_difference: float = 0.0,
    max_activity_difference: float = 0.0,
    cancel_check: Callable[[], bool] | None = None,
) -> list[MmpPair]:
    """
    Build MMP pairs from precomputed fragment keys.

    Each record is ``(oid, smiles, activity, fragment_keys)``.
    ``max_activity_difference`` of 0 disables the upper bound.
    """
    min_dact = max(0.0, float(min_activity_difference))
    max_dact = max(0.0, float(max_activity_difference))
    heavy_cache: dict[str, int] = {}
    index: dict[tuple[str, int], list[tuple[int, str, float, str]]] = defaultdict(list)

    for i, (oid, smiles, activity, keys) in enumerate(records):
        if cancel_check is not None and i % 32 == 0 and cancel_check():
            return []
        if not smiles or not keys:
            continue
        for core, sides in keys:
            n_cuts = len(sides)
            if max_variable_heavy_atoms is not None:
                var_atoms = sum(_heavy_atom_count(s, heavy_cache) for s in sides)
                if var_atoms > int(max_variable_heavy_atoms):
                    continue
            side_key = ".".join(sides)
            index[(core, n_cuts)].append((int(oid), side_key, float(activity), smiles))

    # One entry per unordered molecule pair; prefer the smallest structural change.
    best_by_mols: dict[tuple[int, int], MmpPair] = {}
    heavy_pref_cache: dict[str, int] = {}

    for ci, ((core, _n_cuts), entries) in enumerate(index.items()):
        if cancel_check is not None and ci % 16 == 0 and cancel_check():
            break
        by_side: dict[str, list[tuple[int, float, str]]] = defaultdict(list)
        for oid, side_key, activity, smiles in entries:
            by_side[side_key].append((oid, activity, smiles))
        side_keys = list(by_side.keys())
        for i in range(len(side_keys)):
            for j in range(i + 1, len(side_keys)):
                sa, sb = side_keys[i], side_keys[j]
                for oid_a, act_a, smi_a in by_side[sa]:
                    for oid_b, act_b, smi_b in by_side[sb]:
                        if oid_a == oid_b:
                            continue
                        left_oid, right_oid = oid_a, oid_b
                        left_act, right_act = act_a, act_b
                        left_smi, right_smi = smi_a, smi_b
                        left_side, right_side = sa, sb
                        if left_oid > right_oid:
                            left_oid, right_oid = right_oid, left_oid
                            left_act, right_act = right_act, left_act
                            left_smi, right_smi = right_smi, left_smi
                            left_side, right_side = right_side, left_side
                        delta = right_act - left_act
                        if abs(delta) < min_dact:
                            continue
                        if max_dact > 0.0 and abs(delta) > max_dact:
                            continue
                        transform = f"{left_side}>>{right_side}"
                        cand = MmpPair(
                            oid_a=left_oid,
                            oid_b=right_oid,
                            smiles_a=left_smi,
                            smiles_b=right_smi,
                            activity_a=left_act,
                            activity_b=right_act,
                            delta_activity=delta,
                            transform=transform,
                            core=core,
                            sidechain_a=left_side,
                            sidechain_b=right_side,
                        )
                        mol_key = (left_oid, right_oid)
                        prev = best_by_mols.get(mol_key)
                        if prev is None or _pair_rank(cand, heavy_pref_cache) < _pair_rank(
                            prev, heavy_pref_cache
                        ):
                            best_by_mols[mol_key] = cand

    pairs = list(best_by_mols.values())
    pairs.sort(key=lambda p: (-abs(p.delta_activity), p.transform, p.oid_a, p.oid_b))
    return pairs


def _pair_rank(pair: MmpPair, heavy_cache: dict[str, int]) -> tuple[int, int, str]:
    """Lower is better: fewer changing atoms, then shorter transform SMILES."""
    var_atoms = _heavy_atom_count(pair.sidechain_a, heavy_cache) + _heavy_atom_count(
        pair.sidechain_b, heavy_cache
    )
    return (var_atoms, len(pair.transform), pair.transform)


def find_matched_molecular_pairs(
    records: list[tuple[int, Chem.Mol, float]],
    *,
    max_cuts: int = 1,
    max_cut_bonds: int = 20,
    max_variable_heavy_atoms: int | None = 13,
    min_activity_difference: float = 0.0,
    max_activity_difference: float = 0.0,
    core_smarts: str | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> list[MmpPair]:
    """
    Find matched molecular pairs among *records* ``(oid, mol, activity)``.

    ``max_variable_heavy_atoms`` limits the size of the changing fragment
    (``None`` disables the limit). ``min_activity_difference`` keeps only pairs
    whose absolute Δactivity is at least that threshold (0 disables the filter).
    ``max_activity_difference`` keeps only pairs whose absolute Δactivity is at
    most that threshold (0 disables the upper bound).
    When ``core_smarts`` is set, only molecules containing that core/MCS are
    kept, and only fragmentations whose constant core still contains the query.
    Pairs are sorted by absolute Δactivity descending, then by transform.
    """
    core_query = parse_mmp_core_query(core_smarts)
    frag_records: list[tuple[int, str, float, list[CoreSideKey]]] = []
    for i, (oid, mol, activity) in enumerate(records):
        if cancel_check is not None and i % 16 == 0 and cancel_check():
            return []
        if mol is None:
            continue
        if not mol_contains_core_query(mol, core_query):
            continue
        try:
            smiles = Chem.MolToSmiles(mol, isomericSmiles=True)
        except Exception:
            continue
        if not smiles:
            continue
        keys = fragment_keys_for_mol(
            mol,
            max_cuts=max_cuts,
            max_cut_bonds=max_cut_bonds,
            core_query=core_query,
        )
        frag_records.append((int(oid), smiles, float(activity), keys))
    return pairs_from_fragment_records(
        frag_records,
        max_variable_heavy_atoms=max_variable_heavy_atoms,
        min_activity_difference=min_activity_difference,
        max_activity_difference=max_activity_difference,
        cancel_check=cancel_check,
    )
