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

"""Fingerprint session cache LRU behavior."""

from __future__ import annotations

import molmanager.fingerprint_cache as fc


def test_fingerprint_cache_lru_evicts_oldest(monkeypatch):
    fc.clear()
    monkeypatch.setattr(fc, "_max_entries", lambda: 2)
    fc.store(1, "a", object())
    fc.store(2, "a", object())
    assert fc.size() == 2
    # Touch oid 1 so oid 2 is oldest after inserting oid 3.
    assert fc.get(1, "a") is not None
    fc.store(3, "a", object())
    assert fc.size() == 2
    assert fc.get(2, "a") is None
    assert fc.get(1, "a") is not None
    assert fc.get(3, "a") is not None
    fc.clear()
