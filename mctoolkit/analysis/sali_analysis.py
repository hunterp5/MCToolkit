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

"""Structure–Activity Landscape Index (SALI) pair metrics."""

from __future__ import annotations

import heapq
from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class SaliPoint:
    """One molecule pair on the SALI landscape plot."""

    pair_index: int
    oid_a: int
    oid_b: int
    similarity: float
    abs_delta: float
    signed_delta: float
    sali: float


def sali_index(
    abs_delta: float,
    similarity: float,
    *,
    eps: float = 1e-9,
) -> float:
    """
    Structure–Activity Landscape Index.

    ``SALI = |Δactivity| / (1 − similarity)``. When similarity is ≥ ``1 − eps``,
    returns a large finite sentinel so near-identical structures with any Δ remain
    visible rather than producing ``inf``.
    """
    d = abs(float(abs_delta))
    sim = float(similarity)
    denom = 1.0 - sim
    if denom <= float(eps):
        return d / float(eps)
    return d / denom


def _sali_rank_key(point: SaliPoint) -> tuple[float, float, float, int, int]:
    """Larger is better; matches descending SALI, |Δ|, similarity, then smaller OIDs."""
    return (
        float(point.sali),
        float(point.abs_delta),
        float(point.similarity),
        -int(point.oid_a),
        -int(point.oid_b),
    )


def accumulate_sali_candidate(
    heap: list,
    oid_a: int,
    oid_b: int,
    similarity: float,
    act_a: float,
    act_b: float,
    *,
    min_similarity: float,
    min_activity_difference: float,
    max_pairs: int,
) -> None:
    """Push one unordered pair into *heap*, keeping at most *max_pairs* best SALI values.

    ``max_pairs <= 0`` keeps every qualifying pair. *heap* stores ``(rank_key, SaliPoint)``.
    Canonical order is ``oid_a < oid_b`` with ``signed_delta = act_b - act_a``.
    """
    a, b = int(oid_a), int(oid_b)
    if a == b:
        return
    sim_f = float(similarity)
    if sim_f < float(min_similarity):
        return
    va, vb = float(act_a), float(act_b)
    if a > b:
        a, b = b, a
        va, vb = vb, va
    signed = vb - va
    abs_delta = abs(signed)
    if abs_delta < float(min_activity_difference):
        return
    point = SaliPoint(
        pair_index=0,
        oid_a=a,
        oid_b=b,
        similarity=sim_f,
        abs_delta=abs_delta,
        signed_delta=float(signed),
        sali=sali_index(abs_delta, sim_f),
    )
    key = _sali_rank_key(point)
    item = (key, point)
    limit = int(max_pairs)
    if limit <= 0:
        heap.append(item)
        return
    if len(heap) < limit:
        heapq.heappush(heap, item)
        return
    if key > heap[0][0]:
        heapq.heapreplace(heap, item)


def finalize_sali_points(heap: list) -> list[SaliPoint]:
    """Sort accumulated candidates by descending SALI and assign ``pair_index``."""
    items = sorted(heap, key=lambda it: it[0], reverse=True)
    return [
        SaliPoint(
            pair_index=i,
            oid_a=p.oid_a,
            oid_b=p.oid_b,
            similarity=p.similarity,
            abs_delta=p.abs_delta,
            signed_delta=p.signed_delta,
            sali=p.sali,
        )
        for i, (_key, p) in enumerate(items)
    ]


def build_sali_points(
    records: Sequence[tuple[int, float]],
    similarities: Sequence[tuple[int, int, float]],
    *,
    min_similarity: float = 0.0,
    min_activity_difference: float = 0.0,
    max_pairs: int = 0,
) -> list[SaliPoint]:
    """
    Build SALI plot points from activities and pairwise similarities.

    *records* is ``(oid, activity)`` in any order. *similarities* is
    ``(oid_a, oid_b, similarity)`` for unordered pairs. ``max_pairs`` of 0 keeps
    all qualifying pairs; otherwise the highest-SALI pairs are retained.
    """
    act_by_oid = {int(oid): float(act) for oid, act in records}
    min_sim = max(0.0, float(min_similarity))
    min_dact = max(0.0, float(min_activity_difference))
    heap: list = []
    for oid_a, oid_b, sim in similarities:
        a, b = int(oid_a), int(oid_b)
        if a not in act_by_oid or b not in act_by_oid:
            continue
        accumulate_sali_candidate(
            heap,
            a,
            b,
            sim,
            act_by_oid[a],
            act_by_oid[b],
            min_similarity=min_sim,
            min_activity_difference=min_dact,
            max_pairs=max_pairs,
        )
    return finalize_sali_points(heap)
