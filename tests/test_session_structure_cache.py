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

"""Sidecar structure PNG cache for fast session reopen."""

from __future__ import annotations

from pathlib import Path

from molmanager.storage.session_structure_cache import (
    header_matches_session,
    read_structure_cache,
    session_cache_path,
    write_structure_cache,
)
from molmanager.storage.structure_render_store import StructureRenderStore


def test_session_cache_roundtrip(tmp_path: Path) -> None:
    session = tmp_path / "demo.cms"
    session.write_bytes(b'{"format":"molmanager_session","version":2}')
    store = StructureRenderStore()
    try:
        store.ingest_batch([(1, b"png-one"), (2, b"png-two")])
        blob = store.export_sqlite_bytes()
    finally:
        store.close()

    out = write_structure_cache(
        session,
        blob,
        depict_width=180,
        depict_height=140,
        zoomed_ids=[1],
        oid_count=2,
    )
    assert out is not None
    assert out == session_cache_path(session)
    assert out.is_file()

    loaded = read_structure_cache(session, depict_width=180, depict_height=140)
    assert loaded is not None
    header, png_bytes = loaded
    assert header_matches_session(header, session, depict_width=180, depict_height=140)
    assert header["oid_count"] == 2
    assert header["zoomed_ids"] == [1]

    restored = StructureRenderStore()
    try:
        assert restored.import_sqlite_bytes(png_bytes) == 2
        assert set(restored.png_oids()) == {1, 2}
    finally:
        restored.close()


def test_session_cache_rejects_stale_size(tmp_path: Path) -> None:
    session = tmp_path / "demo.cms"
    session.write_bytes(b"v1")
    write_structure_cache(
        session,
        b"not-a-real-sqlite",
        depict_width=10,
        depict_height=10,
        oid_count=0,
    )
    # Corrupt / unreadable sqlite is still rejected by read when header matches;
    # stale identity is the common reopen guard.
    session.write_bytes(b"v1-changed")
    assert read_structure_cache(session, depict_width=10, depict_height=10) is None
