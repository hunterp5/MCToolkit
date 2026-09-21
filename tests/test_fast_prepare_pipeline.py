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

"""Fast Prepare end-to-end: one fused job writes the neutralized parent and the fragments column."""

from __future__ import annotations

from rdkit import Chem
from PySide6.QtGui import QPixmap

from mctoolkit.storage.structure_render_store import StructureRenderStore

from mctoolkit.ui.main_window import ChemistryWorkspaceWindow
from mctoolkit.chem.molecule_conversion import mol_to_canonical_smiles
from mctoolkit.workers.fast_prepare import FastPrepareParams, FastPrepareWorker

SALTS = [
    "CC(=O)Oc1ccccc1C(=O)[O-].[Na+]",
    "C[NH+](C)C.[Cl-]",
    "c1ccccc1",
]


def _seeded_window() -> ChemistryWorkspaceWindow:
    win = ChemistryWorkspaceWindow()
    win.headers = ["ID_HIDDEN", "Structure", "SMILES"]
    win._table_model.set_headers(list(win.headers))
    win.table.setColumnHidden(0, True)
    for smiles in SALTS:
        mol = Chem.MolFromSmiles(smiles)
        assert mol is not None
        oid = win.next_oid
        win.next_oid += 1
        cells = win._ingest_store_mol(oid, mol)
        cells["SMILES"] = smiles
        win._table_model.append_row(oid, cells)
    return win


def _run_fast_prepare_inline(
    win: ChemistryWorkspaceWindow, src: str, *, neutralize: bool = False
) -> None:
    """Run the worker synchronously, then feed its results to the real GUI handler."""
    prepare_col = getattr(win, "_fast_prepare_source", src)
    need_smiles = win._fast_prepare_target_is_text(prepare_col)
    is_smiles = src != "Structure"
    if is_smiles:
        col = win.headers.index(src)
        items = [
            (oid, win._table_cell_text(win.logical_row_for_oid(oid), col))
            for oid in win._all_oids_in_table_order()
        ]
    else:
        items = [
            (oid, win.mols.get(oid), None)
            for oid in win._all_oids_in_table_order()
            if win.mols.get(oid) is not None
        ]

    captured: list = []

    class _Sig:
        def __init__(self, sink):
            self._sink = sink

        def emit(self, *args):
            self._sink(*args)

    class _Recorder:
        fast_prepared = _Sig(captured.append)
        tool_progress = _Sig(lambda *_a: None)
        partial_results = _Sig(lambda *_a: None)

    FastPrepareWorker(
        items,
        FastPrepareParams(
            is_smiles=is_smiles,
            need_smiles=need_smiles,
            neutralize=neutralize,
            need_png=prepare_col == "Structure",
            png_width=32 if prepare_col == "Structure" else 0,
            png_height=32 if prepare_col == "Structure" else 0,
            process_pool_min_rows=10**9,
        ),
        _Recorder(),
    ).run()
    assert captured, "worker emitted no results"
    win.on_fast_prepare_finished(captured[0])


def test_fast_prepare_structure_target_neutralizes_and_lists_fragments(qapp):  # noqa: ARG001
    win = _seeded_window()
    try:
        win._fast_prepare_source = "Structure"
        win._fast_prepare_fragments_col = "Fragments"
        win._fast_prepare_update_target = True
        win._fast_prepare_allowed_oids = None

        _run_fast_prepare_inline(win, "Structure", neutralize=True)

        assert "Fragments" in win.headers
        assert len(win.mols) == len(SALTS)
        assert len(win.mols._lru) == 0
        for mol in win.mols.values():
            assert Chem.GetFormalCharge(mol) == 0
            assert len(Chem.GetMolFrags(mol)) == 1

        frag_col = win.headers.index("Fragments")
        frag_values = {
            win._table_cell_text(win.logical_row_for_oid(oid), frag_col) for oid in win.mols
        }
        assert mol_to_canonical_smiles(Chem.MolFromSmiles("[Cl-]")) in frag_values
        assert "" in frag_values  # benzene has no smaller fragments
        assert getattr(win, "_render2d_batch_active", False) is False
        assert win._table_model.structure_png_store_active()
    finally:
        win.close()


def test_fast_prepare_new_column_target_gets_canonical_smiles(qapp):  # noqa: ARG001
    win = _seeded_window()
    try:
        target = "Largest fragment SMILES"
        win._fast_prepare_source = target
        win._fast_prepare_fragments_col = "Fragments"
        win._fast_prepare_update_target = False
        win._fast_prepare_allowed_oids = None

        # A column the dialog named but that does not exist yet must still count as a text target,
        # otherwise the worker would skip canonical SMILES and the column would be written empty.
        assert win._fast_prepare_target_is_text(target) is True

        _run_fast_prepare_inline(win, "Structure", neutralize=True)

        assert target in win.headers
        col = win.headers.index(target)
        values = [
            win._table_cell_text(win.logical_row_for_oid(oid), col)
            for oid in win._all_oids_in_table_order()
        ]
        assert all(v for v in values), f"expected SMILES in every row, got {values}"
        for v in values:
            parsed = Chem.MolFromSmiles(v)
            assert parsed is not None
            assert Chem.GetFormalCharge(parsed) == 0
            assert len(Chem.GetMolFrags(parsed)) == 1
    finally:
        win.close()


def test_fast_prepare_structure_target_is_not_text(qapp):  # noqa: ARG001
    win = _seeded_window()
    try:
        assert win._fast_prepare_target_is_text("Structure") is False
        assert win._fast_prepare_target_is_text("SMILES") is True
    finally:
        win.close()


def test_fast_prepare_structure_items_are_blobs_without_hydrate(qapp):  # noqa: ARG001
    win = _seeded_window()
    try:
        win.mols._lru.clear()
        items = win._fast_prepare_structure_items(win._all_oids_in_table_order(), "Structure")
        assert items
        assert all(isinstance(payload, (bytes, bytearray)) and payload for _, payload, _ in items)
        assert len(win.mols._lru) == 0
    finally:
        win.close()


def test_fast_prepare_png_ingest_reuses_store_without_per_oid_delete(qapp):  # noqa: ARG001
    win = _seeded_window()
    try:
        store = StructureRenderStore(max_decoded_pixmaps=8)
        keep_oid = 999
        store.ingest_batch([(keep_oid, b"keep-me")])
        win._table_model.set_structure_png_store(store)
        first = next(iter(win.mols))
        win._table_model._pixmaps[first] = QPixmap()
        removed: list[int] = []

        def _capture_remove(oid: int) -> None:
            removed.append(int(oid))

        store.remove_oid = _capture_remove
        assert win._apply_fast_prepare_pngs([(first, b"new-png")], "Structure") is True
        assert removed == []
        assert store.has_png(keep_oid)
        assert store.png_bytes(first) == b"new-png"
        assert first not in win._table_model._pixmaps
        assert win._table_model._structure_png_store is store
    finally:
        win.close()
