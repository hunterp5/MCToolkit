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

"""Connectivity-only graph helpers for the molecular sketch."""

from __future__ import annotations

from typing import Any

from .bonds import _bond_unpack


def topology_fingerprint(
    nodes: list[dict[str, Any]],
    bonds: list[tuple[int, int, int, int]],
) -> tuple[tuple[int, ...], tuple[tuple[int, int], ...]]:
    """Stable key for heavy-atom connectivity (ids + undirected edges). Ignores bond order/stereo and atom positions."""
    ids = tuple(sorted(n["id"] for n in nodes))
    edges: list[tuple[int, int]] = []
    for b in bonds:
        a, b0, _, __ = _bond_unpack(b)
        edges.append((min(a, b0), max(a, b0)))
    edges.sort()
    return (ids, tuple(edges))


def connected_components_from_graph(
    nodes: list[dict[str, Any]],
    bonds: list[tuple[int, int, int, int]],
) -> list[set[int]]:
    """Heavy-atom connectivity via bonds. Each isolated atom is its own component."""
    adj: dict[int, set[int]] = {n["id"]: set() for n in nodes}
    for bond in bonds:
        a, b, _, __ = _bond_unpack(bond)
        if a in adj and b in adj:
            adj[a].add(b)
            adj[b].add(a)
    seen: set[int] = set()
    out: list[set[int]] = []
    for n in nodes:
        nid = n["id"]
        if nid in seen:
            continue
        comp: set[int] = set()
        stack = [nid]
        while stack:
            u = stack.pop()
            if u in seen:
                continue
            seen.add(u)
            comp.add(u)
            for v in adj[u]:
                if v not in seen:
                    stack.append(v)
        out.append(comp)
    return out
