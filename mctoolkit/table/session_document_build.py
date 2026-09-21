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

"""Finish a session snapshot into a compact ``.mct`` document (no Qt)."""

from __future__ import annotations

from typing import Any

from .session_codec import (
    SESSION_ENSEMBLES_KEY,
    compact_session_document,
    dumps_session_document,
    encode_mol_blob_b64,
)


def fill_structure_session_fields(
    blobs: list[bytes | None], smiles: list[str]
) -> tuple[list[str], list[str]]:
    """Encode mol pickles and fill missing SMILES. RDKit runs only for gaps."""
    from ..chem.molecule_conversion import (
        mol_from_binary_blob,
        mol_graph_binary,
        mol_to_canonical_smiles,
        parse_molecule_from_cell_text,
    )

    n = max(len(blobs), len(smiles))
    out_smi: list[str] = []
    out_b64: list[str] = []
    for i in range(n):
        raw = blobs[i] if i < len(blobs) else None
        smi = str(smiles[i] if i < len(smiles) else "" or "").strip()
        payload = bytes(raw) if raw else None
        if not payload and smi:
            mol = parse_molecule_from_cell_text(smi)
            payload = mol_graph_binary(mol)
        if payload and not smi:
            mol = mol_from_binary_blob(payload)
            try:
                smi = mol_to_canonical_smiles(mol) if mol is not None else ""
            except Exception:  # noqa: BLE001
                smi = ""
        out_smi.append(smi)
        out_b64.append(encode_mol_blob_b64(payload))
    return out_smi, out_b64


def assemble_session_document(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Turn a GUI snapshot (raw blobs, cell text) into the compact session document."""
    blobs = list(snapshot.get("structure_blobs") or [])
    smiles = list(snapshot.get("structure_smiles") or [])
    filled_smi, filled_mols = fill_structure_session_fields(blobs, smiles)
    doc = dict(snapshot)
    ensembles = doc.pop(SESSION_ENSEMBLES_KEY, None)
    doc.pop("structure_blobs", None)
    doc["structure_smiles"] = filled_smi
    doc["structure_mols"] = filled_mols
    out = compact_session_document(doc)
    if ensembles:
        out[SESSION_ENSEMBLES_KEY] = ensembles
    return out


def dumps_session_snapshot(snapshot: dict[str, Any]) -> bytes:
    """Assemble and serialize a session snapshot to gzip ``.mct`` bytes."""
    return dumps_session_document(assemble_session_document(snapshot))
