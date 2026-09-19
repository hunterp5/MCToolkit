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

"""Conformer table writeback and structure-superpose molecule lookup."""

from __future__ import annotations

from ...chem.molecule_conversion import (
    copy_mol,
    is_rdkit_mol,
    mol_from_molblock,
    mol_to_canonical_smiles,
)
from ...conformers.conformer_output import iter_single_conformer_mols
from ...conformers.conformer_column_codec import (
    demote_v1_cell_to_sidecar,
    make_sidecar_cell,
    rehydrate_v1_confs_cell,
)
from ...services.column_labels import COLUMN_PARENT_OID
from ...storage import EnsembleStore, ensure_confs_sidecar, ensemble_mol_for


def append_generated_conformers_as_rows(app, results: list) -> int:
    """Append one table row per generated conformer; keep 3D coordinates in ``app.mols``."""
    records: list[tuple[str, dict[str, str], object]] = []
    for item in results:
        if len(item) < 2:
            continue
        parent_oid, mol = int(item[0]), item[1]
        if mol is None:
            continue
        for conf_i, cm in enumerate(iter_single_conformer_mols(mol)):
            smi = mol_to_canonical_smiles(cm)
            if not smi:
                continue
            records.append(
                (
                    smi,
                    {
                        COLUMN_PARENT_OID: str(parent_oid),
                        "Conformer": str(conf_i + 1),
                    },
                    cm,
                )
            )
    if not records:
        return 0
    field_names: set[str] = set()
    for _smi, fields, _mol in records:
        field_names.update(fields.keys())
    app._ensure_columns(["SMILES"] + sorted(field_names))
    batch_rows: list[tuple[int, dict[str, str]]] = []
    new_mols: list[tuple[int, object]] = []
    for smiles, fields, mol in records:
        oid = app.next_oid
        app.next_oid += 1
        row_cells: dict[str, str] = {}
        for h in app.headers[2:]:
            if h == "SMILES":
                row_cells[h] = smiles
            else:
                row_cells[h] = str(fields.get(h, "") or "")
        batch_rows.append((oid, row_cells))
        new_mols.append((oid, mol))
    app._table_model.append_rows_batch(batch_rows)
    for oid, mol in new_mols:
        app.mols[oid] = mol
        app.start_render_worker(oid, mol)
    app._sync_global_bounds_for_headers(sorted(field_names), refresh_filters=False)
    return len(batch_rows)


def export_conformer_viewer_to_table(
    app,
    *,
    blocks_json_b64: str,
    conf_indices: list[int] | None = None,
    strain_overlay: dict | None = None,
    parent_oid: int | None = None,
    confs_column: str = "confs",
) -> int:
    """
    Append viewer conformer(s) as table rows.

    Structure gets a 2D depiction; 3D coordinates are packed into *confs_column*
    (created if missing) so View Conformers works again. When *strain_overlay*
    is present, also writes ``E_kcal``, ``(delta)E_kcal``, and ``RMSD``.
    """
    import base64
    import json

    from ..mol_viewer_3d import prepare_mol_2d

    raw = (blocks_json_b64 or "").strip()
    if not raw:
        return 0
    try:
        blocks = json.loads(base64.b64decode(raw.encode("ascii")))
    except Exception:
        return 0
    if not isinstance(blocks, list) or not blocks:
        return 0

    n_blocks = len(blocks)
    if conf_indices is None:
        indices = list(range(n_blocks))
    else:
        indices = [i for i in conf_indices if isinstance(i, int) and 0 <= i < n_blocks]
    if not indices:
        return 0

    confs_col = (confs_column or "confs").strip() or "confs"
    overlay = strain_overlay if isinstance(strain_overlay, dict) else None
    energies = (overlay or {}).get("energies") if overlay else None
    deltas = (overlay or {}).get("deltas") if overlay else None
    rmsds = (overlay or {}).get("rmsds") if overlay else None
    has_e = isinstance(energies, list) and len(energies) == n_blocks
    has_de = isinstance(deltas, list) and len(deltas) == n_blocks
    has_rms = isinstance(rmsds, list) and len(rmsds) == n_blocks

    ensure_cols = ["SMILES", COLUMN_PARENT_OID, "Conformer", confs_col]
    if has_e:
        ensure_cols.append("E_kcal")
    if has_de:
        ensure_cols.append("(delta)E_kcal")
    if has_rms:
        ensure_cols.append("RMSD")
    app._ensure_columns(ensure_cols)

    sc = ensure_confs_sidecar(app)

    def _fmt_num(val) -> str:
        try:
            return f"{float(val):.6g}"
        except Exception:
            return ""

    batch_rows: list[tuple[int, dict[str, str]]] = []
    new_mols: list[tuple[int, object]] = []
    confs_pairs: list[tuple[int, str]] = []
    field_names: set[str] = set()

    for conf_i in indices:
        enc = blocks[conf_i]
        if not isinstance(enc, str) or not enc.strip():
            continue
        try:
            mol_block = base64.b64decode(enc.encode("ascii")).decode("utf-8")
        except Exception:
            continue
        mol3d = mol_from_molblock(mol_block, sanitize=True, remove_hs=False)
        if mol3d is None:
            mol3d = mol_from_molblock(mol_block, sanitize=False, remove_hs=False)
        if mol3d is None:
            continue
        # Structure column keeps a 2D depiction; packed confs holds the 3D coordinates.
        depict = prepare_mol_2d(mol3d)
        if depict is None:
            depict = copy_mol(mol3d) or mol3d

        smi = mol_to_canonical_smiles(depict) or mol_to_canonical_smiles(mol3d) or ""
        meta = {
            "ok": True,
            "op": "viewer_export",
            "n_kept": 1,
            "n_packed": 1,
        }
        light = make_sidecar_cell(confs_col, meta)
        oid = app.next_oid
        app.next_oid += 1
        sc.store_mol(oid, confs_col, mol3d)

        row_cells: dict[str, str] = {}
        for h in app.headers[2:]:
            if h == "SMILES":
                row_cells[h] = smi
            elif h == COLUMN_PARENT_OID:
                row_cells[h] = "" if parent_oid is None else str(int(parent_oid))
            elif h == "Conformer":
                row_cells[h] = str(int(conf_i) + 1)
            elif h == confs_col:
                row_cells[h] = light
            elif h == "E_kcal" and has_e:
                row_cells[h] = _fmt_num(energies[conf_i])
            elif h == "(delta)E_kcal" and has_de:
                row_cells[h] = _fmt_num(deltas[conf_i])
            elif h == "RMSD" and has_rms:
                row_cells[h] = _fmt_num(rmsds[conf_i])
            else:
                row_cells[h] = ""
        batch_rows.append((oid, row_cells))
        new_mols.append((oid, depict))
        confs_pairs.append((oid, light))
        field_names.update(row_cells.keys())

    if not batch_rows:
        return 0

    app.table.setSortingEnabled(False)
    try:
        app.table.setUpdatesEnabled(False)
    except Exception:
        pass
    try:
        app._table_model.append_rows_batch(batch_rows)
        for oid, mol in new_mols:
            app.mols[oid] = mol
            app.start_render_worker(oid, mol)
        if confs_pairs:
            app._table_model.set_column_text_by_oids(confs_col, confs_pairs)
        app._sync_global_bounds_for_headers(sorted(field_names), refresh_filters=False)
        app.schedule_calculate_global_bounds()
    finally:
        try:
            app.table.setUpdatesEnabled(True)
        except Exception:
            pass
    app.status_label.setText(f"Exported {len(batch_rows)} conformer row(s) from the 3D viewer.")
    return len(batch_rows)


def next_packed_ensemble_column(app, base: str) -> str:
    """Return a unique packed-ensemble header, inserting it when it is not already in the table."""
    col = app._unique_table_column_names([base])[0]
    if col not in app.headers:
        col_at = len(app.headers)
        app.headers.append(col)
        app._table_model.insert_column_at(col_at, col, None)
    return col


def write_packed_ensemble_cells(app, column: str, pairs: list[tuple[int, str]]) -> None:
    """Store packed ensembles under *column*, demoting payloads into the sidecar keyed by that header."""
    sc = ensure_confs_sidecar(app)
    out: list[tuple[int, str]] = []
    for oid, cell in pairs:
        light, b64 = demote_v1_cell_to_sidecar(str(cell or ""), column)
        if b64 is not None:
            sc[(int(oid), column)] = b64
        out.append((int(oid), light))
    if out:
        app._table_model.set_column_text_by_oids(column, out)


def write_ensemble_worker_results(app, column: str, results: list) -> None:
    """Write worker tuples ``(oid, mol, meta_or_packed_cell)`` into *column* + ensemble store."""
    packed: list[tuple[int, str]] = []
    mol_rows: list[tuple[int, object | None, dict]] = []
    for item in results:
        if not item or len(item) < 2:
            continue
        oid = int(item[0])
        mol = item[1]
        payload = item[2] if len(item) > 2 else None
        if isinstance(payload, dict):
            mol_rows.append((oid, mol if is_rdkit_mol(mol) else None, payload))
        elif isinstance(payload, str) and payload.strip():
            packed.append((oid, payload))
        elif is_rdkit_mol(mol):
            mol_rows.append((oid, mol, {"ok": True}))
    if packed:
        write_packed_ensemble_cells(app, column, packed)
    if not mol_rows:
        return
    sc = ensure_confs_sidecar(app)
    out: list[tuple[int, str]] = []
    for oid, mol, meta in mol_rows:
        if mol is not None:
            sc.store_mol(oid, column, mol)
        out.append((oid, make_sidecar_cell(column, meta)))
    app._table_model.set_column_text_by_oids(column, out)


def mol_for_ensemble_column(
    app, oid: int, column: str, *, min_conformers: int = 1
) -> object | None:
    """Load a 3D ensemble for *oid*/*column* from the disk store, with packed-cell fallback."""
    from ...conformers.conformer_column_codec import mol_from_packed_confs_cell

    sc = getattr(app, "_confs_blocks_sidecar", None)
    if isinstance(sc, EnsembleStore):
        mol = ensemble_mol_for(sc, oid, column, min_conformers=min_conformers)
        if mol is not None:
            return mol
    mapping = sc if sc is not None else {}
    model = getattr(app, "_table_model", None)
    raw = None
    finder = getattr(app, "logical_row_for_oid", None)
    r = -1
    if callable(finder):
        try:
            r = int(finder(int(oid)))
        except Exception:
            r = -1
    if model is not None and r >= 0:
        raw = model.backing_value_for_row_header(r, column)
    elif model is not None:
        row_oid = getattr(model, "row_oid", None)
        n = 1
        try:
            n = int(model.rowCount())
        except Exception:
            n = 1
        if callable(row_oid):
            for row in range(max(n, 1)):
                try:
                    if int(row_oid(row)) == int(oid):
                        raw = model.backing_value_for_row_header(row, column)
                        break
                except Exception:
                    continue
    if not raw:
        return None
    full = rehydrate_v1_confs_cell(raw, column, int(oid), mapping)
    return mol_from_packed_confs_cell(full, min_conformers=min_conformers)


def mol_3d_for_structure_superpose(app, oid: int, src: str) -> object | None:
    """Best-effort 3D mol for structure superposition from *src* (Structure / confs / …)."""
    from ...conformers.conformer_column_codec import mol_has_3d_coordinates
    from ..mol_viewer_3d import prepare_mol_3d

    r = app.logical_row_for_oid(oid)
    if r < 0:
        return None
    src_h = (src or "Structure").strip() or "Structure"
    if src_h != "Structure" and src_h in app.headers:
        packed = mol_for_ensemble_column(app, oid, src_h, min_conformers=1)
        if packed is not None and mol_has_3d_coordinates(packed):
            return packed
    m = app.mols.get(oid)
    if m is None:
        m = app._mol_for_structure_row(r)
    if m is None:
        return None
    if mol_has_3d_coordinates(m):
        return copy_mol(m) or m
    for col in ("confs", "superpose"):
        if col not in app.headers:
            continue
        packed = mol_for_ensemble_column(app, oid, col, min_conformers=1)
        if packed is not None and mol_has_3d_coordinates(packed):
            return packed
    return prepare_mol_3d(m)


def mol_for_structure_superpose(
    app, oid: int, src: str, *, geometry: str = "3d"
) -> object | None:
    """Molecule for structure superposition; 2D does not require 3D coordinates."""
    geom = str(geometry or "3d").strip().lower()
    if not geom.startswith("2"):
        return mol_3d_for_structure_superpose(app, oid, src)

    r = app.logical_row_for_oid(oid)
    if r < 0:
        return None
    src_h = (src or "Structure").strip() or "Structure"
    if src_h != "Structure" and src_h in app.headers:
        packed = mol_for_ensemble_column(app, oid, src_h, min_conformers=1)
        if packed is not None:
            return packed
    m = app.mols.get(oid)
    if m is None:
        m = app._mol_for_structure_row(r)
    if m is None:
        return None
    return copy_mol(m) or m
