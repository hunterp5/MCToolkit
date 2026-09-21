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

"""MolStore payload snapshots without hydrating RDKit mols."""

from __future__ import annotations

from mctoolkit.services.structure_payloads import (
    job_payload_from_store_row,
    payloads_for_oids,
    structure_payloads_by_oid,
)


class _FakeStore:
    def iter_structure_payloads(self):
        yield 1, b"blob-a", "CCO"
        yield 2, None, "CC"

    def get(self, oid):
        raise AssertionError("payload snapshot must not hydrate via get()")


def test_structure_payloads_by_oid_skips_store_get():
    recs = structure_payloads_by_oid(_FakeStore())
    assert recs[1] == (b"blob-a", "CCO")
    assert recs[2] == (None, "CC")


def test_payloads_for_oids_prefers_blob_then_smiles():
    items = payloads_for_oids(_FakeStore(), [2, 1])
    assert items == [(2, "CC"), (1, b"blob-a")]


def test_job_payload_from_store_row_empty():
    assert job_payload_from_store_row(None, "") is None
    assert job_payload_from_store_row(b"", "  ") is None
    assert job_payload_from_store_row(None, "CCO") == "CCO"
