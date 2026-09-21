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

"""Session in-memory LRU cache of RDKit fingerprint bit vectors (OID + spec key)."""

from __future__ import annotations

import threading
from collections import OrderedDict
from typing import Any

from rdkit import Chem

from .rdkit_fingerprints import _compute_fingerprint, spec_for_internal_key

_lock = threading.Lock()
_store: OrderedDict[tuple[int, str], Any] = OrderedDict()
_DEFAULT_MAX_ENTRIES = 50_000


def _max_entries() -> int:
    try:
        from ..platform_support.config import load_config

        return max(0, int(load_config().fingerprint_cache_max_entries))
    except Exception:
        return _DEFAULT_MAX_ENTRIES


def _evict_if_needed_unlocked() -> None:
    limit = _max_entries()
    if limit <= 0:
        _store.clear()
        return
    while len(_store) > limit:
        _store.popitem(last=False)


def get(oid: int, internal_key: str) -> Any | None:
    key = (int(oid), str(internal_key))
    with _lock:
        fp = _store.get(key)
        if fp is not None:
            _store.move_to_end(key)
        return fp


def store(oid: int, internal_key: str, fp: Any) -> None:
    if fp is None:
        return
    key = (int(oid), str(internal_key))
    with _lock:
        _store[key] = fp
        _store.move_to_end(key)
        _evict_if_needed_unlocked()


def store_from_mol(oid: int, internal_key: str, mol: Chem.Mol | None) -> Any | None:
    spec = spec_for_internal_key(internal_key)
    if spec is None or mol is None:
        return None
    fp = _compute_fingerprint(mol, spec)
    if fp is not None:
        store(oid, internal_key, fp)
    return fp


def clear() -> None:
    with _lock:
        _store.clear()


def size() -> int:
    """Current number of cached fingerprint entries (for tests / diagnostics)."""
    with _lock:
        return len(_store)
