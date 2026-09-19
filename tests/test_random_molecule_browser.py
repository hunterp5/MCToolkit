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

"""Tests for the Random Molecule results browser."""

from __future__ import annotations

import pytest

from molmanager.sources.random_molecule_sources import SOURCE_CHEMBL, RandomSourceMolecule
from molmanager.ui.dockable_plot import is_dockable_workspace_widget
from molmanager.ui.random_molecule_browser import (
    RandomMoleculeBrowserDialog,
    RandomMoleculeBrowserWidget,
    add_random_source_hits_to_table,
)


def _hit(mol_id: str, smiles: str, **fields: str) -> RandomSourceMolecule:
    data = {"Source": "ChEMBL", "ChEMBL_ID": mol_id}
    data.update(fields)
    return RandomSourceMolecule(SOURCE_CHEMBL, mol_id, smiles, data)


def test_random_molecule_browser_widget_is_workspace_dockable():
    assert getattr(RandomMoleculeBrowserWidget, "dockable_in_workspace", False) is True
    assert is_dockable_workspace_widget(RandomMoleculeBrowserWidget)
    assert hasattr(RandomMoleculeBrowserWidget, "create_floating_dialog")


def test_random_molecule_browser_table_and_arrows(qapp):  # noqa: ARG001
    pytest.importorskip("PySide6.QtWidgets")
    hits = [_hit("CHEMBL1", "CCO"), _hit("CHEMBL2", "CCN"), _hit("CHEMBL3", "CCC")]
    w = RandomMoleculeBrowserWidget(None)
    w.set_hits(hits, unique_only=True)
    assert w._table.rowCount() == 3
    headers = [w._table.horizontalHeaderItem(i).text() for i in range(w._table.columnCount())]
    assert headers[:2] == ["ID", "SMILES"]
    assert "Source" in headers
    assert w._table.item(0, 0).text() == "CHEMBL1"
    assert w._table.item(0, 1).text() == "CCO"
    assert w.current_hit() is not None
    assert w.current_hit().smiles == "CCO"
    w._step(1)
    assert w.current_hit().smiles == "CCN"
    assert w._table.currentRow() == 1
    w._go_last()
    assert w.current_hit().smiles == "CCC"
    w._go_first()
    assert w.current_hit().smiles == "CCO"
    assert w._btn_add.text() == "Add to table"
    assert w._btn_add.isEnabled() is False  # no parent app
    assert w._cb_unique.isChecked() is True
    w.close()


def test_random_molecule_browser_dialog_hosts_panel(qapp):  # noqa: ARG001
    pytest.importorskip("PySide6.QtWidgets")
    dlg = RandomMoleculeBrowserDialog(None)
    dlg.set_hits([_hit("CHEMBL1", "CCO")], unique_only=False)
    assert dlg.windowTitle() == "Random Molecule Browser"
    assert dlg._panel.current_hit().smiles == "CCO"
    assert dlg._panel._cb_unique.isChecked() is False
    dlg.close()


def test_add_random_source_hits_skips_duplicate_smiles():
    class _FakeApp:
        def __init__(self):
            self.added = []

        def existing_canonical_structure_keys(self):
            return set()

        def canonical_structure_key_from_smiles(self, smiles: str):
            return smiles.strip()

        def add_rows_from_external_records_batch(self, batch, **_kwargs):
            self.added.extend(batch)
            return len(batch)

    app = _FakeApp()
    hits = [_hit("CHEMBL1", "CCO"), _hit("CHEMBL2", "CCO"), _hit("CHEMBL3", "CCN")]
    added, skipped = add_random_source_hits_to_table(app, hits, unique_only=True)
    assert added == 2
    assert skipped == 1
    assert [smi for smi, _fields in app.added] == ["CCO", "CCN"]
