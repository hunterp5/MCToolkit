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
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with MCToolkit. If not, see <https://www.gnu.org/licenses/>.

"""Snapshot structure store rows as blobs/SMILES without hydrating RDKit mols."""

from __future__ import annotations

from collections.abc import Iterable, Mapping


def structure_payloads_by_oid(
    store, wanted: set[int] | None = None
) -> dict[int, tuple[bytes | None, str]]:
    """``oid -> (blob, smiles)`` from ``MolStore.iter_structure_payloads`` (no RDKit)."""
    bulk = getattr(store, "iter_structure_payloads", None)
    if not callable(bulk):
        return {}
    out: dict[int, tuple[bytes | None, str]] = {}
    for oid, blob, smiles in bulk():
        oid_i = int(oid)
        if wanted is not None and oid_i not in wanted:
            continue
        out[oid_i] = (blob, smiles or "")
    return out


def job_payload_from_store_row(blob: bytes | None, smiles: str | None):
    """Prefer the pickle blob; fall back to SMILES text. ``None`` when both are empty."""
    if blob:
        return bytes(blob)
    smi = (smiles or "").strip()
    return smi or None


def payloads_for_oids(
    store,
    oids: Iterable[int],
    *,
    by_oid: Mapping[int, tuple[bytes | None, str]] | None = None,
) -> list[tuple[int, object]]:
    """``(oid, blob_or_smiles)`` in *oids* order, skipping rows with no stored structure."""
    wanted = [int(o) for o in oids]
    recs = by_oid if by_oid is not None else structure_payloads_by_oid(store, set(wanted))
    items: list[tuple[int, object]] = []
    getter = getattr(store, "get", None)
    for oid in wanted:
        rec = recs.get(int(oid))
        if rec is not None:
            payload = job_payload_from_store_row(rec[0], rec[1])
            if payload is not None:
                items.append((int(oid), payload))
            continue
        if not callable(getter):
            continue
        try:
            mol = getter(oid)
        except Exception:
            mol = None
        if mol is not None:
            items.append((int(oid), mol))
    return items
